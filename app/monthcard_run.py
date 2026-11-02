# -*- coding: utf-8 -*-
"""月卡自动领取 协议层 + 编排层（独立，不改动工具箱已有文件）。

只做【领取】，不做任何购买（不碰 buyMonthCard），因此不会消耗点券/元宝。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import monthcard_data as md  # noqa: E402

TOOLBOX = HERE
sys.path.insert(0, TOOLBOX)
import daily_auto as da  # noqa: E402
from pypomelo.flow import GameLoginFlow  # noqa: E402
from pypomelo.login4399 import fetch_game_token  # noqa: E402

_ACCT = {
    "uid": da.UID,
    "username": da.USERNAME,
    "record_index": da.RECORD_INDEX,
    "cookies": da.COOKIES,
}


def use_account(name):
    """加载本目录下 account_<name>.local.json 覆盖默认账号。"""
    path = os.path.join(HERE, "account_%s.local.json" % name)
    if not os.path.exists(path):
        raise RuntimeError("找不到账号文件 %s" % path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _ACCT.update({
        "uid": data["uid"],
        "username": data["username"],
        "record_index": int(data.get("record_index", 0)),
        "cookies": data["cookies"],
    })
    return _ACCT


def use_slot(slot):
    _ACCT["record_index"] = int(slot)
    return _ACCT


def connect():
    token = fetch_game_token(_ACCT["uid"], _ACCT["username"], _ACCT["cookies"])
    for ip in da.GATE_IPS:
        flow = GameLoginFlow(uid=_ACCT["uid"], token=token)
        try:
            host, port = flow.query_entry(ip, da.PORT)
            auth = flow.auth(host, port)
            if isinstance(auth, dict) and auth.get("code") == 200:
                return flow
            flow.disconnect()
        except Exception:
            flow.disconnect()
    raise RuntimeError("connect fail")


def entry(flow, record_index=None):
    """进指定存档（默认用当前 _ACCT 的槽位）。"""
    idx = _ACCT["record_index"] if record_index is None else int(record_index)
    r = flow.request("connector.entryHandler.entry",
                     {"index": idx, "userAgent": flow.user_agent})
    return r.get("info", r)


# ---------- 协议 ----------

def _ok(result):
    return isinstance(result, dict) and not result.get("error") \
        and result.get("code", 200) == 200


def claim_reward(flow):
    """调用领取接口（空参）。返回原始回包。"""
    return flow.request(md.ROUTE_GET_REWARD, {})


def give_items(raw):
    """回包里的奖励条目。"""
    for field in ("give", "reward"):
        rows = (raw or {}).get(field)
        if isinstance(rows, list) and rows:
            return rows
    return []


def format_give(raw):
    rows = give_items(raw)
    if not rows:
        return ""
    parts = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        parts.append("%s×%s" % (r.get("subType") or r.get("type"),
                                r.get("count", 1)))
    return "、".join(parts)


def do_claim(flow, info, cfg=None, config_dir=md.DEFAULT_CONFIG_DIR,
             force=False):
    """领取今日月卡元宝。返回 (ok, message, raw)。

    默认会先查状态：只要今天已领过就直接跳过，不打扰服务器。
    force=True 时无视本地判断直接调用（用于验证）。
    """
    st = md.claim_state(info, cfg, config_dir)
    if not st["activeCards"]:
        expired = st["expiredUnclaimed"]
        extra = ("（已过期未领的卡：%s，服务器不会补发）"
                 % "、".join(st["cards"][c]["name"] for c in expired)) if expired else ""
        return False, "没有生效中的月卡，无需领取%s" % extra, None
    if not st["needClaim"] and not force:
        names = [st["cards"][c]["name"] for c in st["activeCards"]
                 if st["cards"][c]["claimedToday"]]
        return False, "今天已领过（%s），跳过" % ("、".join(names) or "生效中的卡"), None

    raw = claim_reward(flow)
    if not _ok(raw):
        err = (raw or {}).get("error") or (raw or {}).get("msg") or raw
        return False, "领取失败：%s" % err, raw
    got = format_give(raw)
    return True, "领取成功%s" % (("：%s" % got) if got else ""), raw


# ---------- 多槽位 / 批量 ----------

def scan_slots(flow, slots=range(8), cfg=None, config_dir=md.DEFAULT_CONFIG_DIR):
    """扫描若干存档的月卡状态。返回 {slot: {"name","state"}}。

    读取失败（空槽/超时）会在结果里标注，不抛出。
    """
    cfg = cfg or md.load_cards(config_dir)
    out = {}
    for slot in slots:
        try:
            info = entry(flow, slot)
        except Exception as e:
            out[int(slot)] = {"name": None, "state": None, "error": str(e)}
            continue
        if not isinstance(info, dict) or not info.get("name"):
            out[int(slot)] = {"name": None, "state": None, "error": "空槽或无数据"}
            continue
        out[int(slot)] = {
            "name": info.get("name"),
            "state": md.claim_state(info, cfg, config_dir),
            "error": None,
        }
    return out


def claim_all_slots(flow, slots=None, cfg=None, config_dir=md.DEFAULT_CONFIG_DIR,
                    progress=None):
    """批量领取：扫一遍所有槽，只对"需要领取"的槽调用领取接口。

    返回 {"results": {slot: {...}}, "claimed": [slot...], "skipped": [...],
          "failed": [...], "noCard": [...]}
    """
    cfg = cfg or md.load_cards(config_dir)
    if slots is None:
        slots = list(range(8))
    results = {}
    claimed, skipped, failed, no_card = [], [], [], []

    for slot in slots:
        slot = int(slot)
        try:
            info = entry(flow, slot)
        except Exception as e:
            results[slot] = {"ok": False, "msg": "读取存档失败: %s" % e}
            failed.append(slot)
            if progress:
                progress(slot, "读取失败: %s" % e)
            continue
        st = md.claim_state(info, cfg, config_dir)
        name = info.get("name")
        if not st["activeCards"]:
            results[slot] = {"ok": False, "msg": "无生效月卡", "name": name,
                             "state": st}
            no_card.append(slot)
            if progress:
                progress(slot, "无生效月卡")
            continue
        if not st["needClaim"]:
            results[slot] = {"ok": False, "msg": "今日已领", "name": name,
                             "state": st}
            skipped.append(slot)
            if progress:
                progress(slot, "今日已领，跳过")
            continue
        raw = claim_reward(flow)
        if _ok(raw):
            got = format_give(raw)
            results[slot] = {"ok": True, "msg": "领取成功" + (("：%s" % got) if got else ""),
                             "name": name, "raw": raw, "state": st}
            claimed.append(slot)
            if progress:
                progress(slot, "领取成功" + (("：%s" % got) if got else ""))
        else:
            err = (raw or {}).get("error") or (raw or {}).get("msg") or raw
            results[slot] = {"ok": False, "msg": "领取失败：%s" % err,
                             "name": name, "raw": raw, "state": st}
            failed.append(slot)
            if progress:
                progress(slot, "领取失败：%s" % err)

    return {"results": results, "claimed": claimed, "skipped": skipped,
            "failed": failed, "noCard": no_card}


# ---------- 命令行 ----------

def _get_arg(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _print_status(info, cfg, only=None):
    """only: None=全部 / "super"=只看超值月卡 / "sweep"=只看速通月卡。"""
    if only in ("super", "sweep"):
        st = (md.super_card_state(info) if only == "super"
              else md.sweep_card_state(info))
        label = "超值月卡" if only == "super" else "速通月卡(扫荡月卡)"
        cid = md.SUPER_CARD_ID if only == "super" else md.SWEEP_CARD_ID
        print("存档: %s" % info.get("name"))
        print("今日 key = %s（服务器时间）" % st["todayKey"])
        if not st["owned"]:
            print("%s: 未持有" % label)
            return
        c = st["card"]
        print("%s(%d): 每日%s元宝  生效中=%s  今日已领=%s  已领天数=%s"
              % (label, cid, c.get("dailyYuanbao"), c["active"],
                 c["claimedToday"], c["days"]))
        print("整账号今日是否需要领取: %s"
              % ("是" if st["overallNeedClaim"] else "否（今天已领过）"))
        print("领取路由: %s {}（与其它月卡共用，空参一次结算）"
              % md.ROUTE_GET_REWARD)
        if only == "sweep":
            buff = md.load_sweep_buff()
            if buff:
                print("附赠特权: BuffScene[%s]「%s」— %s（持续%d秒）"
                      % (buff["id"], buff["name"], buff["describe"],
                         buff.get("continueTime") or 0))
        return

    st = md.claim_state(info, cfg)
    print("存档: %s" % info.get("name"))
    print("今日 key = %s（服务器时间）" % st["todayKey"])
    print("生效中的月卡: %s" % (st["activeCards"] or "无"))
    print("今日需要领取: %s" % ("是" if st["needClaim"] else "否"))
    print("\n持有月卡明细:")
    for cid in sorted(st["cards"], key=lambda x: int(x)):
        c = st["cards"][cid]
        tag = "  [扫荡页签]" if c.get("isSweepCard") else ""
        print("  id=%-2s %-6s 每日%-5s元宝 生效中=%-5s 今日已领=%-5s 已领天数=%s%s"
              % (cid, c["name"], c.get("dailyYuanbao"), c["active"],
                 c["claimedToday"], c["days"], tag))
    if st["expiredUnclaimed"]:
        print("\n已过期且今日未领（服务器不会补发）: %s"
              % "、".join(st["cards"][c]["name"] for c in st["expiredUnclaimed"]))
    print("\n注：5 种月卡（含速通/扫荡月卡）共用同一条领取路由 %s {}，"
          "一次调用结算全部生效卡。" % md.ROUTE_GET_REWARD)


def _print_batch(scan):
    """打印多槽位扫描结果。"""
    print("%-5s %-14s %s" % ("槽", "角色", "今日是否需要领取"))
    for slot in sorted(scan):
        row = scan[slot]
        if row.get("error"):
            print("  %-3d %-12s 读取失败: %s" % (slot, "-", row["error"]))
            continue
        st = row["state"]
        cards = st["cards"]
        marks = []
        for cid in sorted(cards, key=lambda x: int(x)):
            c = cards[cid]
            if c["active"]:
                marks.append("%s(%s)%s" % (c["name"], c.get("dailyYuanbao"),
                                           "已领" if c["claimedToday"] else "★未领"))
            elif not c["claimedToday"]:
                marks.append("%s(已过期)" % c["name"])
        need = "★需要领取" if st["needClaim"] else "无需"
        print("  %-3d %-12s %s   %s"
              % (slot, str(row["name"])[:12], need, " ".join(marks) or "无月卡"))


if __name__ == "__main__":
    argv = sys.argv[1:]
    apply_ = "--apply" in argv
    account = _get_arg(argv, "--account")
    slot = _get_arg(argv, "--slot")
    slots_arg = _get_arg(argv, "--slots")
    all_slots = "--all-slots" in argv
    only = None
    if "--super" in argv:
        only = "super"
    elif "--sweep" in argv:
        only = "sweep"
    force = "--force" in argv
    if account:
        use_account(account)
    if slot is not None:
        use_slot(slot)

    cfg = md.load_cards()
    slots = None
    if slots_arg:
        slots = [int(x) for x in slots_arg.replace(",", " ").split()]
    elif all_slots:
        slots = list(range(8))

    flow = connect()
    try:
        if slots is not None:
            # 多槽位模式
            if not apply_:
                _print_batch(scan_slots(flow, slots, cfg))
                print("\n（只读模式；加 --apply 批量领取。只领取、不购买，不消耗点券）")
            else:
                print("开始批量领取（只处理需要领取的槽）...")
                res = claim_all_slots(
                    flow, slots, cfg,
                    progress=lambda s, m: print("  槽%-3d %s" % (s, m)))
                print("\n=== 汇总 ===")
                print("  领取成功: %s" % (res["claimed"] or "无"))
                print("  今日已领跳过: %s" % (res["skipped"] or "无"))
                print("  无生效月卡: %s" % (res["noCard"] or "无"))
                print("  失败: %s" % (res["failed"] or "无"))
                print("\n领取后复查:")
                _print_batch(scan_slots(flow, slots, cfg))
        else:
            # 单槽位模式
            info = entry(flow)
            if not apply_:
                _print_status(info, cfg, only)
                print("\n（只读模式；加 --apply 才领取。本模块只领取、不购买，不消耗点券）")
            else:
                ok, msg, raw = do_claim(flow, info, cfg, force=force)
                print(("[OK] " if ok else "[--] ") + msg)
                if raw is not None:
                    print("回包: %s" % json.dumps(raw, ensure_ascii=False)[:400])
                _print_status(entry(flow), cfg, only)
    finally:
        flow.disconnect()
