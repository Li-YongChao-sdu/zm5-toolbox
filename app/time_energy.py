"""时光之舟：查看能量与每周额度，按配置兑换副本次数。"""

import argparse
import json
import os


HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "time_energy_catalog.json"), encoding="utf-8") as file:
    CATALOG = {int(key): value for key, value in json.load(file).items()}

ROUTES = {
    0: "scene.activityHandler.copyBuyCountByEnergy",
    1: "scene.activityHandler.buyLandformChallengeCnt",
    2: "scene.activityHandler.buyDemonTowerCnt",
    4: "scene.activityHandler.buyDungeonTreasureCnt",
}


def _weekly_used(info, energy_id):
    records = (info.get("everyWeekSetting") or {}).get("timeEnergy") or {}
    return int(records.get(str(energy_id), records.get(energy_id, 0)) or 0)


def _target(info, config):
    category = int(config["type"])
    if category == 0:
        dungeon = info.get("dungeon") or {}
        for value in config["dungeonId"].split(";"):
            mid = int(value)
            record = dungeon.get(str(mid)) or dungeon.get(mid) or {}
            used = int(record.get("dailyCount") or 0)
            if used > 0:
                return True, "关卡%d已用%d次" % (mid, used), mid
        return False, "该组关卡尚无已用次数", None
    if category == 1:
        used = int((info.get("everyDaySetting") or {}).get("landformChallengeCnt") or 0)
        remaining = max(0, 5 - used)
        return remaining < 5, "剩余%d/5次" % remaining, None
    if category == 2:
        remaining = int((info.get("demonTower") or {}).get("count") or 0)
        return remaining < 5, "剩余%d/5次" % remaining, None
    if category == 4:
        share_id = str(config["dungeonTreasureShareId"])
        remaining = int(((info.get("dungeonTreasure") or {}).get(share_id) or {}).get("remainCnt") or 0)
        return remaining < 2, "剩余%d/2次" % remaining, None
    raise ValueError("未知时光能量兑换类型: %s" % category)


def show_status(info, slot):
    energy = int(info.get("energy") or 0)
    print("[槽%d 时光之舟] 当前时光能量：%d" % (slot, energy), flush=True)
    for config in sorted(CATALOG.values(), key=lambda item: (item["order"], item["id"])):
        energy_id = int(config["id"])
        used = _weekly_used(info, energy_id)
        weekly_max = int(config["weekChangeNum"])
        available, target_state, _ = _target(info, config)
        print("  %2d %-8s 每次%d能量 周剩余%d/%d %s%s" %
              (energy_id, config["name"], int(config["consume_count"]),
               max(0, weekly_max - used), weekly_max, target_state,
               "（当前无须兑换）" if not available else ""), flush=True)


def exchange(flow, info, slot, energy_id, times):
    if energy_id not in CATALOG:
        raise ValueError("没有这个兑换项目")
    if not 1 <= times <= 15:
        raise ValueError("兑换次数须为1～15")
    config = CATALOG[energy_id]
    category = int(config["type"])
    route = ROUTES[category]
    cost = int(config["consume_count"])
    weekly_max = int(config["weekChangeNum"])
    done = 0
    for _ in range(times):
        energy = int(info.get("energy") or 0)
        used = _weekly_used(info, energy_id)
        available, target_state, mid = _target(info, config)
        if energy < cost or used >= weekly_max or not available:
            print("[%s] 停止：能量%d/%d，周剩余%d，%s" %
                  (config["name"], energy, cost, max(0, weekly_max - used), target_state), flush=True)
            break
        payload = {"energyId": energy_id}
        if category == 0:
            payload["dungeonId"] = mid
        result = flow.request(route, payload)
        if not isinstance(result, dict) or result.get("code") != 200 or result.get("error"):
            print("[%s] 兑换失败：%s" % (config["name"], result), flush=True)
            break
        consume = result.get("consume") or []
        if any(item.get("type") != "coin" or item.get("subType") != "energy" for item in consume):
            print("[%s] 回包出现非时光能量消耗，停止后续兑换：%s" % (config["name"], consume), flush=True)
            break
        refreshed = flow.request("connector.entryHandler.entry",
                                 {"index": slot, "userAgent": flow.user_agent})
        info = refreshed.get("info") or {}
        new_energy = int(info.get("energy") or 0)
        new_used = _weekly_used(info, energy_id)
        if new_energy >= energy or new_used <= used:
            print("[%s] 服务器状态未确认本次兑换，停止：能量%d→%d，周已用%d→%d" %
                  (config["name"], energy, new_energy, used, new_used), flush=True)
            break
        done += 1
        print("[%s] 第%d次成功：能量%d→%d，周已用%d→%d" %
              (config["name"], done, energy, new_energy, used, new_used), flush=True)
    print("[%s] 本次成功兑换 %d/%d 次" % (config["name"], done, times), flush=True)

    return info, done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", type=int, choices=range(8), required=True)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--energy-id", type=int, choices=sorted(CATALOG))
    parser.add_argument("--times", type=int, default=1)
    parser.add_argument("--run-after", action="store_true")
    parser.add_argument("--cave-plan", default="")
    args = parser.parse_args()
    import daily_auto
    flow, info = daily_auto.login(record_index=args.slot)
    try:
        if not (info.get("p1") or {}).get("level"):
            print("[槽%d] 没有可用角色，停止" % args.slot, flush=True)
        elif args.status:
            show_status(info, args.slot)
        elif args.energy_id is not None:
            if args.run_after:
                from time_energy_run import run
                run(flow, info, args.slot, args.energy_id, args.times, cave_plan=json.loads(args.cave_plan) if args.cave_plan else None)
            else:
                exchange(flow, info, args.slot, args.energy_id, args.times)
        else:
            parser.error("需要 --status 或 --energy-id")
    finally:
        flow.disconnect()


if __name__ == "__main__":
    main()
