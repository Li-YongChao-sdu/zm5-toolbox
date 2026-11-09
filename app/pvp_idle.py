"""斗神大会：真人场挂机，机器人场立即结算胜利。"""

import argparse
import json
import queue
import threading
import time
from pathlib import Path

from halo_solo import _request
from teacher_trial import connect, enter, seat_info, team_connect

TASK_ID = 990013
TARGET = 3
EVENTS = ("onPVPMatchResult", "onPlayerJoinWaitingRoom", "onPrepareCreateOnlineCopy",
          "onCreateOnlineCopy", "onCreateOnlineCopyError", "onPlayerLeaveWaitingRoom",
          "onPVPFinish", "kicked")


class BattleKeepalive:
    """真人战斗业务保活；回调只记状态，发包在主循环串行完成。"""
    def __init__(self, team, seat, clock=None):
        self.team, self.seat = team, seat
        self.clock = clock or time.monotonic
        self.loaded = threading.Event()
        self.frames = threading.Event()
        self.closed = threading.Event()
        self.active, self.ready = True, False
        self.load_deadline = self.clock() + 30
        self.frame_deadline = self.next_ping = None
        self.closed_at = None
        self.frame_logged = False
        team.on('onAllLoadComplete', lambda _: self.loaded.set())
        team.on('onSendFrame', lambda _: self.frames.set())
        team.set_close_callback(self.closed.set)
        team.set_kicked_callback(self.closed.set)

    def stop(self):
        self.active = False

    def tick(self):
        if not self.active:
            return
        now = self.clock()
        if self.closed.is_set():
            # 战斗服可能先关闭、场景服再推结算，留出一个主循环接收结算。
            if self.closed_at is None:
                self.closed_at = now
            if now - self.closed_at >= 2:
                raise RuntimeError('战斗服连接已断开，停止本场，不自动重新匹配')
            return
        if not self.loaded.is_set():
            if now >= self.load_deadline:
                raise RuntimeError('未收到全员加载完成通知，不冒发战斗准备信号')
            return
        if not self.ready:
            # 原版 BattleMapBase.onAllLoadComplete：Id/teamPs是房内座位，不是账号UID。
            self.team.notify('copy.copyHandler.keyOperation', {'keys': [84], 'objs': [
                {'ready': True, 'uid': self.seat, 'teamPs': self.seat}]})
            self.ready = True
            self.frame_deadline, self.next_ping = now + 30, now + 10
            print('[斗神大会] 已发送战斗准备信号，启用每10秒房间心跳', flush=True)
        if self.frames.is_set():
            if not self.frame_logged:
                self.frame_logged = True
                print('[斗神大会] 已收到服务器战斗帧，继续挂机', flush=True)
        elif now >= self.frame_deadline:
            raise RuntimeError('准备后未收到战斗帧，停止本场，不自动重新匹配')
        if now >= self.next_ping:
            # 原版业务ping及其回执上报，不能用Pomelo底层心跳替代。
            sent = int(time.time() * 1000)
            reply = _request(self.team, 'copy.copyHandler.ping', {'time': sent}, timeout=5)
            # BattleMapBase.onPingBack只检查时间回显。真人服实测会返回
            # code=500、正确time/serverTime且无error，不能套用业务结算的code校验。
            if (not isinstance(reply, dict) or reply.get('error')
                    or reply.get('time') != sent):
                raise RuntimeError('战斗房间心跳回执异常，停止本场')
            elapsed = max(0, int((self.clock() - now) * 1000))
            self.team.notify('copy.copyHandler.keyOperation', {'keys': [84], 'objs': [
                {'ping': True, 'pingTime': elapsed, 'teamPs': self.seat}]})
            self.next_ping = self.clock() + 10


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
    battle = None
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
                if battle:
                    battle.tick()
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
                matched = True
                battle_deadline = time.monotonic() + battle_seconds
                team = team_connect(data)
                seat, player = seat_info(data, flow.uid)
                # 必须在enter/loadComplete之前监听，以免漏掉很快到达的推送。
                battle = BattleKeepalive(team, seat)
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
                if battle:
                    battle.stop()
                print("[斗神大会] 收到服务器结算", flush=True)
                return _confirm_match(flow, slot, before)
            if battle:
                battle.tick()
    finally:
        if battle:
            battle.stop()
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
            prior_season = dict(info.get('pvpSeason') or {})
            if not _one_match(flow, events, slot, _match_count(info),
                              args.match_seconds, args.battle_seconds):
                break
            info = enter(flow, slot)
            season = info.get('pvpSeason') or {}
            if any(key in prior_season and key in season and int(season[key]) > int(prior_season[key])
                   for key in ('escape', 'totalEscape')):
                print('[斗神大会] 服务器逃跑计数增加，已停止后续匹配，请核查本场', flush=True)
                return 1
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
