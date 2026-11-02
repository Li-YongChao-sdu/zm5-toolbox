"""2026 十一许愿：只处理当天三选一免费签到。"""

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from teacher_trial import connect

HERE = Path(__file__).resolve().parent
ROUTE_STATUS = "scene.activityHandler.getNationalDaySignInInfo"
ROUTE_FREE = "scene.activityHandler.nationalDaySignIn"
CHINA_TIME = timezone(timedelta(hours=8))


def today_key():
    return datetime.now(CHINA_TIME).strftime("%Y%m%d")


def choices_for(day):
    with (HERE / "national_day_2026.json").open(encoding="utf-8") as stream:
        return json.load(stream).get(day)


def checked(reply, action):
    if not isinstance(reply, dict) or reply.get("code") != 200 or reply.get("error"):
        detail = (reply.get("error") or reply.get("code")) if isinstance(reply, dict) else reply
        raise RuntimeError("%s失败：%s" % (action, detail))
    return reply


def signed_rewards(status, day):
    days = (status.get("data") or {}).get("day") or {}
    selected = days.get(day) or {}
    if isinstance(selected, dict):
        return {str(reward_id) for reward_id, claimed in selected.items() if claimed}
    return {str(selected)} if selected else set()


def main():
    parser = argparse.ArgumentParser(description="2026十一许愿，当天三选一免费签到")
    parser.add_argument("--choice", type=int, choices=(1, 2, 3),
                        help="选择当天第1、2或3个奖励；不填写时只查看状态")
    args = parser.parse_args()
    day = today_key()
    choices = choices_for(day)
    if not choices:
        print("[十一许愿] 今天不在2026年10月1日至7日免费签到日期内", flush=True)
        return 1
    flow = None
    try:
        with (HERE / "account.local.json").open(encoding="utf-8") as stream:
            account = json.load(stream)
        slot = int(account.get("record_index", 0))
        flow, _ = connect(account, slot)
        before = checked(flow.request(ROUTE_STATUS, {}), "读取签到状态")
        signed = signed_rewards(before, day)
        print("[十一许愿] %s，存档槽 %d" % (day, slot), flush=True)
        for index, option in enumerate(choices, 1):
            print("  %d. %s：%s" % (index, option["title"], option["items"]), flush=True)
        if signed:
            print("[十一许愿] 今天已签到，已选奖励ID：%s" % "、".join(sorted(signed)), flush=True)
            return 0
        print("[十一许愿] 今天尚未签到，可免费三选一", flush=True)
        if args.choice is None:
            return 0
        chosen = choices[args.choice - 1]
        print("[十一许愿] 免费选择：%s（%s）" % (chosen["title"], chosen["items"]), flush=True)
        checked(flow.request(ROUTE_FREE, {"rewardId": chosen["reward_id"]}), "免费签到")
        for _ in range(5):
            after = checked(flow.request(ROUTE_STATUS, {}), "核对签到结果")
            if str(chosen["reward_id"]) in signed_rewards(after, day):
                print("[十一许愿] 免费签到成功，已领取 %s" % chosen["title"], flush=True)
                return 0
            time.sleep(1)
        raise RuntimeError("服务器已响应，但未查到今天所选奖励；请勿重复提交")
    except (OSError, ValueError, RuntimeError) as exc:
        print("[十一许愿] %s" % exc, flush=True)
        return 1
    finally:
        if flow:
            flow.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
