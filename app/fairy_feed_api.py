# -*- coding: utf-8 -*-
"""幻兽灵魂喂养 协议层 API（独立，不改动工具箱已有文件）。

路由：scene.fairyHandler.upgrade
请求体：{"entityId": 幻兽entityId, "feedId": 幻兽当前level, "index": 出战角色编号0/1}
  * feedId 必须 = 幻兽当前 level，才会走"灵魂喂养"（配表 FairyFeed[level]）
  * feedId = 99999 时走妖元喂养
回包（客户端 FairyProxy.upgradeBack 用到）：
  addExp    本次加的经验
  critRate  有值表示暴击
  fairy     更新后的幻兽数据（含 level/exp）
  everyDaySetting  里面 feedDayNum_N 是今日已喂次数
  consume / give  消耗与获得
"""
import fairy_feed_data as ffd

ROUTE_UPGRADE = "scene.fairyHandler.upgrade"


def _ok(result):
    return isinstance(result, dict) and not result.get("error") \
        and result.get("code", 200) == 200


def _err(result):
    if isinstance(result, dict):
        return result.get("error") or result.get("msg") or result
    return result


def feed_once(flow, entity_id, feed_id, index=None):
    """喂养一次。feed_id 传幻兽当前 level（灵魂喂养）。返回服务器原始回包。"""
    args = {"entityId": str(entity_id), "feedId": int(feed_id)}
    if index is not None:
        args["index"] = int(index)
    r = flow.request(ROUTE_UPGRADE, args)
    if not _ok(r):
        raise RuntimeError("喂养失败: %s" % _err(r))
    return r


def fed_after(raw, index=None):
    """从回包里的 everyDaySetting 取今日已喂次数；拿不到返回 None。"""
    eds = (raw or {}).get("everyDaySetting")
    if not isinstance(eds, dict):
        return None
    key = "feedDayNum_%d" % (int(index) if index is not None else 0)
    if key in eds:
        try:
            return int(eds[key] or 0)
        except (TypeError, ValueError):
            return None
    return None


def fairy_after(raw):
    """回包里的幻兽最新数据 {level, exp, ...}；没有返回 None。"""
    node = (raw or {}).get("fairy")
    if isinstance(node, dict):
        return node
    return None


def add_exp(raw):
    """本次加的经验。"""
    try:
        return int((raw or {}).get("addExp") or 0)
    except (TypeError, ValueError):
        return 0


def is_crit(raw):
    """本次是否暴击（客户端就是判断 critRate 字段有没有值）。"""
    return bool((raw or {}).get("critRate"))


def consume_spirit(raw):
    """本次消耗的灵魂（回包 consume 里 type/subType == spirit 的那条）。"""
    for entry in (raw or {}).get("consume") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "spirit" or entry.get("subType") == "spirit":
            try:
                return int(entry.get("count") or 0)
            except (TypeError, ValueError):
                return 0
    return None


def feed_to_limit(flow, info, fairy, cfg=None, max_feeds=None,
                  progress=None, role=0):
    """把一只幻兽的"今日灵魂喂养次数"喂到上限。

    逐次发送（客户端也是这么循环的），每次成功后按新等级重算消耗。
    role: 0=主角色(index=0), 1=副角色(index=1)，两侧每日次数独立。
    停止条件：
      daily      今日次数用完（主要目标）
      level      幻兽等级已到角色等级
      spirit     灵魂不足
      rejected   服务器拒绝（回包 code != 200）
      safety     触发安全上限（防止意外死循环）

    返回 {"feeds","spiritCost","crits","addExp","levelFrom","levelTo",
          "stop","logs", "quota"}
    """
    cfg = cfg or ffd.FeedConfig()
    role = ffd.role_index(info, role)
    fairy = dict(fairy or {})
    level = int(fairy.get("level") or 1)
    start_level = level
    index = role
    quota = ffd.feed_quota(info, cfg, role)
    left = quota["left"]
    char_level = ffd.role_char_level(info, role)
    spirit = None
    try:
        spirit = int((info or {}).get("spirit") or 0)
    except (TypeError, ValueError):
        spirit = 0

    safety = max(200, left + 5)
    feeds = 0
    cost = 0
    crits = 0
    gained = 0
    logs = []
    stop = None

    while True:
        if left <= 0:
            stop = "daily"
            break
        if max_feeds and feeds >= int(max_feeds):
            stop = "times"
            break
        if char_level is not None and level >= char_level:
            stop = "level"
            break
        if feeds >= safety:
            stop = "safety"
            break
        tier = cfg.tier(level)
        if not tier:
            stop = "noConfig"
            break
        need = tier.get("consumeCount")
        try:
            need = int(need)
        except (TypeError, ValueError):
            stop = "badConfig"
            break
        if spirit is not None and spirit < need:
            stop = "spirit"
            break
        try:
            raw = feed_once(flow, fairy["entityId"], level, index)
        except Exception as e:
            logs.append("第%d次失败：%s" % (feeds + 1, e))
            stop = "rejected"
            break

        feeds += 1
        cost += need
        if spirit is not None:
            spirit -= need
        add = add_exp(raw)
        gained += add
        if is_crit(raw):
            crits += 1
        node = fairy_after(raw)
        if isinstance(node, dict) and node.get("level") is not None:
            try:
                level = int(node["level"])
            except (TypeError, ValueError):
                pass
        used = fed_after(raw, index)
        if used is not None:
            # 以服务器计数为准，永远不越过当日上限
            quota["used"] = used
            left = max(0, quota["total"] - used)
        else:
            # 回包未带计数时，只扣减本次已确认成功的次数。
            quota["used"] += 1
            left = max(0, quota["total"] - quota["used"])
        quota["left"] = left
        logs.append("第%d次：+%s经验%s，幻兽 Lv%d，今日已喂 %s/%s"
                    % (feeds, add, "（暴击）" if is_crit(raw) else "",
                       level,
                       (quota["total"] - left) if used is None else used,
                       quota["total"]))
        if progress:
            progress(logs[-1])

    return {
        "feeds": feeds, "spiritCost": cost, "crits": crits, "addExp": gained,
        "levelFrom": start_level, "levelTo": level, "stop": stop,
        "logs": logs, "quota": quota,
        "spiritLeft": spirit,
    }


STOP_TEXT = {
    "daily": "今日灵魂喂养次数已用满",
    "times": "已喂满指定次数",
    "level": "幻兽等级已到角色等级上限",
    "spirit": "灵魂不足",
    "rejected": "服务器拒绝",
    "safety": "触发安全上限，已停止",
    "noConfig": "配表缺少该等级档位",
    "badConfig": "配表数据异常",
}
