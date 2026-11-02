# -*- coding: utf-8 -*-
"""幻兽灵魂喂养 编排层（自选幻兽 + 当日喂满）。

默认【只读看状态】。真正喂养要显式加 --apply：
  （无参）                     只读：配额、每只幻兽单次消耗与喂满预估
  --feed --entity <entityId> --apply    给指定幻兽喂到今日上限
  --feed --name 金莲 --apply            按名字选（唯一匹配才行）
  --feed --ordinal 1 --apply            按序号选（1 起，等级降序）
  --feed ... --times N --apply          只喂 N 次，不喂满
  --feed ... --item --apply             用妖元喂养（feedId=99999，不吃每日次数）
  --feed ... --both --apply             对背包幻兽同时按1p/2p各喂一遍（各自扣次数）
  --role 0|1（或 1p/2p）                指定出战角色；主/副角色每日次数各自独立

示例：
  python fairy_feed_run.py
  python fairy_feed_run.py --feed --name 金莲 --apply
  python fairy_feed_run.py --feed --entity 570714954_r0_190040001_0f --apply
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fairy_feed_api as api    # noqa: E402
import fairy_feed_data as ffd   # noqa: E402

TOOLBOX = HERE
sys.path.insert(0, TOOLBOX)
import daily_auto as da  # noqa: E402
from pypomelo.flow import GameLoginFlow  # noqa: E402
from pypomelo.login4399 import fetch_game_token  # noqa: E402


def connect():
    token = fetch_game_token(da.UID, da.USERNAME, da.COOKIES)
    for ip in da.GATE_IPS:
        flow = GameLoginFlow(uid=da.UID, token=token)
        try:
            host, port = flow.query_entry(ip, da.PORT)
            auth = flow.auth(host, port)
            if isinstance(auth, dict) and auth.get("code") == 200:
                return flow
            flow.disconnect()
        except Exception:
            flow.disconnect()
    raise RuntimeError("connect fail")


def entry(flow):
    r = flow.request("connector.entryHandler.entry",
                     {"index": da.RECORD_INDEX, "userAgent": flow.user_agent})
    if not isinstance(r, dict) or r.get('code') != 200 or r.get('error') or not isinstance(r.get('info'), dict):
        raise RuntimeError('读取当前存档失败，停止后续操作')
    return r['info']


def _parse_role(argv):
    """--role 0/1（也接受 1p/2p）。默认主角色0。"""
    raw = _get_arg(argv, "--role")
    if raw is None:
        return 0
    text = str(raw).strip().lower()
    if text in ("1p", "p1", "主", "主角色"):
        return 0
    if text in ("2p", "p2", "副", "副角色"):
        return 1
    try:
        role = int(text)
    except (TypeError, ValueError):
        raise ValueError("--role 须为 0(主角色/1p) 或 1(副角色/2p)")
    if role not in (0, 1):
        raise ValueError("--role 须为 0(主角色/1p) 或 1(副角色/2p)")
    return role


def get_status(info, cfg=None, role=0):
    cfg = cfg or ffd.FeedConfig()
    role = ffd.role_index(info, role)
    fairies = ffd.list_fairies(info)
    feedable = ffd.feedable_fairies(info, role)
    quotas = {str(r): ffd.feed_quota(info, cfg, r) for r in (0, 1)}
    spirit = info.get("spirit")
    plans = []
    for f in feedable:
        plans.append({"fairy": f, "plan": ffd.plan_feeds(info, f, cfg, role=role)})
    return {"recordName": info.get("name"), "spirit": spirit,
            "role": role,
            "charLevel": ffd.role_char_level(info, role),
            "charLevels": {str(r): ffd.role_char_level(info, r) for r in (0, 1)},
            "quota": quotas[str(role)], "quotas": quotas,
            "fairies": feedable, "allFairies": fairies, "plans": plans,
            "itemTier": cfg.item_tier()}


def emit_state(info):
    payload={'uid':str(da.UID),'slot':int(da.RECORD_INDEX),'recordName':info.get('name'),
             'fairies':ffd.list_fairies(info),'quota':ffd.feed_quota(info),
             'quotas':{'0':ffd.feed_quota(info,role=0),'1':ffd.feed_quota(info,role=1)}}
    print('__FAIRY_FEED_STATE__'+json.dumps(payload,ensure_ascii=False),flush=True)


def _print_status(st):
    q = st["quota"]
    print("存档: %s  角色等级 主%s/副%s  灵魂 %s" % (
        st["recordName"], st["charLevels"]["0"], st["charLevels"]["1"],
        st["spirit"]))
    print("今日灵魂喂养（主/副角色独立计数，同角色幻兽共用）：")
    for role, label in ((0, "主角色(1p)"), (1, "副角色(2p)")):
        item = st["quotas"][str(role)]
        print("  %s: 已用 %d / %d（剩 %d）  配额 feedDayNum=%d + VIP%d 加成 %d"
              % (label, item["used"], item["total"], item["left"],
                 item["base"], item["vipLevel"], item["vipBonus"]))
    print("  [每条计数按 everyDaySetting.feedDayNum_0/1，非按幻兽]")

    print("\n=== 幻兽（%s 可喂，喂满预估）==="
          % ("主角色" if st["role"] == 0 else "副角色"))
    for row in st["plans"]:
        f = row["fairy"]
        p = row["plan"]
        print("\n%s  Lv%d %s阶  exp %s/%s" % (
            f["name"], f["level"], f["step"], f["exp"], f["expNeed"]))
        print("  entityId: %s" % f["entityId"])
        print("  喂满今日次数：%d 次，消耗灵魂 %s，Lv%d -> Lv%d"
              % (p["feeds"], p["spiritCost"], p["levelFrom"], p["levelTo"]))
        if p["stops"]:
            print("  停止原因: %s" % stop_text(p["stops"]))

    item = st.get("itemTier")
    if item:
        print("\n妖元喂养（不吃每日次数）：消耗 %s×%s，+经验%s，暴击率%s"
              % (item["consumeSubType"], item["consumeCount"],
                 item["fairyExpAdd"], item["critRate"]))


def stop_text(stops):
    return "、".join(api.STOP_TEXT.get(s, s) for s in stops)


def do_feed(flow, info, entity_id=None, name=None, ordinal=None,
            times=None, use_item=False, cfg=None, role=0):
    cfg = cfg or ffd.FeedConfig()
    role = ffd.role_index(info, role)
    fairy, err = ffd.pick_fairy(info, entity_id=entity_id, name=name,
                                ordinal=ordinal, role=role)
    if fairy is None:
        return False, err, None
    if use_item:
        item = cfg.item_tier()
        if not item:
            return False, "配表缺少妖元档", None
        try:
            raw = api.feed_once(flow, fairy["entityId"], ffd.ITEM_FEED_ID,
                                role)
        except Exception as e:
            return False, str(e), None
        return True, ("%s 妖元喂养成功：+%s经验%s"
                      % (fairy["name"], api.add_exp(raw),
                         "（暴击）" if api.is_crit(raw) else "")), raw

    if times is not None:
        times = int(times)
    max_feeds = times if times else None
    result = api.feed_to_limit(flow, info, fairy, cfg, max_feeds=max_feeds,
                               progress=lambda s: print("  " + s), role=role)
    stop = result["stop"]
    msg = ("%s（%s）：喂了 %d 次，共 +%s 经验（暴击 %d 次），消耗灵魂 %s，"
           "Lv%d -> Lv%d；停止原因：%s"
           % (fairy["name"], "主角色" if role == 0 else "副角色",
              result["feeds"], result["addExp"],
              result["crits"], result["spiritCost"],
              result["levelFrom"], result["levelTo"],
              api.STOP_TEXT.get(stop, stop or "未知")))
    if result["feeds"] == 0 and stop == "daily":
        msg = "%s今日灵魂喂养次数已用完（%d/%d），未喂养" % (
            "主角色" if role == 0 else "副角色",
            result["quota"]["used"], result["quota"]["total"])
    return result["feeds"] > 0, msg, result


def do_feed_both(flow, info, times=None, cfg=None):
    """同时喂养1p/2p身上出战的幻兽，各自扣各自的每日次数。

    实测服务器按幻兽所在角色计次（背包幻兽记主角色），所以同时喂养只喂两位
    角色身上的幻兽；某位身上没幻兽就跳过该位。
    """
    cfg = cfg or ffd.FeedConfig()
    parts = []
    rows = []
    ok_any = False
    for role, label in ((0, "1p"), (1, "2p")):
        cur = info if role == 0 else entry(flow)
        if role == 1:
            info = cur
        body = [f for f in ffd.list_fairies(cur) if f.get("role") == role]
        if not body:
            msg = "%s：%s身上没有幻兽，跳过" % (label, "主角色" if role == 0 else "副角色")
            parts.append(msg)
            rows.append({"role": role, "ok": False, "msg": msg, "result": None})
            continue
        fairy = body[0]
        ok, msg, res = do_feed(flow, cur, entity_id=fairy["entityId"],
                               times=times, cfg=cfg, role=role)
        parts.append(msg)
        rows.append({"role": role, "ok": ok, "msg": msg, "result": res})
        ok_any = ok_any or ok
    return ok_any, "\n".join(parts), {"both": rows}


def _get_arg(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    argv = sys.argv[1:]
    apply_ = "--apply" in argv
    expected_uid = _get_arg(argv, '--expected-uid')
    expected_slot = _get_arg(argv, '--expected-slot')
    if expected_uid is not None and str(da.UID) != expected_uid:
        raise ValueError('当前账号与下拉列表不一致，未执行喂养')
    if expected_slot is not None and int(da.RECORD_INDEX) != int(expected_slot):
        raise ValueError('当前存档与下拉列表不一致，未执行喂养')
    flow = connect()
    try:
        info = entry(flow)
        role = _parse_role(argv)
        if "--feed" in argv:
            entity_id = _get_arg(argv, "--entity")
            name = _get_arg(argv, "--name")
            ordinal = _get_arg(argv, "--ordinal")
            times = _get_arg(argv, "--times")
            use_item = "--item" in argv
            both = "--both" in argv
            if both and use_item:
                print("妖元喂养不占角色次数，无需同时喂养；请去掉 --item 或 --both")
            elif both:
                if not apply_:
                    cfg = ffd.FeedConfig()
                    q0 = ffd.feed_quota(info, cfg, 0)
                    q1 = ffd.feed_quota(info, cfg, 1)
                    for role, label, quota in ((0, "1p", q0), (1, "2p", q1)):
                        body = [f for f in ffd.list_fairies(info)
                                if f.get("role") == role]
                        target = body[0]["name"] if body else "身上没有幻兽，跳过"
                        print("  预演 %s: %s（剩%d次）" % (label, target, quota["left"]))
                    n = int(times) if times else "各自喂满"
                    print("将按1p/2p分别喂养 %s；加 --apply 才会真正执行" % n)
                else:
                    ok, msg, _ = do_feed_both(flow, info, times=times)
                    print(msg)
            elif not apply_:
                # 预演：只显示会喂哪只、喂几次、花多少
                fairy, err = ffd.pick_fairy(info, entity_id=entity_id,
                                            name=name, ordinal=ordinal,
                                            role=role)
                if fairy is None:
                    print(err)
                else:
                    cfg = ffd.FeedConfig()
                    plan = ffd.plan_feeds(info, fairy, cfg, role=role)
                    n = int(times) if times else plan["feeds"]
                    print("预演：将对%s %s (Lv%d) 喂养 %s 次"
                          % ("主角色" if role == 0 else "副角色",
                             fairy["name"], fairy["level"],
                             ("妖元" if use_item else n)))
                    print("  今日该角色剩余次数 %d，预计消耗灵魂 %s"
                          % (plan["quota"]["left"],
                             plan["spiritCost"] if not times else "?"))
                    print("  加 --apply 才会真正执行")
            else:
                ok, msg, _ = do_feed(flow, info, entity_id, name, ordinal,
                                     times, use_item, role=role)
                print(msg)
        else:
            _print_status(get_status(info, role=role))
        latest = entry(flow) if '--feed' in argv and apply_ else info
        emit_state(latest)
    finally:
        flow.disconnect()
