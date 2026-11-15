"""斗神大会：真人场挂机，机器人场默认立即结算胜利（--robot-fail 改为失败结算）。

真人场按原仓库 Fylxom/ZMXY5 的 pvp_match.py 翻译：
战斗帧里对手 connected=false（对局已在对面结束）→ 按“我方被打死”提交 battleResult=4；
服务器帧号超过 5670（时间到）→ 按“没人死”提交 battleResult=4；
服务器先推 onPVPFinish/onCopyAbnormal → 直接采用，不再提交。
默认只用原仓库信号；加 --model-fail 为混合方案：模型判死不提交，等对手掉线时才提交，
血量高于 25% 报胜利，25% 以内报失败。
"""

import argparse
import json
import os
import queue
import random
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from halo_solo import _request
from teacher_trial import connect, enter, seat_info, team_connect
import pvp_sim

TASK_ID = 990013
TARGET = 3
FPS = 30
TIME_LIMIT_FRAMES = 5670      # 客户端 PvP 时间到：5670 帧（约 189 秒）
FINISH_WAIT = 30              # 提交 battleExit 后等待 onPVPFinish 的秒数
INSTANT_FAIL_RANGE = (1.0, 3.0)  # --instant-fail：开局随机 1–3 秒内提交失败（仅测试）
BATTLE_WAIT = 240             # 原仓库挂机最长等待（略长于 189 秒时间上限）
EVENTS = ("onPVPMatchResult", "onPlayerJoinWaitingRoom", "onPrepareCreateOnlineCopy",
          "onCreateOnlineCopy", "onCreateOnlineCopyError", "onPlayerLeaveWaitingRoom",
          "onPVPFinish", "onCopyAbnormal", "kicked")


def _client_cg():
    """读取当前客户端的配置版本，战报回放会用 cg 与客户端 CurrCg 比对。"""
    base = Path(os.environ.get("APPDATA", "")) / "dusk.zmBox" / "Local Store" / "zm5" / "assets" / "data"
    for path in sorted(base.glob("gameresources_*.xml"), reverse=True):
        try:
            root = ET.parse(path).getroot()
        except Exception:
            continue
        for item in root.iter("item"):
            if (item.findtext("name") or "").strip() == "config":
                url = (item.findtext("url") or "").strip()
                if url:
                    return url
    return "cg1"


CLIENT_CG = _client_cg()


def _message(body):
    if not isinstance(body, dict):
        return {}
    value = body.get("message")
    return value if isinstance(value, dict) else body


def _num(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _deep_num(source, names, depth=4):
    """在 enter 响应里递归找 sendKeyFrameNum：每条帧推送代表多少帧。"""
    if depth < 0:
        return 0
    if isinstance(source, dict):
        for key in names:
            value = source.get(key)
            if isinstance(value, (int, float)) and value:
                return int(value)
        values = source.values()
    elif isinstance(source, list):
        values = source
    else:
        return 0
    for value in values:
        found = _deep_num(value, names, depth - 1)
        if found:
            return found
    return 0


class _Frames:
    """按客户端 QCOnServerFrame 解析战斗帧，避免用 len(frames) 猜帧号。"""

    def __init__(self, opp_ids, opp_oper_index, per=1, me_ids=()):
        self.opp_ids = {int(v) for v in opp_ids if v is not None}
        self.me_ids = {int(v) for v in me_ids if v is not None}
        self.opp_oper_index = int(opp_oper_index)
        self.per = max(1, int(per))
        self.ser = 0                 # serFrameNum：服务器权威帧号
        self.last = 0                # 已处理的最大 currFrame
        self.op_seen = 0             # 已统计操作的最大 currFrame（与模型时间轴解耦）
        self.gone_frame = None       # 对手 connected=false 出现的帧
        self.gone_at = None
        self.opp_ops = 0
        self.debug_ops = 0
        self.debug_status = 0

    @property
    def frame(self):
        return max(self.ser, self.last)

    def feed(self, body):
        """喂一次 onSendFrame，返回新增的 [(frameNum, 对手按键)]；末尾推进到 serFrameNum。"""
        data = _message(body)
        ser = _num(data.get("serFrameNum"))
        if ser > self.ser:
            self.ser = ser
        raw = [f for f in (data.get("frames") or []) if isinstance(f, dict)]
        items = []
        for index, frame in enumerate(raw):
            curr = _num(frame.get("currFrame"))
            if not curr:
                curr = ser - (len(raw) - 1 - index) * self.per
            # 掉线状态帧可能晚于 serFrameNum 到达，不能被 last 过滤掉。
            for state in frame.get("status") or []:
                if not isinstance(state, dict) or state.get("battlePos") is None:
                    continue
                if self.debug_status < 5:
                    self.debug_status += 1
                    print("[斗神大会] 状态帧样本：frame=%s pos=%s connected=%s escape=%s"
                          % (curr, state.get("battlePos"), state.get("connected"),
                             state.get("playerEscape")), flush=True)
                if state.get("connected") in (False, 0):
                    pos = _num(state.get("battlePos"))
                    # battlePos 对应 playerIdIndex（战报已确认），不能用 teamPs 推。
                    if pos in self.opp_ids or (not self.opp_ids and pos not in self.me_ids):
                        if self.gone_frame is None:
                            self.gone_frame = (_num(state.get("disconnectFrameNum"))
                                               or curr or self.frame)
                            self.gone_at = time.monotonic()
                            print("[斗神大会] 对手掉线：frame %d（%.2fs）"
                                  % (self.gone_frame, self.gone_frame / float(FPS)),
                                  flush=True)
            keys = []
            # 操作统计独立去重：serFrameNum 会提前推进 last，不能用 last 过滤操作帧。
            if curr > self.op_seen:
                for oper in frame.get("playerOper") or []:
                    if not isinstance(oper, dict):
                        continue
                    index = _num(oper.get("playerIdIndex"))
                    pressed = [_num(k) for k in (oper.get("keys") or []) if _num(k)]
                    if pressed and self.debug_ops < 3:
                        self.debug_ops += 1
                        print("[斗神大会] 帧操作样本：frame=%d idx=%d keys=%s"
                              % (curr, index, pressed[:8]), flush=True)
                    if index != self.opp_oper_index:
                        continue
                    if pressed:
                        keys.extend(pressed)
                        self.opp_ops += len(pressed)
                self.op_seen = curr
            if curr <= self.last:
                continue
            items.append((curr, keys))
            self.last = curr
        # 只有本次推送没有真实帧时才补空帧推进，避免把下一次推送的操作帧提前判成旧帧。
        if not raw and self.ser > self.last:
            items.append((self.ser, []))
            self.last = self.ser
        return items


def _fail_settlement_payload(online, uid, frame_num, killed):
    """原仓库 ExitBattleServerCmd.battleExit：一律报输（battleResult=4）。

    killed=True（对手已结束对局，视为我方被打死）：我方 hp=0、dead=True；
    否则是“时间到”：所有人都不死，hp 用 enter 里的原值。
    """
    rows = []
    for index, row in enumerate(online.get("playerInfos") or []):
        if not isinstance(row, dict):
            continue
        player_id = str(row.get("uid") or row.get("playerId"))
        mine = player_id == str(uid)
        dead = killed and mine
        hp = 0 if dead else (_num(row.get("hp")) or _num(row.get("hpMax")) or 1)
        rows.append({
            "playerId": player_id,
            "hp": hp,
            "isme": mine,
            "campId": index + 1,
            "dead": dead,
            "exit": False,
            "from": "",
        })
    return {"battleResult": 4, "playerInfo": rows, "data": [],
            "frameNum": max(1, frame_num)}


def _win_settlement_payload(online, uid, frame_num, self_hp):
    """混合方案：对手掉线且我方血量高于 25% 时按胜利提交（battleResult=5）。

    我方用模型血量、不标死；对手视为已结束对局（dead/exit）。
    """
    rows = []
    for index, row in enumerate(online.get("playerInfos") or []):
        if not isinstance(row, dict):
            continue
        player_id = str(row.get("uid") or row.get("playerId"))
        mine = player_id == str(uid)
        if mine:
            hp = int(self_hp) if self_hp is not None else (
                _num(row.get("hp")) or _num(row.get("hpMax")) or 1)
        else:
            hp = 0
        rows.append({
            "playerId": player_id,
            "hp": hp,
            "isme": mine,
            "campId": index + 1,
            "dead": not mine,
            "exit": not mine,
            "from": "gate" if mine else "",
        })
    return {"battleResult": 5, "playerInfo": rows, "data": [],
            "frameNum": max(1, frame_num)}


class _AutoFail:
    """本地伤害模型：逐帧喂对手按键推算我方 HP，仅用于日志和 --model-fail 判死提交。"""

    def __init__(self, infos, uid, burn_total=0.0):
        if not infos:
            raise RuntimeError("缺少 playerInfos")
        me = None
        for i, row in enumerate(infos):
            if str(row.get("uid") or row.get("playerId")) == str(uid):
                me = i
                break
        if me is None:
            raise RuntimeError("playerInfos 中找不到自己")
        cfg_dir = os.environ.get("PVP_SIM_CFG") or pvp_sim.DEFAULT_CFG
        self.cfg = pvp_sim.Config(cfg_dir)
        ps, _strong, _weak = pvp_sim.pvp_final(self.cfg, infos[0], infos[1])
        pvp_sim.attach_player_meta(self.cfg, ps, infos)
        opp = 1 - me
        opts = dict(att_len=0.33, skill_tail=0.0,
                    x_att=150 if opp == 0 else 1350,
                    x_dfd=150 if me == 0 else 1350,
                    speed=240, body_half=30, lock_movement=True,
                    hit_mode="all", summon_hits=5, summon_life=5.0,
                    burn_total=burn_total)
        self.sim = pvp_sim.BattleSim(self.cfg, ps[opp], ps[me], opts)
        idx = infos[opp].get("playerIdIndex")
        self.opp_index = int(idx) if idx is not None else opp
        self.me_index = me
        self.hp_max = ps[me]["allhpMax"]
        self.death_frame = None

    def feed(self, items):
        for frame_num, keys in items:
            self.sim.feed(frame_num, keys)
            if self.death_frame is None and self.sim.hp <= 0:
                self.death_frame = frame_num
                print("[斗神大会] 本地模型判定 HP 归零：frame %d（%.2fs），HP %d/%d"
                      % (frame_num, frame_num / float(FPS), self.sim.hp, self.hp_max),
                      flush=True)


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


def _one_match(flow, events, slot, before, match_seconds, battle_seconds,
               robot_fail=False, instant_fail=False, model_fail=False,
               robot_fail_streak=0, loss_streak=0):
    instant_delay = random.uniform(*INSTANT_FAIL_RANGE) if instant_fail else None
    reply = _checked(flow.request("scene.pvpHandler.matchStart", {}), "斗神匹配")
    if reply.get("robot"):
        robot = reply["robot"]
        if not isinstance(robot, dict) or not robot.get("name") or not robot.get("entityId"):
            raise RuntimeError("机器人匹配缺少对手资料")
        fail_robot = robot_fail or (robot_fail_streak > 0 and loss_streak >= robot_fail_streak)
        win = 0 if fail_robot else 1
        if instant_fail:
            time.sleep(instant_delay)
            win = 0
            print("[斗神大会] 匹配到机器人，开局随机 %.1f 秒后提交失败结算（--instant-fail）"
                  % instant_delay, flush=True)
        else:
            print("[斗神大会] 匹配到机器人（此前连败 %d 场，阈值 %d），立即提交%s结算"
                  % (loss_streak, robot_fail_streak, "失败" if fail_robot else "胜利"),
                  flush=True)
        result = _checked(flow.request("scene.pvpHandler.robotPVPFinish", {
            "win": win, "name": robot["name"], "entityId": robot["entityId"]}), "机器人战斗结算")
        win_type = int((result.get("data") or {}).get("winType") or 0)
        if instant_fail:
            print("[斗神大会] 机器人失败结算返回：winType=%d" % win_type, flush=True)
        elif win_type != win:
            raise RuntimeError("机器人结算结果异常：winType=%d（期望 %d）" % (win_type, win))
        return _confirm_match(flow, slot, before), bool(win)
    print("[斗神大会] 已发起匹配", flush=True)
    room_id = None
    team = None
    team_events = queue.Queue()
    online_copy = None
    matched = False
    next_ping = 0.0
    next_battle_ping = 0.0
    team_closed = False
    match_deadline = time.monotonic() + match_seconds
    battle_deadline = None
    enter_at = None
    frames = None
    my_slot = 0
    battle_loaded = False
    battle_start = None
    opponent_ops = 0
    accepted = False
    finish_deadline = None
    submit_tries = 0
    next_submit = 0.0
    win = False
    final_win = None
    auto = None
    try:
        while True:
            now = time.monotonic()
            deadline = battle_deadline or match_deadline
            if battle_start is None:
                if now >= deadline:
                    print("[斗神大会] 匹配/进场超时，本场停止", flush=True)
                    return False, None
            elif now >= battle_start + BATTLE_WAIT + FINISH_WAIT + 10:
                print("[斗神大会] 挂机与结算等待均超时，本场停止", flush=True)
                return False, None
            if accepted and finish_deadline is not None and now >= finish_deadline:
                print("[斗神大会] 提交后 %d 秒未收到服务器结算，停止连续匹配"
                      % FINISH_WAIT, flush=True)
                return False, final_win
            if team_closed and not accepted:
                print("[斗神大会] 未提交结算即断开，本场停止", flush=True)
                return False, None
            if room_id and team is None and now >= next_ping:
                flow.request("room.waitingRoomHandler.ping", {
                    "roomId": str(room_id), "code": 200,
                    "time": int(time.time() * 1000)})
                next_ping = time.monotonic() + 5
            if team is not None and not team_closed and now >= next_battle_ping:
                sent = time.time()
                try:
                    back = _request(team, "copy.copyHandler.ping",
                                    {"time": int(sent * 1000)}, timeout=3)
                except Exception:
                    back = None
                back = _message(back) if isinstance(back, dict) else {}
                if "time" in back:
                    # 客户端的按键保活：ping 回来后用按键通道广播延迟，避免被判无操作。
                    team.notify("copy.copyHandler.keyOperation", {
                        "keys": [84],
                        "objs": [{"ping": True,
                                  "pingTime": int((time.time() - sent) * 1000),
                                  "teamPs": my_slot}]})
                next_battle_ping = time.monotonic() + 10
            while team is not None:
                try:
                    troute, tbody = team_events.get_nowait()
                except queue.Empty:
                    break
                if troute == "loaded":
                    battle_loaded = True
                    battle_start = time.monotonic()
                    team.notify("copy.copyHandler.keyOperation", {
                        "keys": [84],
                        "objs": [{"ready": True, "uid": my_slot, "teamPs": my_slot}]})
                    if frames is not None and frames.gone_frame is not None:
                        print("[斗神大会] 加载阶段对手已掉线，忽略该信号，交由加载超时处理",
                              flush=True)
                        frames.gone_frame = None
                        frames.gone_at = None
                    print("[斗神大会] 双方加载完成，开始挂机（对手结束/5670帧时间到才结算）",
                          flush=True)
                elif troute == "frame":
                    if frames is not None:
                        items = frames.feed(tbody)
                        opponent_ops = frames.opp_ops
                        if auto is not None and items:
                            try:
                                auto.feed(items)
                            except Exception as exc:
                                auto = None
                                print("[斗神大会] 本地模型异常，仅保留服务器信号：%s"
                                      % exc, flush=True)
                elif troute == "close":
                    team_closed = True
                    print("[斗神大会] 战斗服连接已断开", flush=True)
                elif troute in ("onPVPFinish", "onCopyAbnormal"):
                    # 结算/异常也可能从战斗服推送（客户端两路都在听）。
                    events.put((troute, tbody))
            if (team is not None and not team_closed and not accepted
                    and submit_tries < 5 and battle_start is not None and frames is not None):
                now = time.monotonic()
                elapsed = now - battle_start
                # 原仓库只用服务器帧号判断，不做任何本地 HP/伤害推断。
                live_frame = frames.frame
                reason = ""
                killed = False
                if instant_fail and elapsed >= instant_delay:
                    killed = True
                    live_frame = 1
                    reason = ("开局随机 %.1f 秒提交失败（--instant-fail，实际第 %.1f 秒）"
                              % (instant_delay, elapsed))
                elif frames.gone_frame is not None:
                    # 对手已结束对局（提交结算后掉线）：混合方案按模型剩余血量判胜负。
                    if model_fail:
                        hp = int(auto.sim.hp) if auto is not None else None
                        hp_max = auto.hp_max if auto is not None else None
                        if hp is not None and hp_max and hp > hp_max * 0.25:
                            win = True
                            reason = ("对手已结束对局（frame %d），模型HP=%d/%d 高于25%%，按胜利提交"
                                      % (frames.gone_frame, hp, hp_max))
                        else:
                            killed = True
                            reason = ("对手已结束对局（frame %d），模型HP=%s 在25%%以内，按失败提交"
                                      % (frames.gone_frame, hp))
                    else:
                        killed = True
                        reason = "对手已结束对局（frame %d），按被打死提交" % frames.gone_frame
                elif live_frame > TIME_LIMIT_FRAMES:
                    reason = ("时间到（服务器帧号 %d 超过 %d），按输提交"
                              % (live_frame, TIME_LIMIT_FRAMES))
                elif elapsed >= BATTLE_WAIT:
                    reason = "挂机超过 %d 秒仍未结束，按时间到提交" % BATTLE_WAIT
                if reason and now >= next_submit:
                    if win:
                        payload = _win_settlement_payload(
                            online_copy or {}, flow.uid,
                            frames.gone_frame or live_frame,
                            int(auto.sim.hp) if auto is not None else None)
                        label = "胜利"
                    else:
                        payload = _fail_settlement_payload(
                            online_copy or {}, flow.uid,
                            frames.gone_frame or live_frame, killed)
                        label = "失败"
                    print("[斗神大会] 提交%s结算（%s） battleResult=%d frameNum=%d 对手操作=%d"
                          % (label, reason, payload["battleResult"], payload["frameNum"],
                             opponent_ops), flush=True)
                    try:
                        exit_reply = _request(team, "copy.copyHandler.battleExit", payload)
                    except TimeoutError as exc:
                        print("[斗神大会] 结算超时：%s" % exc, flush=True)
                        exit_reply = {}
                    code = exit_reply.get("code") if isinstance(exit_reply, dict) else None
                    if code == 200:
                        accepted = True
                        final_win = bool(win)
                        finish_deadline = time.monotonic() + FINISH_WAIT
                        print("[斗神大会] %s结算已受理，等待服务器结算" % label, flush=True)
                    else:
                        submit_tries += 1
                        next_submit = time.monotonic() + 5
                        print("[斗神大会] %s结算暂未受理（%s），%d/5 次后重试"
                              % (label, code, submit_tries), flush=True)
                if submit_tries >= 5 and not accepted:
                    print("[斗神大会] 结算多次未受理，本场停止", flush=True)
                    return False, None
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
                online_copy = data
                infos = data.get("playerInfos") or []
                me_index, player = seat_info(data, flow.uid)
                others = [i for i in range(len(infos)) if i != me_index]
                opp_index = others[0] if others else -1
                opp_row = infos[opp_index] if 0 <= opp_index < len(infos) else {}
                opp_oper = _num(opp_row.get("playerIdIndex")) if opp_row else -1
                me_row = infos[me_index] if 0 <= me_index < len(infos) else {}
                my_battle = _num(me_row.get("playerIdIndex"))
                opp_battle = _num(opp_row.get("playerIdIndex"))
                # battlePos 只对应 playerIdIndex；teamPs/index 会串座（战报已确认）。
                me_ids = {my_battle} if my_battle is not None else {me_index}
                opp_ids = {opp_battle} if opp_battle is not None else {opp_index}
                my_slot = my_battle
                if my_slot is None:
                    my_slot = _num(me_row.get("teamPs"))
                if my_slot is None:
                    my_slot = me_index
                frames = _Frames(opp_ids, opp_oper if opp_oper >= 0 else opp_index,
                                 me_ids=me_ids)
                try:
                    copy_id = _num((online_copy or {}).get("copyId"))
                    burn_total = 0.06 if copy_id == 50090 else 0.0
                    auto = _AutoFail(infos, flow.uid, burn_total)
                    print("[斗神大会] 本地伤害模型已启用：我方 hpMax=%d，对手操作位=%d，地图=%s，灼烧=%.2f%%"
                          % (auto.hp_max, auto.opp_index, copy_id, burn_total * 100), flush=True)
                except Exception as exc:
                    auto = None
                    print("[斗神大会] 本地伤害模型未启用：%s" % exc, flush=True)
                team.on("onAllLoadComplete", lambda body: team_events.put(("loaded", body)))
                team.on("onSendFrame", lambda body: team_events.put(("frame", body)))
                team.on("onSocketClose", lambda body: team_events.put(("close", body)))
                enter_reply = _checked(_request(team, "copy.copyHandler.enter", {
                    "instId": data["instId"], "playerId": str(flow.uid),
                    "password": data["password"], "abnormalFrameNum": 0,
                    "cg": player.get("cg") or data.get("cg") or CLIENT_CG}), "进入战斗服")
                frames.per = _deep_num(enter_reply, ("sendKeyFrameNum",
                                                     "send_key_frame_num")) or 1
                team.notify("copy.copyHandler.loadComplete", {})
                enter_at = time.monotonic()
                next_submit = 0.0
                next_battle_ping = time.monotonic() + 10
                print("[斗神大会] 已进入战斗服，等待双方加载完成", flush=True)
            elif route == "onCreateOnlineCopyError":
                raise RuntimeError("创建战斗实例失败：%s" % (data.get("error") or data))
            elif route == "onPlayerLeaveWaitingRoom":
                print("[斗神大会] 对手离开等待房间，继续等待服务器结算", flush=True)
            elif route == "onCopyAbnormal":
                if _num(data.get("code")) == 200:
                    continue
                print("[斗神大会] 服务器异常结束（code=%s），不再提交结算"
                      % data.get("code"), flush=True)
                return _confirm_match(flow, slot, before), None
            elif route == "onPVPFinish":
                season = data.get("pvpSeason") or {}
                model = ""
                if auto is not None:
                    model = " 对手操作=%d 模型frame=%d hp=%d/%d%s" % (
                        opponent_ops, frames.last if frames is not None else 0,
                        auto.sim.hp, auto.hp_max,
                        " 已归零@%d" % auto.death_frame if auto.death_frame is not None else "")
                print("[斗神大会] 收到服务器结算：winType=%s fail=%s 逃跑=%s/%s%s report=%s"
                      % (data.get("winType"), season.get("fail"),
                         season.get("escape"), season.get("totalEscape"), model,
                         data.get("reportId")), flush=True)
                for result in data.get("playerResult") or []:
                    if not isinstance(result, dict):
                        continue
                    exited = result.get("exitPlayerInfos") or {}
                    print("[斗神大会] 结算明细：playerId=%s result=%s 提交帧=%s"
                          % (result.get("playerId"), result.get("result"),
                             exited.get("frameNum")), flush=True)
                win_type = _num(data.get("winType"))
                outcome = True if win_type == 1 else (False if win_type == 0 else None)
                return _confirm_match(flow, slot, before), outcome
    finally:
        if team:
            team.disconnect()
        if not matched:
            try:
                flow.request("scene.pvpHandler.matchCancel", {})
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="斗神大会匹配，默认4场")
    parser.add_argument("--matches", type=int, default=4)
    parser.add_argument("--match-seconds", type=int, default=90)
    parser.add_argument("--battle-seconds", type=int, default=240)
    parser.add_argument("--robot-fail", action="store_true", help="机器人场也提交失败结算")
    parser.add_argument("--robot-fail-streak", type=int, default=0,
                        help="连败达到 N 场后再遇到机器人时，机器人局也提交失败（0=关闭）")
    parser.add_argument("--instant-fail", action="store_true",
                        help="进战斗后立即按 alld 提交失败（仅测试服务器判定，勿用于正式挂机）")
    parser.add_argument("--model-fail", action="store_true",
                        help="混合方案：模型判死不提交；对手掉线时血量高于25%%报胜利，否则报失败")
    parser.add_argument("--account", default="", help="账号文件名或路径，默认 account.local.json")
    parser.add_argument("--slot", type=int, default=-1, help="存档槽，默认取账号文件 record_index")
    args = parser.parse_args()
    if args.matches < 1:
        parser.error("匹配场数须为正整数")
    if args.match_seconds < 10 or not 60 <= args.battle_seconds <= 600:
        parser.error("匹配至少等待10秒，单场挂机时间须为60～600秒")
    flow = None
    try:
        root = Path(__file__).resolve().parent
        if args.account:
            account_path = Path(args.account)
            if not account_path.is_file():
                name = args.account if args.account.endswith(".json") else args.account + ".json"
                account_path = root / "accounts" / name
        else:
            account_path = root / "account.local.json"
        with account_path.open(encoding="utf-8") as stream:
            account = json.load(stream)
        slot = args.slot if args.slot >= 0 else int(account.get("record_index", 0))
        flow, info = connect(account, slot)
        events = queue.Queue()
        for route in EVENTS:
            flow.on(route, lambda body, name=route: events.put((name, body)))
        progress = _task_progress(info)
        season = info.get("pvpSeason") or {}
        print("[斗神大会] 存档槽 %d，今日任务 %s，逃跑 %s/%s，本次计划 %d 场" %
              (slot, "%d/%d" % (progress, TARGET) if progress is not None else "未显示",
               season.get("escape"), season.get("totalEscape"), args.matches), flush=True)
        loss_streak = 0
        for number in range(args.matches):
            while not events.empty():
                events.get_nowait()
            print("[斗神大会] 第 %d/%d 场" % (number + 1, args.matches), flush=True)
            ok, won = _one_match(flow, events, slot, _match_count(info),
                                 args.match_seconds, args.battle_seconds,
                                 args.robot_fail, args.instant_fail, args.model_fail,
                                 args.robot_fail_streak, loss_streak)
            if not ok:
                break
            if won is True:
                loss_streak = 0
            elif won is False:
                loss_streak += 1
                print("[斗神大会] 当前连败 %d 场" % loss_streak, flush=True)
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
