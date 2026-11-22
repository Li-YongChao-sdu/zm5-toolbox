"""临时诊断：验证通天河同一艘船能否被抢第三次。

不修改 tongtian_rob.py 的默认 ROBBED_MAX，只在本次进程内放宽。
用法：
  python tongtian_third_probe.py --mode observe
  python tongtian_third_probe.py --mode single --slot 0 --execute
  python tongtian_third_probe.py --mode concurrent --accounts a,b,c --slots 0,0,0 --execute
"""
import argparse
import json
import threading
import time
from pathlib import Path

import tongtian_rob as tr

HERE = Path(__file__).resolve().parent
ACCOUNTS_DIR = HERE / "accounts"
OUT = HERE / "tongtian_third_probe_result.json"


def _load_account(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _account_paths(names):
    if names:
        return [ACCOUNTS_DIR / (name.strip() + ".json") for name in names.split(",") if name.strip()]
    return sorted(ACCOUNTS_DIR.glob("*.json"))


def _entry(flow, slot):
    reply = flow.request("connector.entryHandler.entry",
                         {"index": slot, "userAgent": flow.user_agent})
    return reply.get("info") if isinstance(reply, dict) else None


def _used(info):
    return int(((info or {}).get("everyDaySetting") or {}).get("tongtianRiverRobNum") or 0)


def _events(flow, uid):
    reply = flow.request("scene.tongtianHandler.getRobEvent", {"targetId": uid})
    events = reply.get("event") if isinstance(reply, dict) else None
    if isinstance(events, str):
        try:
            events = json.loads(events)
        except ValueError:
            events = None
    return events if isinstance(events, list) else []


def _list_ships(flow, info):
    player = (info or {}).get("p1") or {}
    if not player.get("level") or not player.get("fightPower"):
        return [], "没有可用角色或战力"
    reply = flow.request("scene.tongtianHandler.getEscortList", {})
    error = tr._error(reply)
    if error:
        return [], error
    ships = tr._ships(reply, int(player["level"]), float(player["fightPower"]),
                      info.get("uid") or player.get("uid"), full_reward_only=False)
    return ships, ""


def _pick(ships):
    """优先海舰，其次被抢次数少的，再选刚开不久的。"""
    if not ships:
        return None
    return sorted(ships, key=lambda s: (-s["tier"], s["robbed"], -s["start_ms"]))[0]


def _public(ship, events=None):
    return {"uid": ship["uid"], "owner": ship.get("owner", ""),
            "good_id": ship.get("good_id"), "tier": ship["tier"], "robbed": ship["robbed"],
            "events": len(events) if events is not None else None,
            "start_ms": ship["start_ms"], "end_ms": ship["end_ms"]}


def _resolve_account(value):
    if not value:
        return HERE / "account.local.json"
    path = Path(value)
    if path.exists():
        return path
    name = value if value.endswith(".json") else value + ".json"
    for base in (ACCOUNTS_DIR, HERE):
        candidate = base / name
        if candidate.exists():
            return candidate
    raise SystemExit("找不到账号文件：%s" % value)


def _connect_named(account, slot):
    import teacher_trial
    return teacher_trial.connect(account, int(slot))


def _single(account_path, slot, max_wait, battle_wait, owner=None, target_uid=None, direct=False):
    import daily_auto
    if account_path:
        flow, info = _connect_named(_load_account(account_path), slot)
    else:
        flow, info = daily_auto.login(record_index=slot)
    flow._tongtian_battle_wait = battle_wait
    result = {"mode": "single", "slot": slot, "owner": owner,
              "target_uid": target_uid, "direct": direct, "attempts": []}
    try:
        tr.ROBBED_MAX = 99
        deadline = time.monotonic() + max_wait
        ship = None
        if direct and target_uid:
            now_ms = int(time.time() * 1000)
            ship = {"uid": int(target_uid), "tier": 4, "robbed": 0,
                    "start_ms": 0, "end_ms": now_ms + 15 * 60 * 1000,
                    "now_ms": now_ms, "server_offset_ms": 0}
            result["target"] = _public(ship)
        while ship is None and time.monotonic() < deadline:
            ships, error = _list_ships(flow, info)
            if target_uid:
                ships = [s for s in ships if int(s["uid"]) == int(target_uid)]
            elif owner:
                ships = [s for s in ships if s.get("owner") == owner]
            if ships:
                ship = _pick(ships)
                break
            hint = "等待%s的船" % owner if owner else "等待可用船"
            print("[单账号] %s：%s" % (hint, error or "暂无候选"), flush=True)
            time.sleep(8)
        if ship is None:
            result["error"] = "等待超时，没有可用船"
            return result
        result["target"] = _public(ship)
        result["used_before"] = _used(info)
        for index in range(3):
            events = _events(flow, ship["uid"])
            ship["robbed"] = len(events)
            if len(events) >= 3:
                print("[单账号] 目标已被抢3次，不再尝试", flush=True)
                break
            ship["next_check"] = 0
            ship["next_attempt"] = 0
            ship["last_error"] = None
            print("[单账号] 第%d次尝试，当前 robEvents=%d" % (index + 1, len(events)), flush=True)
            try:
                ok = tr._attack(flow, ship, deadline)
            except Exception as exc:
                result["attempts"].append({"index": index + 1, "error": "%s: %s" % (type(exc).__name__, exc)})
                break
            fresh = _entry(flow, slot)
            used = _used(fresh)
            after = _events(flow, ship["uid"])
            result["attempts"].append({"index": index + 1, "ok": ok is True,
                                       "used": used, "events": len(after),
                                       "robbed": ship.get("robbed")})
            print("[单账号] 第%d次结果 ok=%s，robEvents=%d，今日已用%d/4" %
                  (index + 1, ok, len(after), used), flush=True)
            if ok is not True:
                break
        result["used_after"] = _used(_entry(flow, slot))
        result["final_events"] = len(_events(flow, ship["uid"]))
        return result
    finally:
        flow.disconnect()


def _build_sessions(accounts, slots):
    sessions = []
    for account, slot in zip(accounts, slots):
        try:
            flow, info = _connect_named(account, slot)
            ships, error = _list_ships(flow, info)
        except Exception as exc:
            print("[并发] %s 槽%d 连接失败，跳过：%s: %s" %
                  (account.get("username") or account.get("uid"), slot,
                   type(exc).__name__, exc), flush=True)
            continue
        level = (info.get("p1") or {}).get("level")
        print("[并发] %s 槽%d 等级%s 今日已抢%d 可见%d艘 %s" %
              (account.get("username") or account.get("uid"), slot, level,
               _used(info), len(ships), error), flush=True)
        sessions.append({"flow": flow, "info": info, "slot": slot,
                         "name": account.get("username") or account.get("uid"),
                         "level": level or 0,
                         "ships": {s["uid"]: s for s in ships}})
    return sessions


def _common_target(sessions):
    """找至少3个账号都能抢的船；优先海舰、0次被抢、剩余时间长的。"""
    counts = {}
    for session in sessions:
        for uid in session["ships"]:
            counts[uid] = counts.get(uid, 0) + 1
    candidates = {}
    for session in sessions:
        for uid, ship in session["ships"].items():
            if counts.get(uid, 0) >= 3 and uid not in candidates:
                candidates[uid] = ship
    return _pick(list(candidates.values()))


def _run_concurrent(sessions, target, max_wait, battle_wait):
    result = {"mode": "concurrent", "target": _public(target),
              "accounts": [{"name": s["name"], "slot": s["slot"], "level": s["level"],
                            "used": _used(s["info"])} for s in sessions],
              "attempts": []}
    deadline = time.monotonic() + max_wait
    barrier = threading.Barrier(len(sessions))
    lock = threading.Lock()

    def worker(session):
        ship = dict(target)
        ship.update(session["ships"].get(target["uid"], {}))
        session["flow"]._tongtian_battle_wait = battle_wait
        offset = ship.setdefault("server_offset_ms", ship["now_ms"] - time.time() * 1000)
        ready = ship["start_ms"] + 60.1 * 1000
        wait = (ready - (time.time() * 1000 + offset)) / 1000
        if wait > 0:
            time.sleep(min(wait, max(0, deadline - time.monotonic())))
        try:
            barrier.wait(timeout=30)
        except threading.BrokenBarrierError:
            pass
        print("[并发] %s 开始抢 %s" % (session["name"], target["uid"]), flush=True)
        try:
            ok = tr._attack(session["flow"], ship, deadline)
            row = {"name": session["name"], "ok": ok is True,
                   "used": _used(_entry(session["flow"], session["slot"]))}
        except Exception as exc:
            row = {"name": session["name"], "error": "%s: %s" % (type(exc).__name__, exc)}
        with lock:
            result["attempts"].append(row)
        print("[并发] %s 结果 %s" % (session["name"], row), flush=True)

    threads = [threading.Thread(target=worker, args=(session,), daemon=True) for session in sessions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max_wait + 60)
    result["final_events"] = len(_events(sessions[0]["flow"], target["uid"]))
    return result


def _concurrent(paths, slots, max_wait, battle_wait, auto):
    accounts = [_load_account(path) for path in paths]
    slots = [int(v) for v in slots if str(v).strip()]
    if len(slots) < len(accounts):
        slots += [int(a.get("record_index") or 0) for a in accounts[len(slots):]]
    tr.ROBBED_MAX = 99
    sessions = _build_sessions(accounts, slots)
    try:
        target = _common_target(sessions)
        if target is None:
            return {"mode": "concurrent", "error": "没有至少3个账号都能抢的船"}
        chosen = [s for s in sessions if target["uid"] in s["ships"]]
        if auto:
            chosen = sorted(chosen, key=lambda s: (_used(s["info"]) >= 4, -int(s["level"] or 0)))[:3]
        elif len(chosen) > 3:
            chosen = chosen[:3]
        if len(chosen) < 3:
            return {"mode": "concurrent", "error": "能抢同一艘船的账号不足3个"}
        return _run_concurrent(chosen, target, max_wait, battle_wait)
    finally:
        for session in sessions:
            try:
                session["flow"].disconnect()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("observe", "single", "concurrent"), default="observe")
    parser.add_argument("--slot", type=int, default=0)
    parser.add_argument("--accounts", help="逗号分隔的账号文件名，不含 .json")
    parser.add_argument("--account", help="单账号测试用的账号文件，如 xyh13416626694")
    parser.add_argument("--owner", help="按船主昵称筛选，如 李西城")
    parser.add_argument("--target-uid", type=int, help="直接指定船的 UID")
    parser.add_argument("--direct", action="store_true", help="不查列表，直接用 targetId 发抢船命令")
    parser.add_argument("--slots", default="0,0,0", help="逗号分隔的存档槽位")
    parser.add_argument("--max-wait", type=int, default=900)
    parser.add_argument("--battle-wait", type=int, default=25)
    parser.add_argument("--execute", action="store_true", help="实际发起抢船；不加只读")
    args = parser.parse_args()
    paths = [_resolve_account(args.account)] if args.account and not args.accounts \
        else _account_paths(args.accounts)
    if not args.execute and args.mode != "observe":
        args.mode = "observe"
    if args.mode == "observe":
        result = {"mode": "observe", "owner": args.owner, "accounts": []}
        for path in paths[:10]:
            account = _load_account(path)
            flow, info = _connect_named(account, int(account.get("record_index") or 0))
            try:
                ships, error = _list_ships(flow, info)
                if args.owner:
                    ships = [s for s in ships if s.get("owner") == args.owner]
                result["accounts"].append({"name": account.get("username"),
                                           "nick": (info or {}).get("name"),
                                           "role": (info.get("p1") or {}).get("name"),
                                           "level": (info.get("p1") or {}).get("level"),
                                           "used": _used(info), "ships": len(ships), "error": error,
                                           "candidates": [_public(s) for s in ships[:5]]})
                print("[观察] %s %s 等级%s 今日已抢%d 可见%d艘 %s" %
                      ((info or {}).get("name"), (info.get("p1") or {}).get("name"),
                       (info.get("p1") or {}).get("level"),
                       _used(info), len(ships), error), flush=True)
                for ship in ships[:5]:
                    print("  uid=%s owner=%s good_id=%s 被抢%d" %
                          (ship["uid"], ship.get("owner"), ship.get("good_id"), ship["robbed"]), flush=True)
            finally:
                flow.disconnect()
    elif args.mode == "single":
        result = _single(_resolve_account(args.account), args.slot, args.max_wait,
                         args.battle_wait, owner=args.owner, target_uid=args.target_uid,
                         direct=args.direct)
    else:
        slots = [int(v) for v in args.slots.split(",") if v.strip()]
        result = _concurrent(paths, slots, args.max_wait, args.battle_wait,
                             auto=not args.accounts)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("__TTR_PROBE__" + json.dumps(result, ensure_ascii=False), flush=True)
    print("结果已写入 %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
