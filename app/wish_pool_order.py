# -*- coding: utf-8 -*-
"""许愿池道具优先级表：固定排序、格子评估与自动筛选。

排序表存 wish_pool_order.json（首次运行按 Prop.price/quality 生成，可手动编辑）：
  {"maxRank": 0, "items": [{"id": 101301006, "name": "仙玉土"}, ...]}
列表越靠前越值钱；maxRank 为 0 表示不设排名门槛（只受本期 3 池上限约束）。

评估规则（每个可见格子 = 一个池当期的道具）：
  大愿望 = reward，小愿望 = base 保底；
  大愿望排名优于小愿望 → 建议 10 次，否则 1 次；
  入选顺序按 min(大愿望排名, 小愿望排名) 从前往后。
"""
import json
import os

import wish_pool_data as wpd
from game_version import feature_config_path

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER_FILE = os.path.join(HERE, "wish_pool_order.json")

FEATHER_NAMES = {160000002: "蓝色羽毛", 160000003: "紫色羽毛"}


def _prop_table():
    try:
        with open(feature_config_path("Prop"), encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def item_name(prop_id, props=None):
    props = props if props is not None else _prop_table()
    row = props.get(str(prop_id)) or {}
    return row.get("name") or FEATHER_NAMES.get(int(prop_id)) or str(prop_id)


def _iter_items(stages):
    seen = set()
    for rows in (stages or {}).get("world", {}).values():
        for item in rows:
            yield item
    for pool in (stages or {}).get("camp", {}).values():
        for rows in pool.values():
            for item in rows:
                yield item


def default_items(stages=None, props=None):
    """按 Prop.price、quality 生成初始顺序（高价值在前，去重）。"""
    stages = stages or wpd.load_stages()
    props = props if props is not None else _prop_table()
    best = {}
    for item in _iter_items(stages):
        for side in ("reward", "base"):
            pid = int(item[side]["subType"])
            if pid in best:
                best[pid]["is_reward"] = best[pid]["is_reward"] or side == "reward"
                continue
            row = props.get(str(pid)) or {}
            best[pid] = {
                "id": pid,
                "name": item_name(pid, props),
                "price": int(row.get("price") or 0),
                "quality": int(row.get("quality") or 0),
                "is_reward": side == "reward",
            }
    rows = sorted(best.values(),
                  key=lambda r: (-r["price"], -r["quality"], -r["is_reward"], r["name"]))
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def save_order(items, max_rank=0, path=ORDER_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"maxRank": int(max_rank), "items": items}, f,
                  ensure_ascii=False, indent=1)
    return path


def load_order(path=ORDER_FILE, create=True):
    """读取排序表；缺失时用配置生成一份。返回 {maxRank, items, ranks}。"""
    data = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        if not create:
            data = {"maxRank": 0, "items": []}
        else:
            data = {"maxRank": 0, "items": default_items()}
            save_order(data["items"], data["maxRank"], path)
    items = []
    for row in data.get("items") or []:
        try:
            pid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        items.append({"id": pid, "name": row.get("name") or item_name(pid)})
    ranks = {row["id"]: index for index, row in enumerate(items)}
    return {"maxRank": int(data.get("maxRank") or 0), "items": items, "ranks": ranks}


def evaluate(cell, ranks):
    """评估一个可见格子：返回大小愿望排名、是否值得追大愿望、建议次数基数。"""
    item = cell.get("item") or {}
    big = (item.get("reward") or {}).get("subType")
    small = (item.get("base") or {}).get("subType")
    missing = len(ranks) + 1
    big_rank = ranks.get(int(big), missing) if big is not None else missing
    small_rank = ranks.get(int(small), missing) if small is not None else missing
    big_better = big_rank < small_rank
    return {
        "bigRank": big_rank,
        "smallRank": small_rank,
        "bigMissing": big is None or int(big) not in ranks,
        "smallMissing": small is None or int(small) not in ranks,
        "bigBetter": big_better,
        "bestRank": min(big_rank, small_rank),
        "suggest": 10 if big_better else 1,
    }


def select(cells, positions, maximum, order=None, max_rank=None):
    """按排序表筛出本期要许愿的格子及目标次数。

    cells: read() 返回的可见格子（含 pos/wishId/item/target 等级上限）
    positions: {pos: 已许次数}
    maximum: 本期最多参与的池数
    max_rank: 排名门槛（1 起，0/None 表示用排序表里的 maxRank）
    返回 [{'cell','target','effective','eval'}, ...]（按优先级排序）
      target    = 1/10，直接写入 manual plan（后端再按等级上限夹紧）
      effective = min(target, 等级上限)，用于界面展示
    """
    order = order or load_order()
    ranks = order["ranks"]
    limit = int(max_rank if max_rank is not None else order.get("maxRank") or 0)
    positions = {int(k): int(v) for k, v in (positions or {}).items() if int(v) > 0}
    free = max(0, int(maximum) - len(positions))
    rows = []
    for cell in cells or []:
        ev = evaluate(cell, ranks)
        if limit > 0 and ev["bestRank"] >= limit:
            continue
        cap = int(cell.get("target") or 0) or ev["suggest"]
        used = positions.get(int(cell["pos"]), 0)
        effective = min(ev["suggest"], cap)
        if used >= effective:
            continue
        rows.append({"cell": cell, "eval": ev, "used": used,
                     "effective": effective, "existing": used > 0})
    rows.sort(key=lambda r: (r["eval"]["bestRank"], r["eval"]["bigRank"]))
    # 已参与的池本来就占着名额，先保留；剩余名额再按排名给新池。
    picked = [r for r in rows if r["existing"]]
    for row in rows:
        if row["existing"]:
            continue
        if free <= 0:
            break
        free -= 1
        picked.append(row)
    picked.sort(key=lambda r: (r["eval"]["bestRank"], r["eval"]["bigRank"]))
    return [{"cell": r["cell"], "target": r["eval"]["suggest"],
             "effective": r["effective"], "eval": r["eval"]} for r in picked]
