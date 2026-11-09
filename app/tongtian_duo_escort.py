"""通天河双账号护航：按战力自动让高战力发船、低战力被雇，确保雇佣免费。"""
import argparse
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_account(name):
    path = HERE / "accounts" / (name[:-5] if name.endswith(".json") else name + ".json")
    if not path.exists():
        raise ValueError("找不到账号文件：%s" % path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def hire_cost(hired_power, own_power):
    """按客户端 getHireConsumeId 的档位返回个人贡献消耗；0 表示免费。"""
    diff = float(hired_power) - float(own_power)
    if diff < 100000:
        return 0
    for threshold, cost in ((200000, 1), (300000, 2), (400000, 3), (50000000, 4)):
        if diff < threshold:
            return cost
    return 5


def find_hire(flow, uid, attempts=6):
    """从报名列表里找目标，返回（原始 hire 串，解析后的字典）。"""
    for index in range(attempts):
        reply = flow.request("scene.tongtianHandler.getHiredList", {})
        rows = (reply or {}).get("list") or []
        for row in rows:
            try:
                data = json.loads(row) if isinstance(row, str) else row
            except (TypeError, ValueError):
                continue
            if str(data.get("uid")) == str(uid):
                raw = row if isinstance(row, str) else json.dumps(data, ensure_ascii=False)
                return raw, data
        if index + 1 < attempts:
            time.sleep(2)
    return None, None


def run(names, slots, apply=False):
    if len(names) != 2:
        raise ValueError("需要两个账号")
    if names[0] == names[1]:
        raise ValueError("两个账号不能相同")
    accounts = [load_account(name) for name in names]
    if slots is None:
        slots = [int(acc.get("record_index") or 0) for acc in accounts]

    from teacher_trial import connect, enter
    flows = []
    infos = []
    try:
        for account, slot in zip(accounts, slots):
            flow, info = connect(account, slot)
            flows.append(flow)
            infos.append(info)
            player = info.get("p1") or {}
            print("[护航] %s 槽%d：%s Lv%s 战力%s" %
                  (account.get("username") or account.get("uid"), slot,
                   player.get("name") or "-", player.get("level"), player.get("fightPower")), flush=True)

        players = [info.get("p1") or {} for info in infos]
        powers = [int(player.get("fightPower") or 0) for player in players]
        if min(powers) <= 0:
            raise ValueError("未读取到双方战力")
        employer_index = 0 if powers[0] >= powers[1] else 1
        helper_index = 1 - employer_index
        employer = accounts[employer_index]
        helper = accounts[helper_index]
        employer_info = infos[employer_index]
        helper_info = infos[helper_index]
        employer_slot, helper_slot = slots[employer_index], slots[helper_index]

        employer_player = players[employer_index]
        helper_player = players[helper_index]
        diff = int(helper_player["fightPower"]) - int(employer_player["fightPower"])
        print("[护航] 自动选择：%s 发船，%s 被雇佣（战力差 %+d，雇佣免费）" %
              (employer.get("username") or employer.get("uid"),
               helper.get("username") or helper.get("uid"), diff), flush=True)

        if int(hire_cost(helper_player["fightPower"], employer_player["fightPower"])) > 0:
            raise ValueError("按战力计算会产生个人贡献消耗，已中止")

        daily = employer_info.get("everyDaySetting") or {}
        if int(daily.get("tongtianRiverEscortNum") or 0) >= 3:
            raise ValueError("发船账号今日护送次数已用完")
        if (employer_info.get("tongtianRiver") or {}).get("escortData"):
            raise ValueError("发船账号已有正在护送或待领取的船，请先领奖")

        helper_daily = helper_info.get("everyDaySetting") or {}
        applied = int(helper_daily.get("tongtianHireApply") or 0)
        print("[护航] 被雇账号报名状态：%s" % ("已报名" if applied else "未报名"), flush=True)
        if not applied:
            if not apply:
                print("[护航] 预演：需要先报名；加 --apply 后才会提交 hireApply", flush=True)
                return
            reply = flows[helper_index].request("scene.tongtianHandler.hireApply", {})
            reply = reply if isinstance(reply, dict) else {}
            print("[护航] 报名 code=%r error=%r" % (reply.get("code"), reply.get("error")), flush=True)
            if reply.get("code") != 200 or reply.get("error"):
                raise ValueError("被雇账号报名失败：%s" % (reply.get("error") or reply.get("message") or "未知原因"))
            time.sleep(1)

        raw, hire = find_hire(flows[employer_index], helper.get("uid") or helper_player.get("uid"))
        if not raw:
            raise ValueError("报名列表里暂时找不到被雇账号，未发船")
        cost = hire_cost(hire.get("fightPower") or 0, employer_player["fightPower"])
        if cost > 0:
            raise ValueError("雇佣串战力差会扣个人贡献×%d，已中止" % cost)
        print("[护航] 已找到雇佣串：%s（战力%s，预计免费）" % (hire.get("name"), hire.get("fightPower")), flush=True)

        if not apply:
            print("[护航] 预演完成：校验通过，未发船（加 --apply 才执行）", flush=True)
            return
        result = flows[employer_index].request("scene.tongtianHandler.escort", {"hire": raw})
        result = result if isinstance(result, dict) else {"error": str(result)}
        print("[护航] escort code=%r error=%r" % (result.get("code"), result.get("error")), flush=True)
        if result.get("code") != 200 or result.get("error"):
            raise ValueError("发船失败：%s" % (result.get("error") or result.get("message") or "未知原因"))
        data = result.get("escortData") or {}
        print("[护航] 发船成功：雇佣 %s（uid=%s），船 %s，护送 %s 秒" %
              (data.get("hireName") or hire.get("name"), data.get("hireUid") or hire.get("uid"),
               data.get("goodId"), data.get("escortTime")), flush=True)
    finally:
        for flow in flows:
            try:
                flow.disconnect()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounts", required=True, help="两个账号名，逗号分隔")
    parser.add_argument("--slots", default="", help="两个存档槽位，如 0,3；省略用账号文件 record_index")
    parser.add_argument("--apply", action="store_true", help="实际报名并发船；省略时只预演")
    args = parser.parse_args()
    names = [x.strip() for x in args.accounts.split(",") if x.strip()]
    slots = None
    if args.slots:
        try:
            slots = [int(x) for x in args.slots.split(",")]
        except ValueError:
            raise SystemExit("存档槽位必须是整数")
        if len(slots) != len(names):
            raise SystemExit("--slots 个数必须与 --accounts 一致")
        if any(not 0 <= slot <= 7 for slot in slots):
            raise SystemExit("存档槽位须为 0～7")
    try:
        run(names, slots, apply=args.apply)
    except Exception as exc:
        print("[护航] 中止：%s" % exc, flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
