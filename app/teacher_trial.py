# -*- coding: utf-8 -*-
"""双账号师徒试炼。仅使用明确选定的师尊、徒弟账号与存档。"""
import argparse
import json
import math
import threading
import time
from pathlib import Path

from halo_solo import _request
from pypomelo.client import PomeloClient
from pypomelo.flow import GameLoginFlow
from pypomelo.login4399 import fetch_game_token

GATES = ("82.157.236.253", "101.43.232.80", "101.42.229.203",
         "101.43.164.20", "82.157.236.99", "43.143.171.37",
         "82.157.238.37", "43.143.246.102")
DUNGEON = 1200103
LIMITS = {"teacher": 18, "student": 2}
COUNTERS = {"teacher": "teacherChallengeWeekNum", "student": "studentChallengeWeekNum"}
CURRENCIES = {"teacher": "teacherMoney", "student": "studentMoney"}


def checked(reply, action):
    if not isinstance(reply, dict) or reply.get("code") != 200 or reply.get("error"):
        raise RuntimeError("%s失败：%s" % (action, (reply or {}).get("error") if isinstance(reply, dict) else reply))
    return reply


class SlotUnavailableError(ValueError):
    pass


def check_slot_records(records, slot):
    if not isinstance(records,list):raise SlotUnavailableError('无法核实所选槽位状态，未进入存档')
    rows=[row for row in records if isinstance(row,dict) and row.get('index')==slot]
    if len(rows)!=1:raise SlotUnavailableError('所选槽位未找到或记录不唯一，未进入存档')
    status=rows[0].get('status')
    if status==0:raise SlotUnavailableError('所选槽位为空，未创建存档，请选择已有角色的槽位')
    if status==3:raise SlotUnavailableError('所选存档已冻结，未进入存档')
    if status!=1:raise SlotUnavailableError('所选存档状态未知，未进入存档')
    return rows[0]


def connect(account, slot):
    if not 0 <= slot <= 7:
        raise ValueError("存档槽位须为 0～7")
    cookies = account["cookies"]
    for key in ("Pauth", "Uauth", "Xauth", "USESSIONID"):
        if not cookies.get(key):
            raise ValueError("账号 Cookie 缺少 " + key)
    token = fetch_game_token(account["uid"], account["username"], cookies)
    last = None
    for gate in GATES:
        flow = GameLoginFlow(uid=account["uid"], token=token)
        try:
            host, port = flow.query_entry(gate, 3010)
            checked(flow.auth(host, port), "游戏服认证")
            home=checked(flow.request('connector.roleHandler.getUserInfo',{}),'查询存档列表')
            check_slot_records((home.get('user') or {}).get('records'),slot)
            info = enter(flow, slot)
            return flow, info
        except SlotUnavailableError:
            flow.disconnect()
            raise
        except Exception as exc:
            last = exc
            flow.disconnect()
    raise RuntimeError("登录游戏服失败：%s" % last)


def enter(flow, slot):
    reply = checked(flow.request("connector.entryHandler.entry",
                                 {"index": slot, "userAgent": flow.user_agent}), "进入存档")
    info = reply.get("info")
    if not isinstance(info, dict) or not info.get("uid"):
        raise RuntimeError("存档未创建或缺少角色资料")
    return info


def number(info, field):
    try:
        return int(info[field])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("服务器资料缺少 " + field)


def status(info, role):
    weekly = info.get("everyWeekSetting")
    if not isinstance(weekly, dict):
        raise RuntimeError("服务器资料缺少 everyWeekSetting")
    wallet = info
    # 客户端 EveryWeekSetting 将未下发的周次数初始化为 0。
    used = number(weekly, COUNTERS[role]) if COUNTERS[role] in weekly else 0
    money = number(wallet, CURRENCIES[role])
    return used, money


def master_uid(flow):
    reply = checked(flow.request("scene.apprenticeshipHandler.getApprenticeshipData", {}), "读取师徒关系")
    def find(source, depth=0):
        if depth > 6:
            return None
        if isinstance(source, dict):
            for key in ("masterUid", "teacherUid", "master_id", "teacher_id"):
                if source.get(key) is not None:
                    return int(source[key])
            if isinstance(source.get("master"), dict):
                for key in ("uid", "userId", "playerId"):
                    if source["master"].get(key) is not None:
                        return int(source["master"][key])
            for value in source.values():
                found = find(value, depth + 1)
                if found is not None:
                    return found
        elif isinstance(source, list):
            for value in source:
                found = find(value, depth + 1)
                if found is not None:
                    return found
        return None
    found = find(reply)
    if found is not None:
        return found
    raise RuntimeError("无法读取师徒关系")


def push_wait(flow, event):
    ready = threading.Event()
    box = {}
    flow.on(event, lambda data: (box.setdefault("data", data), ready.set()))
    return ready, box


def team_connect(online):
    team = PomeloClient()
    ready = threading.Event()
    team.connect(online["ip"], int(online["port"]), user={}, handshake_cb=lambda _: ready.set())
    if not ready.wait(12):
        team.disconnect()
        raise TimeoutError("战斗服连接超时")
    return team


def seat_info(online, uid):
    seats = [x for x in (online.get("playerInfos") or []) if isinstance(x, dict)]
    for index, row in enumerate(seats):
        if str(row.get("uid") or row.get("playerId")) == str(uid):
            return index, row
    raise RuntimeError("联机房间未包含预期角色")


def battle_exit(online, order, own_uid, frame_num):
    players = []
    for row in order:
        uid = str(row.get("uid") or row.get("playerId"))
        players.append({"playerId": uid, "hp": row.get("hp") or row.get("hpMax") or 1,
                        "from": "gate", "campId": 1, "exit": False,
                        "isme": uid == str(own_uid), "dead": False})
    return {"battleResult": 5, "playerInfo": players, "data": [],
            "frameNum": max(1, frame_num)}


def one_round(master, student, master_uid_value, student_uid, role):
    prepared = []
    created = []
    for flow in (master, student):
        prepared.append(push_wait(flow, "onPrepareCreateOnlineCopy"))
        created.append(push_wait(flow, "onCreateOnlineCopy"))
    room = checked(master.request("room.waitingRoomHandler.createWaitingRoom",
                                  {"dungeonId": DUNGEON, "type": "master", "masterId": master_uid_value}), "创建房间")
    room_id = (room.get("room") or {}).get("roomId") or room.get("roomId")
    if not room_id:
        raise RuntimeError("建房成功但没有房间号")
    submitted = False
    teams = []
    try:
        checked(student.request("room.waitingRoomHandler.joinWaitingRoom",
                                {"roomId": room_id, "masterId": master_uid_value}), "徒弟进房")
        for flow in (master, student):
            checked(flow.request("room.waitingRoomHandler.changePlayerStatus",
                                 {"roomId": room_id, "status": 1, "masterId": master_uid_value}), "准备")
        time.sleep(2)
        checked(master.request("room.waitingRoomHandler.prepareCreateOnlineCopy", {"roomId": room_id}), "开启试炼")
        for event, _ in prepared:
            if not event.wait(20):
                raise TimeoutError("未收到副本准备通知")
        for percent in (5, 50, 100):
            for flow in (master, student):
                flow.game.notify("room.waitingRoomHandler.loadingProgress",
                                 {"roomId": room_id, "percent": percent, "version": 1})
        for event, _ in created:
            if not event.wait(20):
                raise TimeoutError("未收到战斗实例")
        online = [box["data"] for _, box in created]
        for key in ("ip", "port", "instId", "password"):
            if online[0].get(key) != online[1].get(key) or online[0].get(key) is None:
                raise RuntimeError("两端战斗实例不一致：" + key)
        uid_values = (str(master.uid), str(student_uid))
        seats = [seat_info(online[i], uid_values[i]) for i in range(2)]
        if seats[0][0] == seats[1][0]:
            raise RuntimeError("师徒角色座位冲突")
        rows = [row for row in (online[0].get("playerInfos") or []) if isinstance(row, dict)]
        if {str(row.get("uid") or row.get("playerId")) for row in rows} != set(uid_values):
            raise RuntimeError("战斗实例角色与所选账号不符")
        teams = [team_connect(online[i]) for i in range(2)]
        all_loaded = [threading.Event(), threading.Event()]
        frames = [threading.Event(), threading.Event()]
        counts = [0, 0]
        for i, team in enumerate(teams):
            team.on("onAllLoadComplete", lambda _data, index=i: all_loaded[index].set())
            def frame(_data, index=i):
                counts[index] += 1
                frames[index].set()
            team.on("onSendFrame", frame)
        per_frame = []
        for i, team in enumerate(teams):
            reply = checked(_request(team, "copy.copyHandler.enter", {
                "instId": online[i]["instId"], "playerId": uid_values[i],
                "password": online[i]["password"], "abnormalFrameNum": 0,
                "cg": seats[i][1].get("cg") or online[i].get("cg") or "cg1"}), "进入战斗")
            per_frame.append(int(reply.get("sendKeyFrameNum") or 1))
        for team in teams:
            team.notify("copy.copyHandler.loadComplete", {})
        if not all(event.wait(30) for event in all_loaded):
            raise TimeoutError("战斗加载未完成")
        for i, team in enumerate(teams):
            team.notify("copy.copyHandler.keyOperation", {"keys": [84], "objs": [
                {"ready": True, "uid": seats[i][0], "teamPs": seats[i][0]}]})
        if not all(event.wait(20) for event in frames):
            raise TimeoutError("战斗未开始，未提交结算")
        time.sleep(2)
        targets = (0, 1) if role == "student" else (0,)
        for i in targets:
            checked(_request(teams[i], "copy.copyHandler.battleExit",
                             battle_exit(online[i], rows, uid_values[i], counts[i] * per_frame[i])), "战斗结算")
            submitted = True
        time.sleep(1)
    except Exception as exc:
        if submitted:
            raise RuntimeError("结算已提交，结果待核对：%s" % exc) from exc
        raise
    finally:
        for team in teams:
            team.disconnect()
        if not submitted:
            try:
                master.request("room.waitingRoomHandler.exitWaitingRoom", {"roomId": room_id})
            except Exception:
                pass


def run(master_account, master_slot, student_account, student_slot, role, requested, interval=10):
    if not math.isfinite(interval) or interval < 0:
        raise ValueError("建房间隔须为大于或等于0的有限秒数")
    if str(master_account["uid"]) == str(student_account["uid"]):
        raise ValueError("师尊和徒弟必须使用两个不同的登录账号")
    master, student = None, None
    attempted = 0
    succeeded = 0
    initial_money = None
    confirmed_money = None
    anomalies = []
    used = None
    maximum = LIMITS[role]
    try:
        master, master_info = connect(master_account, master_slot)
        student, student_info = connect(student_account, student_slot)
        master_id = int(master_account["uid"])
        if master_uid(student) != master_id:
            raise RuntimeError("所选徒弟与师尊没有对应的师徒关系")
        owner, owner_slot = (master, master_slot) if role == "teacher" else (student, student_slot)
        used, money = status(master_info if role == "teacher" else student_info, role)
        initial_money = confirmed_money = money
        maximum = LIMITS[role]
        print("%s奖励：本周已用 %d/%d，当前券 %d" % ("师尊" if role == "teacher" else "徒弟", used, maximum, money), flush=True)
        if used >= maximum:
            print("本周次数已满，无需开房", flush=True)
            return
        rounds = min(requested, maximum - used)
        for index in range(rounds):
            print("开始第 %d/%d 次" % (index + 1, rounds), flush=True)
            attempted += 1
            before_used, before_money = used, money
            try:
                one_round(master, student, master_id, student.uid, role)
                reward_data = checked(owner.request("scene.copyHandler.getMasterCopyRewardData", {}), "查询待领奖励")
                if isinstance(reward_data.get("give"), list):
                    checked(owner.request("scene.copyHandler.getMasterCopyReward", {}), "领取奖励")
                fresh = enter(owner, owner_slot)
                new_used, new_money = status(fresh, role)
                if new_used != used + 1 or new_money <= money:
                    raise RuntimeError("奖励核对异常：次数 %d→%d，券 %d→%d；奖励回复 %s" %
                                       (used, new_used, money, new_money, reward_data))
                if not isinstance(reward_data.get("give"), list):
                    print("无需再次领奖：服务器资料确认本次券已到账", flush=True)
                used, money = new_used, new_money
                succeeded += 1
                confirmed_money = money
                print("完成：本周 %d/%d，券 %d" % (used, maximum, money), flush=True)
            except Exception as exc:
                detail = "第%d次：%s" % (index + 1, exc)
                anomalies.append(detail)
                print("[本次异常，记入汇总] " + detail, flush=True)
                # 只同步服务器现状；不重复领取，不在本场自动补刷。
                try:
                    used, money = status(enter(owner, owner_slot), role)
                    confirmed_money = money
                    print("[异常后核对] 次数 %d→%d，券 %d→%d" %
                          (before_used, used, before_money, money), flush=True)
                except Exception as sync_exc:
                    raise RuntimeError("无法读取最新奖励状态，不能继续核对后续场次：%s" % sync_exc) from sync_exc
            if index + 1 < rounds:
                print("等待 %g 秒后执行下一次（本场不自动重刷）" % interval, flush=True)
                time.sleep(interval)
        print("既定批次执行结束：本周 %d/%d，券 %d" % (used, maximum, money), flush=True)
    except Exception as exc:
        label = "第 %d 次失败（未确认奖励到账）" % attempted if attempted > succeeded else "执行中断"
        print("[%s] %s" % (label, exc), flush=True)
        raise
    finally:
        print("[师徒汇总] 本次选择 %d 次，已尝试 %d 次，成功 %d 次，失败（未确认成功）%d 次，未执行 %d 次" %
              (requested, attempted, succeeded, attempted - succeeded, requested - attempted), flush=True)
        if initial_money is not None:
            print("[师徒汇总] 已确认券余额 %d→%d，本次增加 %d" %
                  (initial_money, confirmed_money, confirmed_money - initial_money), flush=True)
        if anomalies:
            print("[师徒异常明细]", flush=True)
            for detail in anomalies:
                print("  " + detail, flush=True)
        if used is not None:
            retry = min(len(anomalies), max(0, maximum - used))
            print("[补刷建议] 本批异常 %d 次，建议补刷 %d 次（按当前本周剩余奖励次数计算）；不自动补刷" %
                  (len(anomalies), retry), flush=True)
            if anomalies:
                print("[补刷建议] 若持续提示未击败Boss或已达上限，请先确认副本结算与领奖条件；重复执行不保证获得奖励", flush=True)
        if student:
            student.disconnect()
        if master:
            master.disconnect()


def main():
    parser = argparse.ArgumentParser(description="师徒试炼双账号奖励")
    parser.add_argument("--master-account", required=True, type=Path)
    parser.add_argument("--master-slot", required=True, type=int)
    parser.add_argument("--student-account", required=True, type=Path)
    parser.add_argument("--student-slot", required=True, type=int)
    parser.add_argument("--role", required=True, choices=LIMITS)
    parser.add_argument("--times", required=True, type=int)
    parser.add_argument("--interval", type=float, default=10, help="每场完成后的建房等待秒数，默认10")
    args = parser.parse_args()
    if not 1 <= args.times <= LIMITS[args.role]:
        parser.error("次数超出所选奖励的每周上限")
    if not math.isfinite(args.interval) or args.interval < 0:
        parser.error("建房间隔须为大于或等于0的有限秒数")
    accounts_dir = (Path(__file__).resolve().parent / "accounts").resolve()
    def load(path):
        resolved = path.resolve()
        if resolved.parent != accounts_dir:
            raise ValueError("账号文件必须在工具箱 accounts 目录")
        with resolved.open(encoding="utf-8") as stream:
            return json.load(stream)
    run(load(args.master_account), args.master_slot,
        load(args.student_account), args.student_slot, args.role, args.times, args.interval)


if __name__ == "__main__":
    main()
