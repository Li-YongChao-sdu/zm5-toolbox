# -*- coding: utf-8 -*-
"""十绝阵三人组队：三个账号同房正常开局，各自提交三座位战果并各自领奖。

已验证结论（2026-10-31 真机）：
- 三个账号 createWaitingRoom/joinWaitingRoom 进同一房，全员
  changePlayerStatus(1) 准备后由房主 prepareCreateOnlineCopy，三端都收到
  onPrepareCreateOnlineCopy，各自 loadingProgress 5/50/100 后共享同一个
  onCreateOnlineCopy（同一 instId/ip/port）。
- battleExit 的 data 必须填满全部三个座位（每座 1000 分、uid 对应座位）；
  只填自己座位会回 code=500「战斗异常,结算失败!!」。
- 服务器给三人各推 onHaloResult(score=3000)，各自 getHaloReward 各扣 1 次
  奖励次数、各得一份 3000 分档奖励。
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import teacher_trial
from halo_solo import _bag_counts, _request
from pypomelo.client import PomeloClient

CREATE_ROOM = "room.waitingRoomHandler.createWaitingRoom"
JOIN_ROOM = "room.waitingRoomHandler.joinWaitingRoom"
CHANGE_STATUS = "room.waitingRoomHandler.changePlayerStatus"
PREPARE = "room.waitingRoomHandler.prepareCreateOnlineCopy"
LOADING = "room.waitingRoomHandler.loadingProgress"
EXIT_ROOM = "room.waitingRoomHandler.exitWaitingRoom"
GET_DUNGEON = "scene.haloHandler.getDungeonId"
GET_REWARD = "scene.copyHandler.getHaloReward"

TARGET_SCORE = 3000


def _halo_scalars(info):
    halo = info.get("halo") or {}
    return {str(k): v for k, v in halo.items() if isinstance(v, (int, float))}


def _gains(before, after):
    return {k: after[k] - before.get(k, 0)
            for k in after if after[k] > before.get(k, 0)}


def _brief(value, limit=300):
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]


def _load_account(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _dungeon_requirement(dungeon_id):
    path = HERE / "halo_requirements.json"
    if not path.exists():
        return 0
    try:
        limits = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(limits.get(str(dungeon_id), 0))


def run(accounts, target_score=TARGET_SCORE, claim="all", log=print, claim_flags=None):
    """三个账号同房正常开局并各自领奖；返回 True 表示三人全部结算并核对通过。

    accounts: 账号 dict 列表（含 uid/username/cookies/record_index），长度必须为 3。
    claim_flags: 逐账号领取标记（True=领、False=不领、保留次数）；None 时按 claim 决定。
    """
    if len(accounts) != 3:
        raise ValueError("十绝阵三人组队需要正好 3 个账号，当前 %s 个" % len(accounts))
    if int(target_score) != TARGET_SCORE:
        raise ValueError("三人正常开局只支持 3000 分档（每座 1000 分），当前 %s" % target_score)

    sessions = []
    teams = []
    room_id = None
    try:
        for account in accounts:
            slot = int(account.get("record_index") or 0)
            flow, info = teacher_trial.connect(account, slot)
            session = {"tag": account.get("username") or str(account.get("uid")),
                       "flow": flow, "info": info, "slot": slot,
                       "account": account}
            sessions.append(session)

        for session in sessions:
            fresh = teacher_trial.enter(session["flow"], session["slot"])
            session["info"].clear()
            session["info"].update(fresh)
            session["remain"] = int((fresh.get("halo") or {}).get("haloRewardCnt") or 0)
            session["bag"] = _bag_counts(fresh)
            session["halo"] = _halo_scalars(fresh)
            reply = session["flow"].request(GET_DUNGEON, {})
            session["did"] = int(reply.get("dungeonId") or 0)
            if not session["did"]:
                log("[十绝阵组队] %s 未取到关卡: %s" % (session["tag"], reply.get("error") or reply))
                return False
            log("[十绝阵组队] %s uid=%s 关卡=%s 奖励次数=%s 战力=%s"
                % (session["tag"], fresh.get("uid"), session["did"],
                   session["remain"], fresh.get("power")))

        short = [s["tag"] for s in sessions if s["remain"] <= 0]
        if short:
            log("[十绝阵组队] 奖励次数不足，三人房不成立，跳过: %s" % "、".join(short))
            return False
        if len({s["did"] for s in sessions}) != 1:
            log("[十绝阵组队] 三人的十绝阵关卡不一致，无法同房: %s"
                % {s["tag"]: s["did"] for s in sessions})
            return False
        required = _dungeon_requirement(sessions[0]["did"])
        low = [s["tag"] for s in sessions
               if required > 0 and float(s["info"].get("power") or 0) < required]
        if low:
            log("[十绝阵组队] 战力不足 %s，未建房、不消耗次数: %s" % (required, "、".join(low)))
            return False

        for session in sessions:
            session["online_evt"] = threading.Event()
            session["prepared_evt"] = threading.Event()
            session["halo_evt"] = threading.Event()

            def make(event, s=session):
                def callback(payload):
                    if not isinstance(payload, dict):
                        return
                    if event == "onCreateOnlineCopy":
                        if int(payload.get("copyType") or 0) == s["did"]:
                            s["online"] = payload
                            s["online_evt"].set()
                    elif event == "onPrepareCreateOnlineCopy":
                        s["prepared_evt"].set()
                    elif event == "onHaloResult":
                        s["halo_result"] = payload
                        s["halo_evt"].set()
                return callback

            for event in ("onCreateOnlineCopy", "onPrepareCreateOnlineCopy", "onHaloResult"):
                session["flow"].on(event, make(event))

        host, other1, other2 = sessions
        made = host["flow"].request(CREATE_ROOM, {"dungeonId": host["did"], "type": "halo"})
        room = made.get("room") or {}
        room_id = room.get("roomId")
        if made.get("code") != 200 or made.get("error") or not room_id:
            log("[十绝阵组队] 建房失败: %s" % _brief(made))
            return False
        log("[十绝阵组队] 建房 roomId=%s 座位=%s" % (room_id, room.get("seating")))
        for session in (other1, other2):
            joined = session["flow"].request(JOIN_ROOM, {"roomId": room_id})
            if joined.get("code") != 200 or joined.get("error"):
                log("[十绝阵组队] %s 加入失败: %s" % (session["tag"], _brief(joined)))
                return False
            log("[十绝阵组队] %s 已加入，座位=%s"
                % (session["tag"], (joined.get("room") or {}).get("seating")))

        for session in sessions:
            session["flow"].request(CHANGE_STATUS, {"roomId": room_id, "status": 1})
        time.sleep(2)
        prepared = host["flow"].request(PREPARE, {"roomId": room_id})
        if prepared.get("code") != 200 or prepared.get("error"):
            log("[十绝阵组队] 准备开局失败: %s" % _brief(prepared))
            return False
        for session in sessions:
            if not session["prepared_evt"].wait(15):
                log("[十绝阵组队] %s 未收到准备通知，继续加载" % session["tag"])
        for percent in (5, 50, 100):
            for session in sessions:
                session["flow"].game.notify(LOADING,
                                            {"roomId": room_id, "percent": percent, "version": 1})
            time.sleep(0.5)
        for session in sessions:
            if not session["online_evt"].wait(25):
                log("[十绝阵组队] %s 未收到战斗实例" % session["tag"])
                return False

        first = sessions[0]["online"]
        for session in sessions[1:]:
            for key in ("instId", "ip", "port"):
                if session["online"].get(key) != first.get(key):
                    log("[十绝阵组队] 实例 %s 不一致: %s vs %s"
                        % (key, session["online"].get(key), first.get(key)))
                    return False
        rows = [x for x in (first.get("playerInfos") or []) if isinstance(x, dict)]
        order = [str(row.get("uid") or row.get("playerId")) for row in rows]
        if set(order) != {str(s["info"].get("uid")) for s in sessions} or len(order) != 3:
            log("[十绝阵组队] 实例玩家与登录账号不一致: %s" % order)
            return False
        log("[十绝阵组队] 实例 instId=%s ip=%s port=%s 座位=%s"
            % (first.get("instId"), first.get("ip"), first.get("port"), order))

        for session in sessions:
            online = session["online"]
            team = PomeloClient()
            connected = threading.Event()
            team.connect(online["ip"], int(online["port"]), user={},
                         handshake_cb=lambda _: connected.set())
            if not connected.wait(12):
                team.disconnect()
                log("[十绝阵组队] %s 战斗服握手超时" % session["tag"])
                return False
            session["loaded"] = threading.Event()
            team.on("onAllLoadComplete", lambda _d, s=session: s["loaded"].set())
            uid = str(session["info"].get("uid"))
            entered = _request(team, "copy.copyHandler.enter", {
                "instId": online["instId"], "playerId": uid,
                "password": online.get("password"), "abnormalFrameNum": 0,
                "cg": online.get("cg") or "cg1"})
            if entered.get("code") != 200 or entered.get("error"):
                team.disconnect()
                log("[十绝阵组队] %s 进入战斗失败: %s" % (session["tag"], _brief(entered)))
                return False
            team.notify("copy.copyHandler.loadComplete", {})
            session["team"] = team
            teams.append(team)
        for session in sessions:
            if not session["loaded"].wait(30):
                log("[十绝阵组队] %s 未收到 onAllLoadComplete" % session["tag"])
                return False
        time.sleep(1)

        for session in sessions:
            uid = str(session["info"].get("uid"))
            seat = order.index(uid)
            data = [{"win": True, "uid": row_uid, "hp": 1000, "hpMax": 1000,
                     "frame": 0, "remainTime": 600, "time": 600,
                     "remainHpPercent": 1000, "score": 1000}
                    for row_uid in order]
            player_info = [{"playerId": row_uid, "hp": 1000, "isme": row_uid == uid,
                            "campId": 1, "dead": False, "exit": False, "from": ""}
                           for row_uid in order]
            finished = _request(session["team"], "copy.copyHandler.battleExit", {
                "battleResult": 5, "playerInfo": player_info, "data": data,
                "frameNum": 0})
            log("[十绝阵组队] %s 座位%s 提交战果: code=%s error=%s"
                % (session["tag"], seat, finished.get("code"), finished.get("error")))
            if finished.get("code") != 200 or finished.get("error"):
                log("[十绝阵组队] 结算失败: %s" % _brief(finished))
                return False
        for session in sessions:
            if not session["halo_evt"].wait(20):
                log("[十绝阵组队] %s 未收到 onHaloResult" % session["tag"])
                return False
            result = session["halo_result"]
            session["score"] = int(result.get("score") or 0)
            session["drops"] = result.get("drops")
            if result.get("code") != 200 or session["score"] < TARGET_SCORE:
                log("[十绝阵组队] %s 结算未达档: %s" % (session["tag"], _brief(result, 400)))
                return False
            log("[十绝阵组队] %s 服务器结算 score=%s drops=%s"
                % (session["tag"], session["score"], _brief(result.get("drops"), 400)))

        if claim_flags is not None:
            for session, flag in zip(sessions, claim_flags):
                session["claim"] = bool(flag)
        else:
            for session in sessions:
                session["claim"] = True if claim == "all" else session is sessions[0]
        for session in sessions:
            if not session["claim"]:
                log("[十绝阵组队] %s 不领奖，保留奖励次数" % session["tag"])
        for session in sessions:
            if not session["claim"]:
                continue
            reward = session["flow"].request(GET_REWARD, {})
            if reward.get("code") != 200 or reward.get("error"):
                log("[十绝阵组队] %s 领奖失败: %s" % (session["tag"], _brief(reward)))
                return False
        time.sleep(1)

        all_ok = True
        for session in sessions:
            fresh = teacher_trial.enter(session["flow"], session["slot"])
            after_remain = int((fresh.get("halo") or {}).get("haloRewardCnt", -1))
            gained = _gains(session["bag"], _bag_counts(fresh))
            halo_gained = _gains(session["halo"], _halo_scalars(fresh))
            if session["claim"]:
                ok = after_remain == session["remain"] - 1 and bool(gained)
            else:
                ok = after_remain == session["remain"] and not gained
            session.update(remain_after=after_remain, gained=gained,
                           halo_gained=halo_gained, ok=ok)
            decrease = session["remain"] - after_remain
            log("[十绝阵组队] %s（%s）奖励次数 %s→%s（本次减少 %s 次）背包新增 %s 十绝阵新增 %s %s"
                % (session["tag"], "领奖" if session["claim"] else "未领奖",
                   session["remain"], after_remain, decrease,
                   gained or "无", halo_gained or "无", "✓" if ok else "✗"))
            if not ok:
                all_ok = False
        return all_ok
    except Exception as exc:
        log("[十绝阵组队] 流程失败: %s" % exc)
        return False
    finally:
        for team in teams:
            try:
                team.disconnect()
            except Exception:
                pass
        if room_id:
            try:
                host["flow"].request(EXIT_ROOM, {"roomId": room_id})
            except Exception:
                pass
        for session in sessions:
            try:
                session["flow"].disconnect()
            except Exception:
                pass


def _apply_slots(accounts, text):
    """逐账号覆盖存档槽位；省略时沿用账号文件里的 record_index（缺省为0）。"""
    if not text:
        return
    parts = [x.strip() for x in text.split(",") if x.strip()]
    if len(parts) != len(accounts):
        raise SystemExit("--slots 个数必须与 --accounts 一致")
    for account, value in zip(accounts, parts):
        try:
            slot = int(value)
        except ValueError:
            raise SystemExit("存档槽位必须是整数: %s" % value)
        if not 0 <= slot <= 7:
            raise SystemExit("存档槽位须为 0～7")
        account["record_index"] = slot


def _apply_claim(accounts, text):
    """逐账号领取标记 1/0；省略时返回 None（沿用旧行为：三人全部领取）。"""
    if not text:
        return None
    parts = [x.strip() for x in text.split(",") if x.strip()]
    if len(parts) != len(accounts):
        raise SystemExit("--claim 个数必须与 --accounts 一致")
    flags = []
    for value in parts:
        if value not in ("0", "1"):
            raise SystemExit("--claim 只能填 1 或 0: %s" % value)
        flags.append(value == "1")
    return flags


def main():
    parser = argparse.ArgumentParser(description="十绝阵三人组队（正常开局，各领一份3000分档奖励）")
    parser.add_argument("--accounts", required=True,
                        help="三个账号名（accounts 目录下文件名，不含 .json），逗号分隔")
    parser.add_argument("--slots", default="",
                        help="逐账号存档槽位，如 6,0,1（顺序对应 --accounts；省略则用账号文件 record_index）")
    parser.add_argument("--claim", default="",
                        help="逐账号领取标记 1/0，如 1,0,1（顺序对应 --accounts；省略=全部领取）")
    parser.add_argument("--claim-main-only", action="store_true",
                        help="只让第一个账号领奖；副账号不领服务器奖励、保留奖励次数")
    args = parser.parse_args()
    names = [x.strip() for x in args.accounts.split(",") if x.strip()]
    accounts = []
    for name in names:
        path = HERE / "accounts" / (name + ".json")
        if not path.exists():
            raise SystemExit("找不到账号文件: %s" % path)
        accounts.append(_load_account(path))
    _apply_slots(accounts, args.slots)
    flags = _apply_claim(accounts, args.claim)
    for account, flag in zip(accounts, flags if flags is not None else [True] * len(accounts)):
        print("[十绝阵组队] %s 使用存档槽位 %s，%s"
              % (account.get("username") or account.get("uid"),
                 int(account.get("record_index") or 0),
                 "领奖" if flag else "不领奖"))
    ok = run(accounts, claim="main" if args.claim_main_only else "all", claim_flags=flags)
    print("[十绝阵组队] 结束: %s" % ("成功" if ok else "失败"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
