"""灵宠乱斗：匹配后进入房间并保持在线，战斗阶段不发送操作或伪造结算。"""

import argparse
import json
import queue
import time
from pathlib import Path

from teacher_trial import connect

R_INFO = "scene.petPvpHandler.getPetPVPInfo"
R_MATCH = "scene.petPvpHandler.matchStart"
R_CANCEL = "scene.petPvpHandler.matchCancel"
R_READY = "room.waitingRoomHandler.changePlayerStatus"
R_LOADED = "room.petPvpRoomHandler.loadingEnd"
DUNGEON = 2000101
EVENTS = ("onPVPMatchResult", "onPrepareCreateOnlineCopy", "onPetPvpBtlChangeState",
          "onPetPVPFinish", "onPetPvpBtlExit", "kicked")


def _message(body):
    if not isinstance(body, dict):
        return {}
    inner = body.get("message")
    return inner if isinstance(inner, dict) else body


def _checked(result, name):
    if not isinstance(result, dict) or result.get("code") != 200 or result.get("error"):
        detail = result.get("error") or result.get("code") if isinstance(result, dict) else result
        raise RuntimeError("%s：%s" % (name, detail))
    return result


def _one_match(flow, events, match_seconds, battle_seconds, exit_seconds=20, controller=None):
    before = _checked(flow.request(R_INFO, {}), "读取乱斗状态")
    before_total = int(((before.get("petPvp") or {}).get("1") or {}).get("total") or 0)
    _checked(flow.request(R_MATCH, {}), "发起匹配")
    print("[灵宠乱斗] 已发起匹配，等待对手", flush=True)
    room_id = None
    matched = False
    loading = False
    finished = False
    total_ok = False
    next_loading = 0.0
    match_deadline = time.monotonic() + match_seconds
    battle_deadline = None
    exit_deadline = None
    try:
        while True:
            if controller is not None:
                controller.process(flow)
            now = time.monotonic()
            deadline = exit_deadline if exit_deadline is not None else battle_deadline if battle_deadline is not None else match_deadline
            if now >= deadline:
                if finished:
                    print("[灵宠乱斗] 结算后等待房间关闭超时（%d秒），按已结算处理" % exit_seconds, flush=True)
                    return total_ok
                if not matched:
                    print("[灵宠乱斗] 等待匹配超时", flush=True)
                else:
                    print("[灵宠乱斗] 已入房，挂机观察时间结束；服务器尚未推送最终结算", flush=True)
                return False
            if loading and now >= next_loading:
                reply = flow.request(R_LOADED, {"roomId": room_id})
                if reply.get("code") == 500:
                    loading = False
                elif reply.get("code") != 200 or reply.get("error"):
                    raise RuntimeError("上报加载状态失败：%s" % (reply.get("error") or reply.get("code")))
                next_loading = time.monotonic() + 2
            timeout = min(0.2 if controller is not None else 2, max(0.1, deadline - time.monotonic()))
            try:
                route, body = events.get(timeout=timeout)
            except queue.Empty:
                continue
            data = _message(body)
            if route == "kicked":
                raise RuntimeError("服务器断开了当前连接")
            if route == "onPVPMatchResult":
                if str(data.get("battleType") or "8") != "8":
                    continue
                if data.get("code") != 200:
                    raise RuntimeError("匹配失败：%s" % (data.get("error") or data.get("code")))
                matched = True
                battle_deadline = time.monotonic() + battle_seconds
                print("[灵宠乱斗] 已匹配到对手", flush=True)
            elif route == "onPrepareCreateOnlineCopy":
                if int(data.get("dungeonId") or 0) != DUNGEON:
                    continue
                room_id = data.get("roomId")
                if not room_id:
                    raise RuntimeError("准备入房时服务器未提供 roomId")
                if loading:
                    continue
                matched = True
                battle_deadline = time.monotonic() + battle_seconds
                _checked(flow.request(R_READY, {"roomId": room_id, "status": 4}), "准备入房")
                loading = True
                next_loading = time.monotonic()
                print("[灵宠乱斗] 已准备入房，开始保持加载与心跳", flush=True)
            elif route == "onPetPvpBtlChangeState":
                if matched:
                    print("[灵宠乱斗] 战斗阶段：回合%s，阶段%s，剩余%s秒；继续挂机" %
                          (data.get("session"), data.get("btlStage"), data.get("time")), flush=True)
            elif route == "onPetPVPFinish":
                print("[灵宠乱斗] 服务器已推送最终结算", flush=True)
                if data.get("error"):
                    print("[灵宠乱斗] 结算提示：%s" % data["error"], flush=True)
                finished = True
                loading = False
                total_ok = False
                for _ in range(5):
                    latest = _checked(flow.request(R_INFO, {}), "核对乱斗战绩")
                    total = int(((latest.get("petPvp") or {}).get("1") or {}).get("total") or 0)
                    if total > before_total:
                        print("[灵宠乱斗] 战绩场次 %d → %d，本场已计入" % (before_total, total), flush=True)
                        total_ok = True
                        break
                    time.sleep(2)
                if not total_ok:
                    print("[灵宠乱斗] 已结算但战绩尚未增加，本场不继续下一场", flush=True)
                exit_deadline = time.monotonic() + exit_seconds
                print("[灵宠乱斗] 保持心跳，等待房间关闭通知（最多%d秒）" % exit_seconds, flush=True)
            elif route == "onPetPvpBtlExit":
                if finished:
                    print("[灵宠乱斗] 收到房间退出通知，本场正常结束", flush=True)
                    return matched and total_ok
                print("[灵宠乱斗] 收到房间退出通知", flush=True)
                return False
    finally:
        if not matched:
            try:
                result = flow.request(R_CANCEL, {})
                print("[灵宠乱斗] 取消排队：%s" % (result.get("error") or result.get("code")), flush=True)
            except Exception as exc:
                print("[灵宠乱斗] 取消排队未确认：%s" % exc, flush=True)


def main():
    parser = argparse.ArgumentParser(description="灵宠乱斗匹配并挂机")
    parser.add_argument("--matches", type=int, default=4)
    parser.add_argument("--match-seconds", type=int, default=90)
    parser.add_argument("--battle-seconds", type=int, default=600)
    parser.add_argument("--exit-seconds", type=int, default=20, help="结算后保持心跳、等待房间关闭的秒数")
    parser.add_argument("--interactive", action="store_true", help="打开准备阶段手动选宠、上符窗口")
    args = parser.parse_args()
    if args.matches < 1:
        parser.error("匹配场数须为正整数")
    if args.match_seconds < 10 or not 60 <= args.battle_seconds <= 600:
        parser.error("匹配至少等待10秒，单场挂机时间须为60～600秒")
    if not 5 <= args.exit_seconds <= 120:
        parser.error("结算等待须为5～120秒")
    flow = None
    try:
        path = Path(__file__).resolve().parent / "account.local.json"
        with path.open(encoding="utf-8") as stream:
            account = json.load(stream)
        slot = int(account.get("record_index", 0))
        flow, _ = connect(account, slot)
        print("[灵宠乱斗] 使用存档槽 %d" % slot, flush=True)
        if args.interactive:
            from pet_brawl_control import run_window
            args.record_index = slot
            run_window(flow, account['uid'], args)
            return 0
        events = queue.Queue()
        for route in EVENTS:
            flow.on(route, lambda body, name=route: events.put((name, body)))
        for number in range(1, args.matches + 1):
            while not events.empty():
                events.get_nowait()
            print("[灵宠乱斗] 第 %d/%d 次" % (number, args.matches), flush=True)
            if not _one_match(flow, events, args.match_seconds, args.battle_seconds, args.exit_seconds):
                break
            if number < args.matches:
                time.sleep(3)
    except RuntimeError as exc:
        print("[灵宠乱斗] %s" % exc, flush=True)
        return 1
    finally:
        if flow:
            flow.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
