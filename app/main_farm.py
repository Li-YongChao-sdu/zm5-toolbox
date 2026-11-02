"""Main-story farming from the toolbox's dedicated 一键刷图 page."""

import argparse
import json
import random
import threading
import time
from collections import Counter
from pathlib import Path

import daily_auto as da
from pypomelo.flow import GameLoginFlow
from pypomelo.login4399 import fetch_game_token


HERE = Path(__file__).parent
ROUTES = json.loads((HERE / "main_boss_routes.json").read_text(encoding="utf-8"))
STAGES = {int(row["mid"]): row["name"] for row in
          json.loads((HERE / "main_custom_stages.json").read_text(encoding="utf-8"))}
DUNGEON = json.loads((HERE / "cg_config_out_cg1_20261019_1" / "Dungeon.json").read_text(encoding="utf-8"))


def _response(flow, route, payload):
    result = flow.request(route, payload)
    if not isinstance(result, dict) or result.get("error") or result.get("code") != 200:
        error = result.get("error") if isinstance(result, dict) else str(result)
        raise RuntimeError("%s: %s" % (route, error or result))
    return result


def _connect():
    token = fetch_game_token(da.UID, da.USERNAME, da.COOKIES)
    last_error = None
    for ip in da.GATE_IPS:
        flow = GameLoginFlow(uid=da.UID, token=token)
        try:
            host, port = flow.query_entry(ip, da.PORT)
            auth = flow.auth(host, port)
            if not isinstance(auth, dict) or auth.get("error") or auth.get("code") != 200:
                raise RuntimeError("账号验证失败: %s" % auth)
            return flow
        except Exception as exc:
            last_error = exc
            flow.disconnect()
    raise RuntimeError("无法连接游戏服: %s" % last_error)


def _slot_status(flow):
    result = _response(flow, "connector.roleHandler.getUserInfo", {})
    rows = (result.get("user") or result).get("records") or []
    return next((row for row in rows if row.get("index") == da.RECORD_INDEX), None)


def _entry(flow):
    result = _response(flow, "connector.entryHandler.entry", {
        "index": da.RECORD_INDEX, "userAgent": flow.user_agent})
    info = result.get("info")
    if not isinstance(info, dict):
        raise RuntimeError("服务器没有返回存档数据")
    return info


def _stage(info, mid):
    return (info.get("dungeon") or {}).get(str(mid)) or {}


def _create(flow, mid):
    client_rnd = random.randint(0, 9999)
    result = _response(flow, "scene.copyHandler.createSinglePlayerCopy", {
        "mid": mid, "rnd": client_rnd})
    if result.get("rnd") is None:
        raise RuntimeError("副本 %s 未返回结算随机数" % mid)
    return client_rnd, result


def _pickup_all(flow, created, client_rnd, loot="all", pickup_supplies=True):
    drops = created.get("drops") or []
    gained = Counter()
    skipped = Counter()
    server_rnd = int(created["rnd"])
    from supply_filter import before
    jobs = []
    for ordinal, drop in enumerate(drops):
        if not isinstance(drop, dict):
            raise RuntimeError("掉落数据格式错误")
        # 原客户端对经验仅本地显示；其余掉落通过 syncDropInfo 入包。
        if drop.get("type") == "exp":
            continue
        if not pickup_supplies and drop.get("type") == "item" and str(drop.get("subType")) in (
                "101014001", "101014002", "101014003", "101014004"):
            continue
        if loot == "spiritPet" and not (
                (drop.get("type") == "coin" and drop.get("subType") == "spirit")
                or (drop.get("type") == "petAttr" and drop.get("subType") == "petEXP")):
            continue
        if loot == "currency" and not (
            (drop.get("type") == "coin" and drop.get("subType") in ("exp", "spirit"))
            or (drop.get("type") == "petAttr" and drop.get("subType") == "petEXP")
        ):
            continue
        drop_index = int(drop.get("dropIndex", ordinal))
        salt = random.randint(1, 10000)
        data = {"index": (drop_index + salt) ^ (server_rnd ^ client_rnd),
                "key": salt ^ client_rnd}
        if before(flow, "scene.copyHandler.syncDropInfo", data) is not None:
            continue
        jobs.append((drop_index, data, (str(drop.get("type")), str(drop.get("subType")))))
    # 流水线拾取：官方客户端逐条排队，服务端实测可并发处理同一副本的多个请求。
    replies = {}
    lock = threading.Lock()
    for start in range(0, len(jobs), 50):
        chunk = jobs[start:start + 50]
        state = {"left": len(chunk)}
        ready = threading.Event()

        def callback(body, key, state=state, ready=ready):
            replies[key] = body
            with lock:
                state["left"] -= 1
                if state["left"] == 0:
                    ready.set()

        for offset, (_, data, _) in enumerate(chunk):
            flow.game.request("scene.copyHandler.syncDropInfo", data,
                              lambda body, key=start + offset: callback(body, key))
        if not ready.wait(15):
            raise TimeoutError("掉落拾取回包超时")
    for key, (drop_index, _, kind) in enumerate(jobs):
        result = replies.get(key)
        if not isinstance(result, dict) or result.get("error") or result.get("code") != 200:
            error = result.get("error") if isinstance(result, dict) else str(result)
            if error and "背包空间不足" in str(error):
                skipped[kind] += 1
                continue
            raise RuntimeError("掉落拾取失败 (%s): %s" % (drop_index, error or result))
        for item in result.get("give") or []:
            if isinstance(item, dict) and item.get("type") in ("item", "equipment", "coin", "petAttr"):
                gained[(item.get("type"), str(item.get("subType")))] += int(item.get("count") or 0)
    return len(drops), gained, skipped


def _finish(flow, created, client_rnd, win):
    return _response(flow, "scene.copyHandler.finishSingleCopy", {
        "win": int(win), "rnd": int(created["rnd"]) ^ client_rnd,
        "star": 3 if win else 0})


def _target(mid, loot):
    if loot in ("small", "currency", "spiritPet"):
        return None
    route = ROUTES.get(str(mid)) or {}
    key = "hidden" if loot == "hidden" else "normal"
    if key not in route:
        label = "隐藏饰品 Boss" if key == "hidden" else "普通 Boss"
        raise ValueError("%s 没有配置%s房间" % (STAGES[mid], label))
    value = route[key]
    return [int(x) for x in (value if isinstance(value, list) else [value])]


def run(mid, times, progress, loot, base_seconds, boss_seconds, round_seconds, pickup_supplies=True):
    if mid not in STAGES:
        raise ValueError("无效主线关卡: %s" % mid)
    if not 1 <= times <= 20:
        raise ValueError("每批次数须为 1–20")
    if progress not in ("increase", "keep") or loot not in ("small", "boss", "hidden", "currency", "spiritPet"):
        raise ValueError("无效模式")
    if min(base_seconds, boss_seconds, round_seconds) < 0:
        raise ValueError("等待时间不能为负数")
    target = _target(mid, loot)
    pick_mode = loot if loot in ("currency", "spiritPet") else "all"
    flow = _connect()
    try:
        slot = _slot_status(flow)
        if not slot or slot.get("status") != 1:
            raise RuntimeError("所选存档槽不可用或已被限制")
        info = _entry(flow)
        if mid == 64 and progress == "increase" and not int(_stage(info, 64).get("passNum") or 0):
            raise RuntimeError("穹顶宫首次通关曾在测试槽触发封禁，已阻止自动首次通关")
        if mid > 1 and not int(_stage(info, mid - 1).get("passNum") or 0):
            raise RuntimeError("前一主线关尚未通关，当前关卡未确认解锁")
        print("[一键刷图] 槽%d · %s(%d) · %d次 · %s · %s" %
              (da.RECORD_INDEX, STAGES[mid], mid, times,
               "通关计数增加" if progress == "increase" else "失败结算不增加",
               {"small": "小材料", "boss": "小材料+普通Boss",
                "hidden": "小材料+隐藏Boss", "currency": "角色/宠物经验和灵魂",
                "spiritPet": "灵魂+宠物经验"}[loot]), flush=True)
        for attempt in range(1, times + 1):
            before = int(_stage(info, mid).get("passNum") or 0)
            info_before_spirit = info.get("spirit")
            info_before_exp = (info.get("p1") or {}).get("exp")
            base_rnd, base = _create(flow, mid)
            active = (base, base_rnd)
            try:
                base_count, base_give, base_skipped = _pickup_all(flow, base, base_rnd,
                                                                  pick_mode,
                                                                  pickup_supplies=pickup_supplies)
                time.sleep(base_seconds)
                boss_count, boss_give, boss_skipped = 0, Counter(), Counter()
                for room in target or []:
                    boss_rnd, boss = _create(flow, room)
                    active = (boss, boss_rnd)
                    cnt, give, skipped = _pickup_all(flow, boss, boss_rnd,
                                                     pickup_supplies=pickup_supplies)
                    boss_count += cnt
                    boss_give += give
                    boss_skipped += skipped
                    time.sleep(boss_seconds)
                _finish(flow, *active, win=(progress == "increase"))
                active = None
            except Exception:
                if active is not None:
                    try:
                        _finish(flow, *active, win=False)
                    except Exception as cleanup_error:
                        print("[一键刷图] 关闭当前副本失败：%s" % cleanup_error, flush=True)
                raise
            info = _entry(flow)
            after = int(_stage(info, mid).get("passNum") or 0)
            if progress == "increase" and after <= before:
                last_room = target[-1] if target else mid
                settles = int((DUNGEON.get(str(last_room)) or {}).get("finishBId") or 0)
                if settles:
                    raise RuntimeError("第%d次结算后通关次数未增加 (%d→%d)" % (attempt, before, after))
                print("[一键刷图] %s 的 finishBId=0，官方也不记主线通关，本次仅结算掉落" % last_room, flush=True)
            if progress == "keep" and after != before:
                raise RuntimeError("第%d次失败结算后通关次数意外变化 (%d→%d)" % (attempt, before, after))
            gained = base_give + boss_give
            items = ", ".join("%s:%s×%d" % (kind, sub, amount)
                              for (kind, sub), amount in sorted(gained.items())) or "无道具"
            if loot in ("currency", "spiritPet"):
                print("[一键刷图] 实际灵魂 %s→%s；经验 %s→%s" %
                      (info_before_spirit, info.get("spirit"), info_before_exp,
                       (info.get("p1") or {}).get("exp")), flush=True)
            print("[一键刷图] %d/%d 完成：地面掉落%d件，Boss房%d件；passNum %d→%d；领取 %s" %
                  (attempt, times, base_count, boss_count, before, after, items), flush=True)
            skipped = base_skipped + boss_skipped
            if skipped:
                print("[一键刷图] 背包空间不足，%d件掉落未入包：%s" %
                      (sum(skipped.values()), ", ".join("%s:%s×%d" % (kind, sub, amount)
                          for (kind, sub), amount in sorted(skipped.items()))), flush=True)
            if attempt % 5 == 0:
                status = _slot_status(flow)
                if not status or status.get("status") != 1:
                    raise RuntimeError("服务器显示存档状态异常，已停止")
            if attempt < times:
                time.sleep(round_seconds)
        print("[一键刷图] 本批完成", flush=True)
    finally:
        flow.disconnect()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mid", type=int, required=True)
    parser.add_argument("--times", type=int, default=1)
    parser.add_argument("--progress", choices=("increase", "keep"), default="keep")
    parser.add_argument("--loot", choices=("small", "boss", "hidden", "currency", "spiritPet"), default="small")
    parser.add_argument("--base-seconds", type=float, default=40)
    parser.add_argument("--boss-seconds", type=float, default=10)
    parser.add_argument("--round-seconds", type=float, default=5)
    parser.add_argument("--skip-supplies", action="store_true", help="不领取萝卜、蟠桃、蓝瓶、蓝壶")
    args = parser.parse_args()
    run(args.mid, args.times, args.progress, args.loot,
        args.base_seconds, args.boss_seconds, args.round_seconds, not args.skip_supplies)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[一键刷图] 已停止：%s" % exc, flush=True)
        raise SystemExit(1)
