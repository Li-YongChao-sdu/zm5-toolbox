# -*- coding: utf-8 -*-
"""月卡（含超值月卡）自动领取模块（独立，不改动工具箱已有文件）。

路由（客户端 modules/monthCard 反编译确认）：
  领取：scene.activityHandler.getMonthCardReward  {}      —— 空参，服务器自己判断
  购买：scene.shopHandler.buyMonthCard            {id}    —— 本模块不使用

关键规则（实测确认）：
  1. 领取接口是【空参】，一次调用即结算，返回 give/reward；
  2. 服务器按【每个存档每天一次】限制 —— 当天已领过会返回
     code=500 "当天元宝已领取过"；
  3. 只有【生效中(expiredTime > serverTime)】的月卡才发每日元宝；
     已过期的卡即使 history 里没有今天，也不会发（实测豪华/至尊月卡被拒）；
  4. 客户端判断"今日是否已领"：monthCard[id].history 里是否有今天，
     日期 key 格式 = DateModelManager.getFullDate() = "YYYY/M/D"（月日不补零）。

配表 MonthCard.json（5 种卡）：
  id1 高级月卡  1000点券 / 每日150元宝 / monthType=1 / buffId=-1
  id2 豪华月卡  3000点券 / 每日300元宝 / monthType=1 / buffId=-1
  id3 超值月卡   100点券 / 每日 50元宝 / monthType=1 / buffId=-1
  id4 至尊月卡  6000点券 / 每日500元宝 / monthType=1 / buffId=-1
  id5 速通月卡(扫荡月卡) 3000点券 / 每日120元宝 / monthType=2 / buffId=999001

【速通月卡没有独立领取路由】—— 它和其它月卡完全共用：
  * 同一份数据：都挂在 entry.monthCard[id] 下（含 expiredTime / history）；
  * 同一条领取路由：scene.activityHandler.getMonthCardReward {}（空参，一次结算全部）。
  monthType 只在客户端用于【切页签 + 显示扫荡图标】（MonthCardModule.initConfigData 里
  按 tabbarIndex+1 != monthType 过滤），purchaseType="record" 在客户端没有任何分支使用。
  buffId=999001 -> BuffScene[999001]「速通精灵」(effectType=999, 12小时)。
  注意：客户端 BuffSceneManager.hasMonthCardBuff() 读的是【场景 buff 列表 vos 里
  是否存在 type==999 的条目】（BuffServerVo 由服务器下发），而不是直接读配表 buffId；
  配表 BuffScene[999001].type 恰好也是 999，两者一致。
  该 buff 提供【速通不消耗速通能量】的特权，与元宝领取无关，本模块不涉及。
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG_DIR = os.path.join(HERE, "feature_config")

ROUTE_GET_REWARD = "scene.activityHandler.getMonthCardReward"
ROUTE_BUY = "scene.shopHandler.buyMonthCard"

# 配表 id
SUPER_CARD_ID = 3          # 超值月卡
SWEEP_CARD_ID = 5          # 速通月卡（扫荡月卡）
SWEEP_BUFF_ID = 999001     # 速通精灵 buff（BuffScene）


def _load(config_dir, name):
    with open(os.path.join(config_dir, name), encoding="utf-8") as f:
        return json.load(f)


def load_cards(config_dir=DEFAULT_CONFIG_DIR):
    """MonthCard.json -> {id: {...}}。"""
    try:
        table = _load(config_dir, "MonthCard.json")
    except Exception:
        return {}
    out = {}
    for key, v in (table or {}).items():
        if not isinstance(v, dict):
            continue
        try:
            cid = int(v.get("id", key))
        except (TypeError, ValueError):
            continue
        out[cid] = {
            "id": cid,
            "name": v.get("name", ""),
            "price": v.get("count"),
            "dailyYuanbao": v.get("dailyYuanBao"),
            "totalYuanbao": v.get("returnTotalYuanBao"),
            "usefulLife": v.get("usefulLife"),
            "monthType": v.get("monthType"),
            "buffId": v.get("buffId"),
            "purchaseType": v.get("purchaseType"),
            # 扫荡月卡页签（monthType=2），带速通精灵特权
            "isSweepCard": cid == SWEEP_CARD_ID,
        }
    return out


def server_time(info):
    """服务器时间（毫秒）。取不到就退回本地时间。"""
    try:
        return int((info or {}).get("serverTime"))
    except (TypeError, ValueError):
        return int(time.time() * 1000)


def server_date(info):
    """按服务器时间算出的日期 (year, month, day)。"""
    return time.localtime(server_time(info) / 1000.0)[:3]


def today_key(info):
    """今日 history key，格式与客户端 DateModelManager.getFullDate() 一致：
    "YYYY/M/D"，月、日不补零。
    """
    y, m, d = server_date(info)
    return "%d/%d/%d" % (y, m, d)


def today_key_local():
    y, m, d = time.localtime()[:3]
    return "%d/%d/%d" % (y, m, d)


def cards_owned(info):
    """entry.monthCard -> {id: {expiredTime, history, days}}。"""
    raw = (info or {}).get("monthCard") or {}
    out = {}
    for key, v in (raw.items() if isinstance(raw, dict) else []):
        if not isinstance(v, dict):
            continue
        try:
            cid = int(key)
        except (TypeError, ValueError):
            continue
        hist = v.get("history") or {}
        out[cid] = {
            "id": cid,
            "expiredTime": v.get("expiredTime"),
            "history": hist if isinstance(hist, dict) else {},
            "days": len(hist) if isinstance(hist, dict) else 0,
        }
    return out


def is_active(card, info):
    """月卡是否生效中（expiredTime > 服务器当前时间）。"""
    try:
        exp = int(card.get("expiredTime") or 0)
    except (TypeError, ValueError):
        return False
    return exp > server_time(info)


def claim_state(info, cfg=None, config_dir=DEFAULT_CONFIG_DIR):
    """今日领取状态。

    返回 {
      "todayKey", "cards": {id: {...active, claimedToday}},
      "activeCards": [id...], "needClaim": bool,
      "canClaim": bool,   # 有生效中的卡且今天还没领
      "expiredUnclaimed": [id...],  # 已过期且今天没领的（服务器不会发）
    }
    """
    cfg = cfg or load_cards(config_dir)
    tk = today_key(info)
    owned = cards_owned(info)
    cards = {}
    active = []
    expired_unclaimed = []
    claimed_any_active = False
    for cid, card in owned.items():
        act = is_active(card, info)
        claimed = tk in card["history"]
        cards[cid] = {
            "id": cid,
            "name": (cfg.get(cid) or {}).get("name", str(cid)),
            "dailyYuanbao": (cfg.get(cid) or {}).get("dailyYuanbao"),
            "monthType": (cfg.get(cid) or {}).get("monthType"),
            "buffId": (cfg.get(cid) or {}).get("buffId"),
            "isSweepCard": cid == SWEEP_CARD_ID,
            "active": act,
            "claimedToday": claimed,
            "days": card["days"],
            "expiredTime": card.get("expiredTime"),
        }
        if act:
            active.append(cid)
            if claimed:
                claimed_any_active = True
        elif not claimed:
            expired_unclaimed.append(cid)
    return {
        "todayKey": tk,
        "cards": cards,
        "activeCards": sorted(active),
        "expiredUnclaimed": sorted(expired_unclaimed),
        "needClaim": bool(active) and not claimed_any_active,
        "canClaim": bool(active) and not claimed_any_active,
    }


def super_card_state(info, cfg=None, config_dir=DEFAULT_CONFIG_DIR):
    """超值月卡的专门状态（用户要的就是这一张）。"""
    st = claim_state(info, cfg, config_dir)
    node = st["cards"].get(SUPER_CARD_ID)
    return {
        "owned": node is not None,
        "active": bool(node and node["active"]),
        "claimedToday": bool(node and node["claimedToday"]),
        "todayKey": st["todayKey"],
        "card": node,
        "overallNeedClaim": st["needClaim"],
    }


def sweep_card_state(info, cfg=None, config_dir=DEFAULT_CONFIG_DIR):
    """速通月卡（扫荡月卡）状态。

    注意：它的元宝领取与其它月卡【完全共用】getMonthCardReward（空参），
    这里只是为了单独展示；它的额外特权是 BuffScene[999001]「速通精灵」。
    """
    st = claim_state(info, cfg, config_dir)
    node = st["cards"].get(SWEEP_CARD_ID)
    return {
        "owned": node is not None,
        "active": bool(node and node["active"]),
        "claimedToday": bool(node and node["claimedToday"]),
        "todayKey": st["todayKey"],
        "card": node,
        "overallNeedClaim": st["needClaim"],
        "buffId": SWEEP_BUFF_ID,
    }


def load_sweep_buff(config_dir=DEFAULT_CONFIG_DIR):
    """BuffScene[999001]「速通精灵」的说明（纯展示用）。"""
    try:
        table = _load(config_dir, "BuffScene.json")
    except Exception:
        return {}
    node = (table or {}).get(str(SWEEP_BUFF_ID))
    if not isinstance(node, dict):
        return {}
    return {
        "id": SWEEP_BUFF_ID,
        "name": node.get("name"),
        "describe": node.get("describe"),
        "effectType": node.get("effectType"),
        "continueTime": node.get("continueTime"),
    }
