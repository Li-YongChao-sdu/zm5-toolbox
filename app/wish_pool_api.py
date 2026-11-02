# -*- coding: utf-8 -*-
"""许愿池 协议层 API（独立模块，不改动工具箱已有文件）。

路由（scene.activityHandler）：
  getWishPoolInfo  {}            取本期/上期许愿池（20 个许愿格子）
  wish             {"wishId":id} 在某格子许愿（服务器按次递增扣灵魂）
  getWishReward    {}            领取上一期奖励（中奖拿 reward，未中拿 base 保底）

显示规则（已 live 实测验证）：
  服务器 cur/last 是以 pos 为键的 20 个格子，每格 id 指向 Wish.json 物品：
    无阵营 pos: 1明目 2清心 3彻悟 4无量
    阵营   pos: 十位=camp(1-4)，个位= 1因缘 2善果 3轮回 4圆满
  始终只显示 彻悟(3)/无量(4)；有阵营时加 轮回(x3)/圆满(x4) 且十位=我的camp。
"""
import json
import os

import wish_pool_data as wpd

HERE = os.path.dirname(os.path.abspath(__file__))

ROUTE_GET_INFO = "scene.activityHandler.getWishPoolInfo"
ROUTE_WISH = "scene.activityHandler.wish"
ROUTE_GET_REWARD = "scene.activityHandler.getWishReward"

# id 前缀 -> 池名
PREFIX_POOL = {
    "1010": "明目池", "1020": "清心池", "1030": "彻悟池", "1040": "无量池",
    "1051": "因缘池", "1061": "善果池", "1071": "轮回池", "1081": "圆满池",
}
# 需要显示的池
WORLD_POOLS = {"彻悟池", "无量池"}
CAMP_POOLS = {"轮回池", "圆满池"}


def _ok(result):
    return isinstance(result, dict) and not result.get("error") \
        and result.get("code", 200) == 200


def _err(result):
    if isinstance(result, dict):
        return result.get("error") or result.get("msg") or result
    return result


def build_item_index(stages):
    """把 wish_pool_data 的结构拍平成 id->物品详情。"""
    idx = {}
    for item in stages["world"].values():
        for it in item:
            idx[it["id"]] = it
    for pool in stages["camp"].values():
        for rows in pool.values():
            for it in rows:
                idx[it["id"]] = it
    return idx


def get_my_camp(entry_info):
    """从 entry info 取我的阵营与是否有联盟。返回 (camp, has_union, league)。"""
    league = entry_info.get("league") or {}
    camp = int(league.get("camp") or 0)
    has_union = bool(league.get("leagueId"))
    return camp, has_union, league


def pool_of_id(wish_id):
    return PREFIX_POOL.get(str(wish_id)[:4], "未知池")


def decorate_cell(pos, cell, item_index):
    """给一个服务器格子附上池名/奖励/消耗等详情。"""
    wish_id = int(cell["id"])
    item = item_index.get(wish_id, {})
    return {
        "pos": int(pos),
        "wishId": wish_id,
        "pool": pool_of_id(wish_id),
        "poscnt": int(cell.get("poscnt") or 0),
        "rewardUsers": cell.get("reward") or [],
        "bakUsers": cell.get("bak") or [],
        "rewardUser": cell.get("rewardUser") or {},
        "item": item,
    }


def select_visible_cells(period, my_camp, item_index):
    """从一期的 20 格中筛出要显示的格子（彻悟/无量；有阵营加轮回/圆满）。"""
    out = []
    for pos, cell in period.items():
        d = decorate_cell(pos, cell, item_index)
        pool = d["pool"]
        if pool in WORLD_POOLS:
            out.append(d)
        elif pool in CAMP_POOLS and my_camp and d["pos"] // 10 == my_camp:
            out.append(d)
    out.sort(key=lambda x: x["pos"])
    return out


def get_pool_info(flow):
    """请求许愿池信息，返回原始 dict（含 code/curKey/lastKey/cur/last）。"""
    r = flow.request(ROUTE_GET_INFO, {})
    if not _ok(r):
        raise RuntimeError("getWishPoolInfo 失败: %s" % _err(r))
    return r


def do_wish(flow, wish_id):
    """在指定格子许愿，返回服务器结果（含 wishData、everyWeekSetting、消耗）。"""
    r = flow.request(ROUTE_WISH, {"wishId": int(wish_id)})
    if not _ok(r):
        raise RuntimeError("许愿失败: %s" % _err(r))
    return r


def claim_prev_reward(flow):
    """领取上一期奖励（空参，服务器按上期记录结算）。"""
    r = flow.request(ROUTE_GET_REWARD, {})
    if not _ok(r):
        raise RuntimeError("领取上期奖励失败: %s" % _err(r))
    return r


def my_wish_state(ews_wish, key):
    """我在某一期的许愿状态（数据来自 everyWeekSetting.wish[key].pos）。
    返回 {slots: 占用不同格子数, total: 许愿总次数, pos: {pos:count}}。
    官方 wishCount/hasWishMax 以占用格子数为准（上限 wishMax）。"""
    pos = {}
    node = (ews_wish or {}).get(key)
    if isinstance(node, dict) and isinstance(node.get("pos"), dict):
        pos = {int(k): int(v) for k, v in node["pos"].items()}
    return {"slots": len(pos), "total": sum(pos.values()), "pos": pos}


# pos -> 池名 缓存，由 register_pos_pools 从 stages 构建
_POS_POOL_CACHE = {}


def register_pos_pools(stages):
    """从 stages 里取出 (pos, id) 并登记 pos->池名；返回 pos->池名映射。

    许愿记录 everyWeekSetting.wish[key].pos 只带 pos 和次数、不带池名，
    要靠这张表才知道某次许愿算在哪个池子上。
    """
    _POS_POOL_CACHE.clear()
    for items in (stages or {}).get("world", {}).values():
        for it in items:
            _POS_POOL_CACHE[int(it["pos"])] = pool_of_id(it["id"])
    for pool in (stages or {}).get("camp", {}).values():
        for rows in pool.values():
            for it in rows:
                _POS_POOL_CACHE[int(it["pos"])] = pool_of_id(it["id"])
    return _POS_POOL_CACHE


def pos_pool_map(stages):
    """pos -> 池名（对外入口，基于 stages）。"""
    return register_pos_pools(stages)


def my_wish_state_by_pool(ews_wish, key, stages, visible_pools=None,
                          max_per_pool=None):
    """我在某一期"每个池子"的许愿次数（按池分别计数，上限 0-10）。

    一个池子在 20 个格子里对应多个 pos，玩家的 pos 记录形如 {pos: 次数}，
    所以某个池子的次数 = 该池所有 pos 的次数之和。

    返回 {
      "byPool": {池名: {"used":n,"max":10,"remaining":m}},
      "unknown": 落在未知池子上的次数合计,
      "maxPerPool": 单池上限,
    }
    """
    if max_per_pool is None:
        max_per_pool = wpd.WISH_MAX_PER_POOL
    state = my_wish_state(ews_wish, key)
    pos_map = register_pos_pools(stages) if stages else dict(_POS_POOL_CACHE)

    names = list(wpd.WORLD_POOL_ORDER) + list(wpd.CAMP_POOL_ORDER)
    if visible_pools:
        keep = set(visible_pools)
        names = [n for n in names if n in keep]
    elif pos_map:
        shown = set(pos_map.values())
        names = [n for n in names if n in shown]

    by_pool = {}
    for name in names:
        by_pool[name] = {"used": 0, "max": max_per_pool,
                         "remaining": max_per_pool}
    unknown = 0
    for pos, cnt in state["pos"].items():
        name = pos_map.get(int(pos))
        if name in by_pool:
            by_pool[name]["used"] += int(cnt)
        else:
            unknown += int(cnt)
    for name in by_pool:
        used = wpd.clamp_wish_count(by_pool[name]["used"])
        by_pool[name]["used"] = used
        by_pool[name]["remaining"] = max(0, max_per_pool - used)
    return {"byPool": by_pool, "unknown": unknown, "maxPerPool": max_per_pool}


def pool_remaining(pool_states, pool):
    """取某池剩余可许愿次数；池名未知时返回 None（表示不限制）。"""
    node = (pool_states or {}).get("byPool", {}).get(pool)
    return None if node is None else node["remaining"]


def can_claim_prev(ews_wish, last_key):
    """复刻官方 hasMyPrevReward：上期在>=1格许愿，且记录尚无 'reward' 字段（未领）。"""
    node = (ews_wish or {}).get(last_key)
    if not isinstance(node, dict):
        return False
    pos = node.get("pos")
    slots = len(pos) if isinstance(pos, dict) else 0
    return slots > 0 and "reward" not in node


def my_prev_result(last_period, ews_wish, last_key, my_record_id):
    """我上期各许愿格子的结果：pos -> ('reward',item)中奖 / ('bak',item)保底。
    以 last 格子 rewardUser 中是否存在 我的 record _id 判定中奖。"""
    state = my_wish_state(ews_wish, last_key)
    out = {}
    for pos in state["pos"]:
        cell = last_period.get(str(pos)) or last_period.get(pos) or {}
        wish_id = int(cell.get("id"))
        reward_user = cell.get("rewardUser") or {}
        won = str(my_record_id) in reward_user
        out[pos] = ("reward" if won else "bak", wish_id)
    return out


def load_item_index():
    stages = wpd.load_stages()
    return stages, build_item_index(stages)
