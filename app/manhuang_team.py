# -*- coding: utf-8 -*-
"""多人蛮荒（dungeon3）：2~3 个账号同房正常开局，各自结算并各自领共享宝箱。

已验证结论（2026-10-31 真机）：
- 房间 type="dungeon3"，副本 id 为 1400101+（1400100 只是共享宝箱 id）。
- 服务器只给 3 个座位，第 4 人加入返回「房间人数已满」；2 人房同样能开局。
- 每人 battleExit 提交 battleResult=4 / bossHp=0 / playerInfo=[] / data=[]。
- 结算后每人各自 getDungeonTreasureDrop + getDungeonTreasureReward，
  各得 2~3 件材料、各自扣 1 次宝箱次数；2 人房与 3 人房每人掉落一致。
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
TREASURE_ID = "1400100"
DROP = "scene.copyHandler.getDungeonTreasureDrop"
REWARD = "scene.copyHandler.getDungeonTreasureReward"


def _brief(value, limit=300):
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]


def _gains(before, after):
    return {k: after[k] - before.get(k, 0)
            for k in after if after[k] > before.get(k, 0)}


def _unlocked_mids(info):
    dungeon = info.get("dungeon") or {}
    out = {}
    for key, rec in dungeon.items():
        try:
            mid = int(key)
        except (TypeError, ValueError):
            continue
        if not str(mid).startswith("140") or mid == int(TREASURE_ID):
            continue
        if isinstance(rec, dict) and int(rec.get("passNum") or 0) > 0:
            out[mid] = int(rec.get("passNum") or 0)
    return out


def _common_mid(sessions):
    sets = [set(s["unlocked"]) for s in sessions]
    common = set.intersection(*sets) if sets else set()
    if not common:
        return 0
    return max(common)


def run(accounts, mid=0, log=print, claim_flags=None):
    """2~3 个账号同房正常开局，各自领取共享宝箱；返回 True 表示全部核对通过。

    claim_flags: 逐账号领取标记（True=领、False=不领、保留宝箱次数）；None 时全部领取。
    """
    if not 2 <= len(accounts) <= 3:
        raise ValueError("多人蛮荒需要 2~3 个账号，当前 %s 个" % len(accounts))

    sessions = []
    teams = []
    room_id = None
    try:
        for account in accounts:
            slot = int(account.get("record_index") or 0)
            flow, info = teacher_trial.connect(account, slot)
            sessions.append({"tag": account.get("username") or str(account.get("uid")),
                             "flow": flow, "info": info, "slot": slot,
                             "account": account})
        for session in sessions:
            fresh = teacher_trial.enter(session["flow"], session["slot"])
            session["info"].clear()
            session["info"].update(fresh)
            session["unlocked"] = _unlocked_mids(fresh)
            rec = (fresh.get("dungeonTreasure") or {}).get(TREASURE_ID) or {}
            session["remain"] = int(rec.get("remainCnt") or 0)
            session["bag"] = _bag_counts(fresh)
            log("[蛮荒组队] %s uid=%s 宝箱次数=%s 已解锁=%s 战力=%s"
                % (session["tag"], fresh.get("uid"), session["remain"],
                   sorted(session["unlocked"])[-3:] or "无", fresh.get("power")))

        target = int(mid or 0) or _common_mid(sessions)
        if not target:
            log("[蛮荒组队] 没有三人共同已解锁的蛮荒关卡，不建房")
            return False
        missing = [s["tag"] for s in sessions if target not in s["unlocked"]]
        if missing:
            log("[蛮荒组队] 关卡 %s 未解锁: %s，不建房" % (target, "、".join(missing)))
            return False
        short = [s["tag"] for s in sessions if s["remain"] <= 0]
        if short:
            log("[蛮荒组队] 宝箱次数不足，跳过: %s" % "、".join(short))
            return False
        log("[蛮荒组队] 使用关卡 %s，%s 人房" % (target, len(sessions)))

        for session in sessions:
            session["online_evt"] = threading.Event()
            session["prepared_evt"] = threading.Event()

            def make(event, s=session):
                def callback(payload):
                    if not isinstance(payload, dict):
                        return
                    if event == "onCreateOnlineCopy":
                        if int(payload.get("copyType") or 0) == target:
                            s["online"] = payload
                            s["online_evt"].set()
                    elif event == "onPrepareCreateOnlineCopy":
                        s["prepared_evt"].set()
                return callback

            for event in ("onCreateOnlineCopy", "onPrepareCreateOnlineCopy"):
                session["flow"].on(event, make(event))

        host = sessions[0]
        made = host["flow"].request(CREATE_ROOM, {"dungeonId": target, "type": "dungeon3"})
        room = made.get("room") or {}
        room_id = room.get("roomId")
        if made.get("code") != 200 or made.get("error") or not room_id:
            log("[蛮荒组队] 建房失败: %s" % _brief(made))
            return False
        log("[蛮荒组队] 建房 roomId=%s 座位=%s" % (room_id, room.get("seating")))
        for session in sessions[1:]:
            joined = session["flow"].request(JOIN_ROOM, {"roomId": room_id})
            if joined.get("code") != 200 or joined.get("error"):
                log("[蛮荒组队] %s 加入失败: %s" % (session["tag"], _brief(joined)))
                return False
            log("[蛮荒组队] %s 已加入，座位=%s"
                % (session["tag"], (joined.get("room") or {}).get("seating")))

        for session in sessions:
            session["flow"].request(CHANGE_STATUS, {"roomId": room_id, "status": 1})
        time.sleep(2)
        prepared = host["flow"].request(PREPARE, {"roomId": room_id})
        if prepared.get("code") != 200 or prepared.get("error"):
            log("[蛮荒组队] 准备开局失败: %s" % _brief(prepared))
            return False
        for session in sessions:
            if not session["prepared_evt"].wait(15):
                log("[蛮荒组队] %s 未收到准备通知，继续加载" % session["tag"])
        for percent in (5, 50, 100):
            for session in sessions:
                session["flow"].game.notify(LOADING,
                                            {"roomId": room_id, "percent": percent, "version": 1})
            time.sleep(0.5)
        for session in sessions:
            if not session["online_evt"].wait(30):
                log("[蛮荒组队] %s 未收到战斗实例" % session["tag"])
                return False

        first = sessions[0]["online"]
        for session in sessions[1:]:
            for key in ("instId", "ip", "port"):
                if session["online"].get(key) != first.get(key):
                    log("[蛮荒组队] 实例 %s 不一致: %s vs %s"
                        % (key, session["online"].get(key), first.get(key)))
                    return False
        rows = [x for x in (first.get("playerInfos") or []) if isinstance(x, dict)]
        order = [str(row.get("uid") or row.get("playerId")) for row in rows]
        if set(order) != {str(s["info"].get("uid")) for s in sessions} or len(order) != len(sessions):
            log("[蛮荒组队] 实例玩家与登录账号不一致: %s" % order)
            return False
        log("[蛮荒组队] 实例 instId=%s ip=%s port=%s 玩家=%s"
            % (first.get("instId"), first.get("ip"), first.get("port"), order))

        for session in sessions:
            online = session["online"]
            team = PomeloClient()
            connected = threading.Event()
            team.connect(online["ip"], int(online["port"]), user={},
                         handshake_cb=lambda _: connected.set())
            if not connected.wait(12):
                team.disconnect()
                log("[蛮荒组队] %s 战斗服握手超时" % session["tag"])
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
                log("[蛮荒组队] %s 进入战斗失败: %s" % (session["tag"], _brief(entered)))
                return False
            team.notify("copy.copyHandler.loadComplete", {})
            session["team"] = team
            teams.append(team)
        for session in sessions:
            if not session["loaded"].wait(30):
                log("[蛮荒组队] %s 未收到 onAllLoadComplete" % session["tag"])
                return False
        time.sleep(2)

        for session in sessions:
            finished = _request(session["team"], "copy.copyHandler.battleExit", {
                "battleResult": 4, "playerInfo": [], "data": [],
                "frameNum": 0, "bossHp": 0})
            log("[蛮荒组队] %s 结算: code=%s error=%s"
                % (session["tag"], finished.get("code"), finished.get("error")))
            if finished.get("code") != 200 or finished.get("error"):
                log("[蛮荒组队] 结算失败: %s" % _brief(finished))
                return False
        time.sleep(3)

        all_ok = True
        for index, session in enumerate(sessions):
            session["claim"] = True if claim_flags is None else bool(claim_flags[index])
            session["chest"] = {}
            if not session["claim"]:
                log("[蛮荒组队] %s 不领取宝箱，保留次数" % session["tag"])
                continue
            cd = session["flow"].request(DROP, {})
            drops = cd.get("drop") or [] if isinstance(cd, dict) else []
            if cd.get("code") != 200 or cd.get("error"):
                log("[蛮荒组队] %s 查询宝箱失败: %s" % (session["tag"], _brief(cd)))
                all_ok = False
                continue
            for index, drop in enumerate(drops):
                if not isinstance(drop, dict):
                    continue
                drop_index = drop.get("dropIndex", index)
                got = session["flow"].request(REWARD, {"i": drop_index})
                if got.get("code") != 200 or got.get("error"):
                    log("[蛮荒组队] %s 领取宝箱 i=%s 失败: %s"
                        % (session["tag"], drop_index, _brief(got)))
                    all_ok = False
                    continue
                give = got.get("give") or []
                if isinstance(give, dict):
                    give = [give]
                for row in give:
                    if isinstance(row, dict):
                        key = str(row.get("subType"))
                        session["chest"][key] = session["chest"].get(key, 0) + int(row.get("count") or 0)
            log("[蛮荒组队] %s 宝箱掉落 %s 件，领取 %s"
                % (session["tag"], len(drops), session["chest"] or "无"))

        for session in sessions:
            fresh = teacher_trial.enter(session["flow"], session["slot"])
            rec = (fresh.get("dungeonTreasure") or {}).get(TREASURE_ID) or {}
            after_remain = int(rec.get("remainCnt", -1))
            gained = _gains(session["bag"], _bag_counts(fresh))
            if session["claim"]:
                ok = (after_remain == session["remain"] - 1 and bool(gained)
                      and bool(session["chest"]))
            else:
                ok = after_remain == session["remain"] and not gained
            session.update(remain_after=after_remain, gained=gained, ok=ok)
            decrease = session["remain"] - after_remain
            log("[蛮荒组队] %s（%s）宝箱次数 %s→%s（本次减少 %s 次）背包新增 %s %s"
                % (session["tag"], "领取" if session["claim"] else "未领取",
                   session["remain"], after_remain, decrease,
                   gained or "无", "✓" if ok else "✗"))
            if not ok:
                all_ok = False
        return all_ok
    except Exception as exc:
        log("[蛮荒组队] 流程失败: %s" % exc)
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
    """逐账号领取标记 1/0；省略时返回 None（沿用旧行为：全部领取）。"""
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
    parser = argparse.ArgumentParser(description="多人蛮荒（2~3 个账号正常开局，各自领宝箱）")
    parser.add_argument("--accounts", required=True,
                        help="2~3 个账号名（accounts 目录下文件名），逗号分隔")
    parser.add_argument("--slots", default="",
                        help="逐账号存档槽位，如 6,0,1（顺序对应 --accounts；省略则用账号文件 record_index）")
    parser.add_argument("--claim", default="",
                        help="逐账号领取标记 1/0，如 1,0,1（顺序对应 --accounts；省略=全部领取）")
    parser.add_argument("--mid", type=int, default=0,
                        help="副本 id（0=自动选三人共同已解锁的最高关）")
    args = parser.parse_args()
    names = [x.strip() for x in args.accounts.split(",") if x.strip()]
    accounts = []
    for name in names:
        path = HERE / "accounts" / (name + ".json")
        if not path.exists():
            raise SystemExit("找不到账号文件: %s" % path)
        accounts.append(json.loads(path.read_text(encoding="utf-8-sig")))
    _apply_slots(accounts, args.slots)
    flags = _apply_claim(accounts, args.claim)
    for account, flag in zip(accounts, flags if flags is not None else [True] * len(accounts)):
        print("[蛮荒组队] %s 使用存档槽位 %s，%s"
              % (account.get("username") or account.get("uid"),
                 int(account.get("record_index") or 0),
                 "领取宝箱" if flag else "不领取宝箱"))
    
    ok = run(accounts, mid=args.mid, claim_flags=flags)
    print("[蛮荒组队] 结束: %s" % ("成功" if ok else "失败"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
