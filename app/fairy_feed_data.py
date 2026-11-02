# -*- coding: utf-8 -*-
"""幻兽灵魂喂养 数据整理模块（独立，不改动工具箱已有文件）。

玩法（客户端 modules/fairy 反编译源码确认）：
  幻兽"喂养"= 用灵魂换经验升级，路由 scene.fairyHandler.upgrade，
  请求体 {"entityId":某只幻兽, "feedId":该幻兽当前level, "index":出战角色编号0/1}。
    feedId > 0  -> 灵魂喂养（配表 FairyFeed[level]）
    feedId = 99999 -> 妖元喂养（配表 FairyFeed[99999]，消耗妖元不消耗灵魂）

规则（均为客户端逻辑复刻）：
  1. 每日灵魂喂养次数：FairyFeed[level].getFeedDayNum() + VIP.freeFairyFeedNum
     —— getFeedDayNum() 在活动期间取 feedDayNum_Activity，否则 feedDayNum（默认 10）。
  2. 次数计数器是 everyDaySetting["feedDayNum_" + index]，按【幻兽所在角色】计：
     背包和主角色身上 -> feedDayNum_0；副角色身上 -> feedDayNum_1。
     实测服务器不校验请求里的 index，同一角色下的幻兽共用该角色那份每日次数。
  3. 单次消耗灵魂 = FairyFeed[level].consume_count（随等级变化）。
  4. 单次加经验 = FairyFeed[level].fairyExpAdd，critRate=0.1 时有暴击（多倍）。
  5. 幻兽等级不能超过角色等级（客户端 isUpgarde）。
  6. 喂满一只要客户端循环发请求，每次成功后按新等级重新取消耗。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG_DIR = os.path.join(HERE, "feature_config")

# 妖元喂养的伪 level（配表 id）
ITEM_FEED_ID = 99999

FALLBACK_FEED_DAY_NUM = 10


def _load(config_dir, name):
    with open(os.path.join(config_dir, name), encoding="utf-8") as f:
        return json.load(f)


def load_feed_tiers(config_dir=DEFAULT_CONFIG_DIR):
    """FairyFeed.json -> {level: {...}}（含 99999 妖元档）。"""
    try:
        table = _load(config_dir, "FairyFeed.json")
    except Exception:
        return {}
    out = {}
    for key, v in (table or {}).items():
        if not isinstance(v, dict):
            continue
        try:
            level = int(v.get("id", key))
        except (TypeError, ValueError):
            continue
        out[level] = {
            "level": level,
            "consumeType": v.get("consume_type"),
            "consumeSubType": v.get("consume_subType"),
            "consumeCount": v.get("consume_count"),
            "feedDayNum": v.get("feedDayNum", FALLBACK_FEED_DAY_NUM),
            "feedDayNumActivity": v.get("feedDayNum_Activity"),
            "fairyExpAdd": v.get("fairyExpAdd"),
            "fairyExpAddRate": v.get("fairyExpAddRate"),
            "critRate": v.get("critRate"),
            "activityId": v.get("activityId"),
        }
    return out


def load_fairy_exp(config_dir=DEFAULT_CONFIG_DIR):
    """FairyExp.json -> {level: 升到下一级需要的经验}。"""
    try:
        table = _load(config_dir, "FairyExp.json")
    except Exception:
        return {}
    out = {}
    for key, v in (table or {}).items():
        if not isinstance(v, dict):
            continue
        try:
            level = int(v.get("id", key))
        except (TypeError, ValueError):
            continue
        out[level] = v.get("fairyExp")
    return out


def load_vip_bonus(config_dir=DEFAULT_CONFIG_DIR):
    """VIP.json -> {vipLevel: freeFairyFeedNum}。"""
    try:
        table = _load(config_dir, "VIP.json")
    except Exception:
        return {}
    out = {}
    for key, v in (table or {}).items():
        if not isinstance(v, dict):
            continue
        try:
            level = int(v.get("id", key))
        except (TypeError, ValueError):
            continue
        if v.get("freeFairyFeedNum") is not None:
            try:
                out[level] = int(v["freeFairyFeedNum"])
            except (TypeError, ValueError):
                pass
    return out


class FeedConfig(object):
    """喂养相关的配表集合。"""

    def __init__(self, config_dir=DEFAULT_CONFIG_DIR):
        self.config_dir = config_dir
        self.tiers = load_feed_tiers(config_dir)
        self.fairy_exp = load_fairy_exp(config_dir)
        self.vip_bonus = load_vip_bonus(config_dir)

    def tier(self, level):
        """取某等级的灵魂喂养档；没有就退回最近的一档（配表只到 200 级）。"""
        if level in self.tiers:
            return self.tiers[level]
        keys = sorted(k for k in self.tiers if k != ITEM_FEED_ID)
        if not keys:
            return None
        if level > keys[-1]:
            return self.tiers[keys[-1]]
        for k in keys:
            if k >= level:
                return self.tiers[k]
        return self.tiers[keys[-1]]

    def item_tier(self):
        return self.tiers.get(ITEM_FEED_ID)

    def exp_need(self, level):
        """升到下一级需要的经验（没配表就返回 None）。"""
        if level in self.fairy_exp:
            return self.fairy_exp[level]
        keys = sorted(self.fairy_exp)
        if not keys:
            return None
        if level > keys[-1]:
            return self.fairy_exp[keys[-1]]
        for k in keys:
            if k >= level:
                return self.fairy_exp[k]
        return self.fairy_exp[keys[-1]]

    def vip_free_feed(self, vip_level):
        try:
            return int(self.vip_bonus.get(int(vip_level), 0))
        except (TypeError, ValueError):
            return 0


# ---------- 幻兽 / 玩家状态 ----------

def list_fairies(info):
    """背包幻兽 + 身上出战幻兽(p1/p2.equipments.fairy)。

    返回 [{entityId,id,name,level,exp,step,expNeed,source,role}]，按等级降序。
    role: None=背包, 0=主角色身上, 1=副角色身上。
    """
    cfg = FeedConfig()
    bag = ((info or {}).get("bag") or {}).get("fairy") or {}
    candidates = []
    if isinstance(bag, dict):
        candidates = [(node, "背包", None) for node in bag.values()]
    elif isinstance(bag, list):
        candidates = [(node, "背包", None) for node in bag]
    for role, key in enumerate(("p1", "p2")):
        body = (((info or {}).get(key) or {}).get("equipments") or {}).get("fairy")
        if isinstance(body, dict):
            candidates.append((body, "主角色身上" if role == 0 else "副角色身上", role))
    rows, seen = [], set()
    for node, source, role in candidates:
        if not isinstance(node, dict):
            continue
        entity_id = node.get("entityId")
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        try:
            level = int(node.get("level") or 1)
        except (TypeError, ValueError):
            level = 1
        rows.append({
            "entityId": entity_id,
            "id": node.get("id"),
            "name": node.get("name") or node.get("nickName") or "",
            "level": level,
            "exp": node.get("exp"),
            "step": node.get("step"),
            "expNeed": cfg.exp_need(level),
            "source": source,
            "role": role,
        })
    rows.sort(key=lambda r: (-r["level"], str(r["entityId"])))
    return rows


def feedable_fairies(info, role=0):
    """按幻兽归属算可喂范围：背包/p1身上走主角色，只有p2身上走副角色。

    实测：服务器不看请求里的 index，只按幻兽在哪位角色身上计次；
    背包幻兽即使带 index=1 也记到 feedDayNum_0。
    """
    role = role_index(info, role)
    if role == 1:
        return [f for f in list_fairies(info) if f["role"] == 1]
    return [f for f in list_fairies(info) if f["role"] in (None, 0)]


def pick_fairy(info, entity_id=None, name=None, ordinal=None, role=0):
    """按 entityId / 名字 / 序号选一只幻兽。序号 1 起（按等级降序）。"""
    role = role_index(info, role)
    fairies = feedable_fairies(info, role)
    if not fairies:
        return None, ("%s身上没有幻兽"
                      % ("主角色" if role == 0 else "副角色"))
    if entity_id:
        for f in fairies:
            if f["entityId"] == entity_id:
                return f, ""
        return None, "找不到 entityId=%s 的幻兽" % entity_id
    if name:
        hits = [f for f in fairies if name in (f["name"] or "")]
        if not hits:
            return None, "找不到名字含 %r 的幻兽" % name
        if len(hits) > 1:
            return None, ("名字含 %r 的幻兽有 %d 只，请用 --entity 指定：%s"
                          % (name, len(hits),
                             "、".join(f["entityId"] for f in hits)))
        return hits[0], ""
    if ordinal:
        try:
            idx = int(ordinal)
        except (TypeError, ValueError):
            return None, "序号必须是数字"
        if 1 <= idx <= len(fairies):
            return fairies[idx - 1], ""
        return None, "序号 %d 超出范围（1-%d）" % (idx, len(fairies))
    return fairies[0], ""


def role_index(info, role=None):
    """喂养使用的出战角色编号0(主角色)/1(副角色)；info.index是存档槽位，不能用于此路由。"""
    if role is None:
        return 0
    try:
        role = int(role)
    except (TypeError, ValueError):
        raise ValueError("角色编号须为0(主角色)或1(副角色)")
    if role not in (0, 1):
        raise ValueError("角色编号须为0(主角色)或1(副角色)")
    return role


def role_char_level(info, role=None):
    """该出战角色的等级（幻兽喂养等级上限）。"""
    role = role_index(info, role)
    key = "p1" if role == 0 else "p2"
    try:
        return int(((info or {}).get(key) or {}).get("level"))
    except (TypeError, ValueError):
        return None


def feed_used(info, index=None):
    """今日已用灵魂喂养次数（everyDaySetting.feedDayNum_{index}）。"""
    if index is None:
        index = role_index(info)
    eds = (info or {}).get("everyDaySetting") or {}
    try:
        return int(eds.get("feedDayNum_%d" % index) or 0)
    except (TypeError, ValueError):
        return 0


def feed_quota(info, cfg=None, role=None):
    """今日灵魂喂养配额（按出战角色独立）。返回 {used,total,left,base,vipBonus,index}。"""
    cfg = cfg or FeedConfig()
    index = role_index(info, role)
    fairies = list_fairies(info)
    level = fairies[0]["level"] if fairies else 1
    tier = cfg.tier(level)
    base = int((tier or {}).get("feedDayNum") or FALLBACK_FEED_DAY_NUM)
    try:
        vip_level = int(((info or {}).get("vip") or {}).get("level") or 0)
    except (TypeError, ValueError):
        vip_level = 0
    bonus = cfg.vip_free_feed(vip_level)
    total = base + bonus
    used = feed_used(info, index)
    return {
        "index": index,
        "used": used,
        "total": total,
        "left": max(0, total - used),
        "base": base,
        "vipBonus": bonus,
        "vipLevel": vip_level,
    }


def plan_feeds(info, fairy, cfg=None, spirit=None, role=None):
    """算出"喂满"这只幻兽需要多少次、花多少灵魂、卡在哪。

    按客户端循环逐次模拟：每喂一次，等级可能上升 -> 消耗与经验需求都变。
    返回 {feeds, spiritCost, levelFrom, levelTo, stops, affordable}
      stops: 停止原因列表，如 ["daily"] / ["level"] / ["spirit"] / ["expTable"]
    """
    cfg = cfg or FeedConfig()
    role = role_index(info, role)
    fairy = dict(fairy or {})
    level = int(fairy.get("level") or 1)
    exp = fairy.get("exp")
    try:
        exp = int(exp or 0)
    except (TypeError, ValueError):
        exp = 0
    if spirit is None:
        try:
            spirit = int((info or {}).get("spirit") or 0)
        except (TypeError, ValueError):
            spirit = 0
    char_level = role_char_level(info, role)

    quota = feed_quota(info, cfg, role)
    left = quota["left"]

    feeds = 0
    cost = 0
    stops = []
    start_level = level

    while True:
        if left <= 0:
            stops.append("daily")
            break
        if char_level is not None and level >= char_level:
            stops.append("level")
            break
        tier = cfg.tier(level)
        if not tier:
            stops.append("noConfig")
            break
        need = tier.get("consumeCount")
        try:
            need = int(need)
        except (TypeError, ValueError):
            stops.append("badConfig")
            break
        if spirit < need:
            stops.append("spirit")
            break
        exp_need = cfg.exp_need(level)
        if exp_need is None:
            stops.append("expTable")
            break
        add = tier.get("fairyExpAdd")
        try:
            add = int(add or 0)
        except (TypeError, ValueError):
            add = 0
        if add <= 0:
            stops.append("badConfig")
            break

        spirit -= need
        cost += need
        feeds += 1
        left -= 1
        exp += add
        # 可能连升多级
        guard = 0
        while exp >= exp_need and guard < 1000:
            exp -= exp_need
            level += 1
            guard += 1
            if char_level is not None and level >= char_level:
                break
            exp_need = cfg.exp_need(level)
            if exp_need is None:
                break
    return {
        "feeds": feeds,
        "spiritCost": cost,
        "levelFrom": start_level,
        "levelTo": level,
        "stops": stops,
        "quota": quota,
    }


if __name__ == "__main__":
    cfg = FeedConfig()
    print("灵魂喂养档位数:", len([k for k in cfg.tiers if k != ITEM_FEED_ID]))
    print("妖元档 99999:", json.dumps(cfg.item_tier(), ensure_ascii=False))
    print("VIP 免费喂养加成:", cfg.vip_free_feed(0), cfg.vip_free_feed(2), cfg.vip_free_feed(3))
    print("\n各等级灵魂消耗 / 经验/次 / 每日次数:")
    for lv in (1, 10, 20, 30, 40, 54, 60, 80, 100, 134, 150, 200):
        t = cfg.tier(lv)
        if t:
            print("  level %-4d 灵魂%-10s +经验%-4s 每日次数%-4s 暴击率%s expNeed=%s"
                  % (lv, t["consumeCount"], t["fairyExpAdd"], t["feedDayNum"],
                     t["critRate"], cfg.exp_need(lv)))
