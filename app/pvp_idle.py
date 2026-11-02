"""斗神大会：真人场挂机，机器人场立即结算胜利。"""

import argparse
import json
import queue
import time
from pathlib import Path

from halo_solo import _request
from teacher_trial import connect, enter, seat_info, team_connect

TASK_ID = 990013
TARGET = 3
EVENTS = ("onPVPMatchResult", "onPlayerJoinWaitingRoom", "onPrepareCreateOnlineCopy",
          "onCreateOnlineCopy", "onCreateOnlineCopyError", "onPlayerLeaveWaitingRoom",
          "onPVPFinish", "kicked")


def _message(body):
    if not isinstance(body, dict):
        return {}
    value = body.get("message")
    return value if isinstance(value, dict) else body


def _task_progress(info):
    for task in info.get("quest") or []:
        if str(task.get("id")) == str(TASK_ID):
            if int(task.get("status") or 0) == 3:
                return TARGET
            return min(TARGET, int((task.get("progress") or {}).get("0") or 0))
    # 每日任务领取后可能不再出现在 quest 中，不影响继续匹配。
    return None


def _match_count(info):
    season = info.get("pvpSeason") or {}
    played = season.get("pvpNum") or []
    reported = int(played[0] or 0) if isinstance(played, list) and played else 0
    settled = int(season.get("win") or 0) + int(season.get("fail") or 0)
    return max(reported, settled)


def _checked(reply, action):
    if not isinstance(reply, dict) or reply.get("code") != 200 or reply.get("error"):
        raise RuntimeError("%s失败：%s" % (action, reply.get("error") or reply.get("code")
                                      if isinstance(reply, dict) else reply))
    return reply


def _confirm_match(flow, slot, before):
    for _ in range(5):
        count = _match_count(enter(flow, slot))
        if count > before:
            print("[斗神大会] 已结算场次 %d → %d" % (before, count), flush=True)
            return True
        time.sleep(2)
    print("[斗神大会] 结算场次未增加，停止连续匹配", flush=True)
    return False


def _one_match(flow, events, slot, before, match_seconds, battle_seconds):
    reply = _checked(flow.request("scene.pvpHandler.matchStart", {}), "斗神匹配")
    if reply.get("robot"):
        robot = reply["robot"]
        if not isinstance(robot, dict) or not robot.get("name") or not robot.get("entityId"):
            raise RuntimeError("机器人匹配缺少对手资料")
        print("[斗神大会] 匹配到机器人，立即提交胜利结算", flush=True)
        result = _checked(flow.request("scene.pvpHandler.robotPVPFinish", {
            "win": 1, "name": robot["name"], "entityId": robot["entityId"]}), "机器人战斗结算")
        if int((result.get("data") or {}).get("winType") or 0) != 1:
            raise RuntimeError("机器人结算未确认胜利，停止连续匹配")
        return _confirm_match(flow, slot, before)
    print("[斗神大会] 已发起匹配", flush=True)
    room_id = None
    team = None
    matched = False
    next_ping = 0.0
    match_deadline = time.monotonic() + match_seconds
    battle_deadline = None
    try:
        while True:
            now = time.monotonic()
            deadline = battle_deadline or match_deadline
            if now >= deadline:
                print("[斗神大会] %s超时，本场停止" % ("挂机" if matched else "匹配"), flush=True)
                return False
            if room_id and team is None and now >= next_ping:
                flow.request("room.waitingRoomHandler.ping", {
                    "roomId": str(room_id), "code": 200,
                    "time": int(time.time() * 1000)})
                next_ping = time.monotonic() + 5
            try:
                route, body = events.get(timeout=min(2, max(.1, deadline - now)))
            except queue.Empty:
                continue
            data = _message(body)
            if route == "kicked":
                raise RuntimeError("游戏服断开连接")
            if route == "onPVPMatchResult":
                if data.get("code") != 200:
                    raise RuntimeError("匹配失败：%s" % (data.get("error") or data.get("code")))
                matched = True
                battle_deadline = time.monotonic() + battle_seconds
                print("[斗神大会] 已匹配到对手", flush=True)
            elif route == "onPlayerJoinWaitingRoom":
                room_id = data.get("roomId") or (data.get("room") or {}).get("roomId") or room_id
            elif route == "onPrepareCreateOnlineCopy":
                room_id = data.get("roomId") or room_id
                if not room_id:
                    raise RuntimeError("缺少等待房间号")
                matched = True
                battle_deadline = time.monotonic() + battle_seconds
                flow.game.notify("room.waitingRoomHandler.loadingProgress", {
                    "roomId": room_id, "percent": 100, "version": 1})
                print("[斗神大会] 已上报加载完成", flush=True)
            elif route == "onCreateOnlineCopy":
                if team is not None:
                    continue
                for key in ("ip", "port", "instId"):
                    if not data.get(key):
                        raise RuntimeError("战斗实例缺少 " + key)
                if 'password' not in data or data['password'] is None:
                    raise RuntimeError('战斗实例缺少 password')
                team = team_connect(data)
                _, player = seat_info(data, flow.uid)
                _checked(_request(team, "copy.copyHandler.enter", {
                    "instId": data["instId"], "playerId": str(flow.uid),
                    "password": data["password"], "abnormalFrameNum": 0,
                    "cg": player.get("cg") or data.get("cg") or "cg1"}), "进入战斗服")
                team.notify("copy.copyHandler.loadComplete", {})
                print("[斗神大会] 已进入战斗服，开始挂机", flush=True)
            elif route == "onCreateOnlineCopyError":
                raise RuntimeError("创建战斗实例失败：%s" % (data.get("error") or data))
            elif route == "onPlayerLeaveWaitingRoom":
                print("[斗神大会] 对手离开等待房间，继续等待服务器结算", flush=True)
            elif route == "onPVPFinish":
                print("[斗神大会] 收到服务器结算", flush=True)
                return _confirm_match(flow, slot, before)
    finally:
        if team:
            team.disconnect()
        if not matched:
            try:
                flow.request("scene.pvpHandler.matchCancel", {})
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="斗神大会匹配，默认3场")
    parser.add_argument("--matches", type=int, default=3)
    parser.add_argument("--match-seconds", type=int, default=90)
    parser.add_argument("--battle-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.matches < 1:
        parser.error("匹配场数须为正整数")
    if args.match_seconds < 10 or not 60 <= args.battle_seconds <= 600:
        parser.error("匹配至少等待10秒，单场挂机时间须为60～600秒")
    flow = None
    try:
        with (Path(__file__).resolve().parent / "account.local.json").open(encoding="utf-8") as stream:
            account = json.load(stream)
        slot = int(account.get("record_index", 0))
        flow, info = connect(account, slot)
        events = queue.Queue()
        for route in EVENTS:
            flow.on(route, lambda body, name=route: events.put((name, body)))
        progress = _task_progress(info)
        print("[斗神大会] 存档槽 %d，今日任务 %s，本次计划 %d 场" %
              (slot, "%d/%d" % (progress, TARGET) if progress is not None else "未显示",
               args.matches), flush=True)
        for number in range(args.matches):
            while not events.empty():
                events.get_nowait()
            print("[斗神大会] 第 %d/%d 场" % (number + 1, args.matches), flush=True)
            if not _one_match(flow, events, slot, _match_count(info),
                              args.match_seconds, args.battle_seconds):
                break
            info = enter(flow, slot)
            if number + 1 < args.matches:
                time.sleep(3)
    except (OSError, ValueError, RuntimeError) as exc:
        print("[斗神大会] %s" % exc, flush=True)
        return 1
    finally:
        if flow:
            flow.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
