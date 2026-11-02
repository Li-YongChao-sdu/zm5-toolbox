# -*- coding: utf-8 -*-
"""幻兽试炼（幻兽派遣）编排层。

默认【只读看状态】。写操作都要显式加参数：
  （无参）                  只读：3 个档位现状 + 今日配额 + 可派情况
  --refresh                 刷新任务（优先用每日免费次数，用完自动拒绝）
  --refresh --ticket        强制用点券刷新
  --collect --pos N         给第 N 档派遣（自动挑满足条件的 2 只幻兽）
  --collect --pos N --ids A,B   指定两只幻兽 entityId
  --reward [--pos N]        领取奖励（不指定 pos 则领所有可领的）
  --complete --pos N        用点券(10)立即完成
  --reset --pos N           用点券(100)提前召回
  --buy                     用点券(100)购买今日派遣次数
  --apply                   对所有写操作生效；缺省是预演

用法示例：
  python fairy_run.py
  python fairy_run.py --refresh --apply
  python fairy_run.py --collect --pos 0 --apply
  python fairy_run.py --reward --apply
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fairy_api as api   # noqa: E402
import fairy_data as fd   # noqa: E402

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
    return r.get("info", r)


def _fmt_left(ms):
    if ms <= 0:
        return "已到期"
    secs = int(ms // 1000)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return "%d小时%02d分%02d秒" % (h, m, s)


def get_status(info, config_dir=fd.DEFAULT_CONFIG_DIR):
    """只读状态：3 个档位的任务、奖励、派遣情况、可派性。"""
    help_ = fd.load_help(config_dir)
    tasks = fd.load_tasks(config_dir)
    all_reward_ids = sorted({r for t in tasks.values() for r in t["rewardIds"]})
    rewards = fd.load_rewards(all_reward_ids, config_dir)
    fairies = fd.list_fairies(info, config_dir)
    q = api.quota(info, help_)
    slots = api.slots(info)
    occupied = {entity for slot in slots.values() if api.slot_state(slot)['dispatched']
                for entity in slot.get('fairy', [])}
    # 身上出战的幻兽只展示，不进入自动配对候选（避免派遣已装备幻兽的未验证请求）
    available = [fairy for fairy in fairies
                 if fairy['entityId'] not in occupied and fairy.get('role') is None]

    rows = []
    for pos in range(int(help_["stallNum"])):
        slot = slots.get(pos)
        st = api.slot_state(slot)
        task = tasks.get((slot or {}).get("id"))
        names = {r["subType"]: r["name"]
                 for node in rewards.values() for r in node["items"]}
        # 该档位的奖励：优先用服务器下发的 reward，其次用配表
        slot_reward = None
        if isinstance(slot, dict) and slot.get("reward"):
            slot_reward = []
            for entry_ in slot["reward"]:
                sub = entry_.get("subType")
                try:
                    sub_i = int(sub)
                except (TypeError, ValueError):
                    sub_i = sub
                slot_reward.append({
                    "subType": sub_i,
                    "count": entry_.get("count", 1),
                    "name": names.get(sub_i) or ("item%s" % sub_i),
                })
        pick = fd.pick_fairies(task, available, config_dir) if task else None
        rows.append({
            "pos": pos, "state": st, "task": task,
            "slotReward": slot_reward, "pick": pick,
            "fairyIds": (slot or {}).get("fairy") or [],
        })
    return {"recordName": info.get("name"), "help": help_, "quota": q,
            "slots": rows, "fairies": fairies, "rewards": rewards,
            "tasks": tasks}


def _print_status(st):
    print("存档: %s" % st["recordName"])
    q = st["quota"]
    print("今日配额: 免费刷新 %d/%d（剩 %d）| 点券刷新 %d/%d | 派遣 %d/%d（剩 %d）"
          % (q["refreshFreeUsed"], q["refreshFreeTotal"], q["refreshFreeLeft"],
             q["refreshTicketUsed"], q["refreshTicketTotal"],
             q["sendUsed"], q["sendTotal"], q["sendLeft"]))
    help_ = st["help"]
    print("消耗: 点券刷新 %s/次 | 提前召回 %s | 立即完成 %s | 买次数 %s"
          % (help_["refreshTicket"], help_["sendTicket"],
             help_["completeTicket"], help_["sendTicket"]))

    print("\n=== 三个档位 ===")
    for row in st["slots"]:
        task = row["task"]
        slot_reward = row["slotReward"]
        print("\n[档位 %d] %s" % (row["pos"], _state_text(row["state"])))
        if task:
            line, reward_texts = fd.describe_task(task, st["rewards"])
            print("   任务: %s" % line)
            if task["describe"]:
                print("   要求: %s" % task["describe"].replace("\n", " + "))
            if reward_texts:
                print("   配表奖励: %s" % " / ".join(reward_texts))
        else:
            print("   任务: （服务器给的 id 不在配表里：%s）"
                  % (row["task"] if row["task"] else "无"))
        if slot_reward:
            print("   本档奖励(服务器): %s"
                  % "、".join("%s×%s" % (r["name"], r["count"]) for r in slot_reward))
        if row["fairyIds"]:
            for fid in row["fairyIds"]:
                f = fd.fairy_by_entity(fid, st["fairies"])
                if f:
                    print("   已派幻兽: %s %d阶" % (f["name"], f["step"]))
                else:
                    print("   已派幻兽: %s" % fid)
        pick = row["pick"]
        if pick and not row["state"]["dispatched"]:
            if pick["ok"]:
                print("   可派遣: %s(%d阶) + %s(%d阶)"
                      % (pick["first"]["name"], pick["first"]["step"],
                         pick["second"]["name"], pick["second"]["step"]))
            else:
                print("   不可派遣: %s" % pick["reason"])

    print("\n=== 幻兽 (%d 只, 含身上出战) ===" % len(st["fairies"]))
    for f in st["fairies"]:
        print("  %-12s %d阶  %s%s" % (f["name"], f["step"], f["entityId"],
                                    "" if f.get("role") is None else "（%s）" % f.get("source")))

    # 汇总：哪些档位现在能派、哪些能领
    q = st["quota"]
    alloc = _allocate(st)
    can_collect = [r["pos"] for r in st["slots"]
                   if not r["state"]["dispatched"] and alloc.get(r["pos"], {}).get("ok")]
    claimable = [r["pos"] for r in st["slots"] if r["state"]["claimable"]]
    running = [r["pos"] for r in st["slots"] if r["state"]["state"] == "running"]
    print("\n=== 汇总 ===")
    print("  可派遣档位: %s（今日派遣 %d/%d，剩 %d）"
          % (can_collect or "无", q["sendUsed"], q["sendTotal"], q["sendLeft"]))
    print("  可领取档位: %s" % (claimable or "无"))
    print("  派遣中档位: %s" % (running or "无"))


def _allocate(st):
    """给可派遣的档位各自分配（互不重复的）幻兽组合。

    幻兽只能同时派一处，所以先到先得，后面档位用剩下的幻兽再挑。
    """
    used = set()
    # 正在派遣中的幻兽先占用
    for row in st["slots"]:
        if row["state"]["dispatched"]:
            used.update(row["fairyIds"])
    out = {}
    for row in st["slots"]:
        if row["state"]["dispatched"]:
            continue
        if not row["task"]:
            out[row["pos"]] = {"ok": False, "reason": "任务不在配表里"}
            continue
        pool = [f for f in st["fairies"] if f["entityId"] not in used]
        pick = fd.pick_fairies(row["task"], pool)
        if pick["ok"]:
            used.add(pick["first"]["entityId"])
            used.add(pick["second"]["entityId"])
        out[row["pos"]] = pick
    return out


def _state_text(st):
    return {
        "idle": "空档（可派遣）",
        "running": "派遣中（剩 %s）" % _fmt_left(st["remainMs"]),
        "claimable": "已到期（可领取）",
        "empty": "无数据",
    }.get(st["state"], st["state"])


# ---------- 动作 ----------

def do_refresh(flow, info, apply=False, use_ticket=False,
               config_dir=fd.DEFAULT_CONFIG_DIR):
    help_ = fd.load_help(config_dir)
    q = api.quota(info, help_)
    if not apply:
        if q["refreshFreeLeft"] > 0 and not use_ticket:
            return False, ("预演：将用【免费】刷新（今日剩 %d 次），加 --apply 执行"
                           % q["refreshFreeLeft"]), None
        if use_ticket or q["refreshFreeLeft"] <= 0:
            if q["refreshTicketLeft"] <= 0:
                return False, "预演：点券刷新次数也已达上限（%d/%d）" % (
                    q["refreshTicketUsed"], q["refreshTicketTotal"]), None
            return False, ("预演：将用【点券】刷新，消耗 %d 点券（今日点券刷新 %d/%d），"
                           "加 --apply 执行" % (help_["refreshTicket"],
                                             q["refreshTicketUsed"],
                                             q["refreshTicketTotal"])), None
    if use_ticket:
        if q["refreshTicketLeft"] <= 0:
            return False, ("点券刷新已达今日上限 %d/%d，不刷新"
                           % (q["refreshTicketUsed"], q["refreshTicketTotal"])), None
    else:
        if q["refreshFreeLeft"] <= 0:
            return False, ("今日免费刷新次数已用完（%d/%d），如需继续请加 --ticket "
                           "用点券刷新（%d 点券/次）"
                           % (q["refreshFreeUsed"], q["refreshFreeTotal"],
                              help_["refreshTicket"])), None
    raw = api.refresh(flow, use_ticket=use_ticket, config_dir=config_dir)
    new_q = api.quota_from_reply(raw, help_) or q
    return True, ("已刷新（%s）：免费剩 %d，点券 %d/%d，消耗 %s"
                  % ("点券" if use_ticket else "免费",
                     new_q["refreshFreeLeft"], new_q["refreshTicketUsed"],
                     new_q["refreshTicketTotal"],
                     api.format_give(raw) or "无")), raw


def do_collect(flow, info, pos, ids=None, apply=False,
               config_dir=fd.DEFAULT_CONFIG_DIR):
    if pos is None:
        return False, "派遣需要指定 --pos N", None
    pos = int(pos)
    st = get_status(info, config_dir)
    row = next((r for r in st["slots"] if r["pos"] == int(pos)), None)
    if row is None:
        return False, "档位 %s 不存在" % pos, None
    if row["state"]["dispatched"]:
        return False, "档位 %d 已经派遣过了（%s）" % (pos, _state_text(row["state"])), None
    if st["quota"]["sendLeft"] <= 0:
        return False, ("今日派遣次数已用完（%d/%d）"
                       % (st["quota"]["sendUsed"], st["quota"]["sendTotal"])), None
    if ids:
        fairy_ids = list(ids)
    else:
        pick = row["pick"]
        if not pick or not pick["ok"]:
            return False, "无法自动挑选幻兽：%s" % (
                pick["reason"] if pick else "无任务"), None
        fairy_ids = [pick["first"]["entityId"], pick["second"]["entityId"]]
    if len(fairy_ids) != 2:
        return False, "需要正好 2 只幻兽，当前给了 %d 只" % len(fairy_ids), None
    if not apply:
        return False, ("预演：档位 %d 将派遣 %s，加 --apply 执行"
                       % (pos, " + ".join(fairy_ids))), None
    raw = api.collect(flow, pos, fairy_ids)
    return True, "档位 %d 已派遣 %s（剩余派遣次数 %s）" % (
        pos, " + ".join(fairy_ids),
        (api.quota_from_reply(raw, st["help"]) or st["quota"])["sendLeft"]), raw


def do_reward(flow, info, pos=None, apply=False,
              config_dir=fd.DEFAULT_CONFIG_DIR):
    if pos is not None:
        pos = int(pos)
    st = get_status(info, config_dir)
    targets = [r for r in st["slots"]
               if r["state"]["claimable"] and (pos is None or r["pos"] == int(pos))]
    if not targets:
        if pos is None:
            return False, "没有已到期可领取的档位", None
        row = next((r for r in st["slots"] if r["pos"] == int(pos)), None)
        return False, "档位 %s 不可领取（%s）" % (
            pos, _state_text(row["state"]) if row else "不存在"), None
    if not apply:
        return False, "预演：将领取档位 %s 的奖励，加 --apply 执行" % (
            [t["pos"] for t in targets]), None
    names = {r["subType"]: r["name"]
             for node in st["rewards"].values() for r in node["items"]}
    msgs = []
    last_raw = None
    for t in targets:
        raw = api.get_reward(flow, t["pos"])
        last_raw = raw
        got = api.format_give(raw, names)
        msgs.append("档位 %d%s" % (t["pos"], ("：%s" % got) if got else ""))
    return True, "已领取 " + "；".join(msgs), last_raw


def do_simple(flow, action, pos, apply=False):
    """complete / reset 这类只带 pos 的动作。"""
    if not apply:
        return False, "预演：将执行 %s（档位 %d），加 --apply 执行" % (action, pos), None
    if action == "complete":
        raw = api.complete(flow, pos)
        return True, "档位 %d 已立即完成" % pos, raw
    raw = api.reset(flow, pos)
    return True, "档位 %d 已召回" % pos, raw


def do_buy(flow, info, apply=False, config_dir=fd.DEFAULT_CONFIG_DIR):
    help_ = fd.load_help(config_dir)
    if not apply:
        return False, ("预演：将用 %d 点券购买派遣次数，加 --apply 执行"
                       % help_["sendTicket"]), None
    raw = api.buy_count(flow)
    return True, "已购买派遣次数", raw


# ---------- 命令行 ----------

def _get_arg(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    argv = sys.argv[1:]
    apply = "--apply" in argv
    flow = connect()
    try:
        info = entry(flow)

        if "--refresh" in argv:
            ok, msg, _ = do_refresh(flow, info, apply=("--apply" in argv),
                                    use_ticket=("--ticket" in argv))
            print(msg)
        elif "--collect" in argv:
            pos = _get_arg(argv, "--pos")
            ids = _get_arg(argv, "--ids")
            id_list = [x.strip() for x in ids.split(",")] if ids else None
            ok, msg, _ = do_collect(flow, info, pos, id_list, apply=apply)
            print(msg)
        elif "--reward" in argv:
            pos = _get_arg(argv, "--pos")
            ok, msg, _ = do_reward(flow, info, pos, apply=apply)
            print(msg)
        elif "--complete" in argv or "--reset" in argv:
            action = "complete" if "--complete" in argv else "reset"
            pos = _get_arg(argv, "--pos")
            if pos is None:
                print("需要 --pos N")
            else:
                ok, msg, _ = do_simple(flow, action, int(pos), apply=apply)
                print(msg)
        elif "--buy" in argv:
            ok, msg, _ = do_buy(flow, info, apply=apply)
            print(msg)
        else:
            _print_status(get_status(info))
    finally:
        flow.disconnect()
