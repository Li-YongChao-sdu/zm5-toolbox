"""通天河：检测当前存档战力并报名雇佣（只报名，不发船、不护航）。"""
import argparse
import json


def run(slot=None, apply=False):
    import daily_auto
    if slot is None:
        slot = daily_auto.RECORD_INDEX
    flow, info = daily_auto.login(record_index=slot)
    try:
        player = info.get("p1") or {}
        eds = info.get("everyDaySetting") or {}
        level = player.get("level")
        power = player.get("fightPower")
        print("[通天河报名] 存档槽%s 角色%s Lv%s 战力%s" %
              (slot, player.get("name") or "-", level, power), flush=True)
        if level is None or power is None:
            raise RuntimeError("未读取到角色等级或战力")
        level = int(level)
        if level < 40:
            print("[通天河报名] 角色等级低于40级，通天河未开放", flush=True)
            return
        applied = int(eds.get("tongtianHireApply") or 0)
        print("[通天河报名] 今日报名标记：%s" % ("已报名" if applied else "未报名"), flush=True)
        if applied:
            print("[通天河报名] 今日已报名，跳过重复提交", flush=True)
            return
        if not apply:
            print("[通天河报名] 仅检测战力，未提交报名（需要加 --apply）", flush=True)
            return
        reply = flow.request("scene.tongtianHandler.hireApply", {})
        reply = reply if isinstance(reply, dict) else {"error": str(reply)}
        print("[通天河报名] hireApply code=%r error=%r" %
              (reply.get("code"), reply.get("error")), flush=True)
        if reply.get("code") == 200 and not reply.get("error"):
            flag = (reply.get("everyDaySetting") or {}).get("tongtianHireApply")
            print("[通天河报名] 报名成功，tongtianHireApply=%r" % flag, flush=True)
        else:
            detail = str(reply.get("error") or reply.get("message") or "")
            if "暂未开放" in detail:
                print("[通天河报名] 当前不在开放时间（通天河周末 12:00–15:00 开放）", flush=True)
            else:
                print("[通天河报名] 报名未成功：%s" % detail, flush=True)
    finally:
        flow.disconnect()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", type=int, choices=range(8), help="存档槽位 0～7；省略时用账号配置")
    parser.add_argument("--apply", action="store_true", help="实际提交报名；省略时只检测战力")
    args = parser.parse_args()
    try:
        run(slot=args.slot, apply=args.apply)
    except Exception as exc:
        print("[通天河报名] 失败：%s" % exc, flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
