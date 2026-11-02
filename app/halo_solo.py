"""十绝阵单人联机结算与领奖。每次调用最多消耗一次奖励次数。"""

import threading
import json
from pathlib import Path

from pypomelo.client import PomeloClient


def _request(client, route, data, timeout=15):
    done = threading.Event()
    box = {}

    def callback(reply):
        box["reply"] = reply
        done.set()

    client.request(route, data, callback)
    if not done.wait(timeout):
        raise TimeoutError("%s 响应超时" % route)
    return box["reply"]


def _bag_counts(info):
    return {str(k): int(v.get("count", 0))
            for k, v in ((info.get("bag") or {}).get("item") or {}).items()
            if isinstance(v, dict)}


SCORE_CHOICES = (1000, 3000)


def score_parts(target_score):
    """1000分用一个位置，3000分用三个位置。"""
    if target_score not in SCORE_CHOICES:
        raise ValueError("十绝阵奖励档位无效: %s" % target_score)
    if target_score == 1000:
        return [(1000, 1000)]
    return [(1000, 1000), (1000, 1000), (1000, 1000)]


def run_halo_solo(flow, info, dungeon_id, record_index, target_score=3000):
    target_score = int(target_score)
    parts = score_parts(target_score)
    latest = flow.request("connector.entryHandler.entry", {
        "index": record_index, "userAgent": flow.user_agent})
    if not isinstance(latest, dict) or latest.get("code") != 200 or latest.get("error") or not isinstance(latest.get("info"), dict):
        print("[十绝阵] 无法读取最新存档，未建房:", latest)
        return False
    info.clear()
    info.update(latest["info"])
    limits_path = Path(__file__).with_name("halo_requirements.json")
    if limits_path.exists():
        limits = json.loads(limits_path.read_text(encoding="utf-8"))
        required = int(limits.get(str(dungeon_id), 0))
        power = info.get("power")
        if power is not None and required > 0 and float(power) < required:
            print("[十绝阵] 战力不足：当前%s，需要%s；未建房，不消耗次数" % (power, required))
            return False
    remain = int((info.get("halo") or {}).get("haloRewardCnt", 0))
    if remain <= 0:
        print("[十绝阵] 奖励次数不足，跳过")
        return False

    room_id = None
    team = None
    online = threading.Event()
    result_ready = threading.Event()
    state = {}

    def on_online(message):
        if isinstance(message, dict) and int(message.get("copyType", 0)) == dungeon_id:
            state["online"] = message
            online.set()

    def on_result(message):
        if isinstance(message, dict):
            state["result"] = message
            result_ready.set()

    flow.on("onCreateOnlineCopy", on_online)
    flow.on("onHaloResult", on_result)
    before = _bag_counts(info)
    try:
        made = flow.request("room.waitingRoomHandler.createWaitingRoom",
                            {"dungeonId": dungeon_id, "type": "halo"})
        if made.get("code") != 200 or made.get("error") or not (made.get("room") or {}).get("roomId"):
            raise RuntimeError("建房失败: %s" % (made.get("error") or made.get("code")))
        room_id = made["room"]["roomId"]
        prepared = flow.request("room.waitingRoomHandler.prepareCreateOnlineCopy", {"roomId": room_id})
        if prepared.get("code") != 200 or prepared.get("error"):
            raise RuntimeError("准备失败: %s" % (prepared.get("error") or prepared.get("code")))
        flow.request("room.waitingRoomHandler.loadingProgress",
                     {"roomId": room_id, "percent": 100, "version": 1})
        if not online.wait(12):
            raise TimeoutError("未收到联机副本实例")
        message = state["online"]

        team = PomeloClient()
        connected = threading.Event()
        team.connect(message["ip"], int(message["port"]), user={},
                     handshake_cb=lambda _: connected.set())
        if not connected.wait(10):
            raise TimeoutError("战斗服握手超时")
        uid = str(flow.uid)
        entered = _request(team, "copy.copyHandler.enter", {
            "instId": message["instId"], "playerId": uid,
            "password": message.get("password"), "abnormalFrameNum": 0,
            "cg": message.get("cg") or "cg1"})
        if entered.get("code") != 200 or entered.get("error"):
            raise RuntimeError("进入战斗失败: %s" % (entered.get("error") or entered.get("code")))

        seat = {"win": True, "uid": uid, "hp": 1000, "hpMax": 1000,
                "frame": 0, "remainTime": 600, "time": 600,
                "remainHpPercent": 1000}
        seat_results = [dict(seat, hp=percent, remainHpPercent=percent, score=points)
                        for points, percent in parts]
        finished = _request(team, "copy.copyHandler.battleExit", {
            "battleResult": 5,
            "playerInfo": [{"playerId": uid, "hp": 1, "isme": True,
                            "campId": 1, "dead": False, "exit": False, "from": ""}],
            "data": seat_results, "frameNum": 0})
        if finished.get("code") != 200 or finished.get("error"):
            raise RuntimeError("结算失败: %s" % (finished.get("error") or finished.get("code")))
        if not result_ready.wait(10):
            raise TimeoutError("未收到十绝阵结算结果")
        result = state["result"]
        score = int(result.get("score", 0))
        print("[十绝阵] 服务器结算分数:", score)
        if result.get("code") != 200 or score < target_score:
            print("[十绝阵] 未达到所选档位，停止领奖:", result.get("error") or result.get("drops"))
            return False

        reward = flow.request("scene.copyHandler.getHaloReward", {})
        if reward.get("code") != 200 or reward.get("error"):
            raise RuntimeError("领奖失败: %s" % (reward.get("error") or reward.get("code")))
        verified = flow.request("connector.entryHandler.entry",
                                {"index": record_index, "userAgent": flow.user_agent})
        if verified.get("code") != 200 or verified.get("error") or not isinstance(verified.get("info"), dict):
            raise RuntimeError("领奖请求已提交，但无法核对存档；停止，不自动重试")
        fresh = verified["info"]
        after = _bag_counts(fresh)
        gained = {k: after.get(k, 0) - before.get(k, 0)
                  for k in sorted(set(before) | set(after))
                  if after.get(k, 0) > before.get(k, 0)}
        after_remain = int((fresh.get("halo") or {}).get("haloRewardCnt", -1))
        info.clear()
        info.update(fresh)
        if after_remain != remain - 1 or not gained:
            print("[十绝阵] 奖励核对异常；次数 %s→%s（预期仅扣1次）；背包新增 %s；停止，不自动重试" % (remain, after_remain, gained or "无"))
            return False
        print("[十绝阵] %s分档领奖成功；次数 %s→%s；背包新增 %s" % (target_score, remain, after_remain, gained))
        return True
    except Exception as exc:
        print("[十绝阵] 单人联机流程失败:", exc)
        return False
    finally:
        if team:
            team.disconnect()
        if room_id:
            try:
                flow.request("room.waitingRoomHandler.exitWaitingRoom", {"roomId": room_id})
            except Exception:
                pass
