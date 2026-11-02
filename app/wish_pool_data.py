# -*- coding: utf-8 -*-
"""许愿池 数据整理模块（独立、不改动工具箱已有文件）。

从官方配置 Wish.json 提取需要的四个池：
  无阵营（unionType=0，始终显示“后两个”）：彻悟池(1030)、无量池(1040)
  阵营联盟（unionType 11-14，有阵营时额外显示“后两个”）：轮回池(1071)、圆满池(1081)

运行本文件会把整理结果落地为 wish_pool_stages.json，供协议/界面模块直接读取。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# 配置源（生成数据时使用；集成进工具箱后改用落地的 wish_pool_stages.json）
DEFAULT_CONFIG_DIR = os.path.join(HERE, "feature_config")
STAGES_FILE = os.path.join(HERE, "wish_pool_stages.json")

# id 前缀 -> 归类
WORLD_PREFIXES = {"1030": "彻悟池", "1040": "无量池"}
CAMP_PREFIXES = {"1071": "轮回池", "1081": "圆满池"}

# 始终显示的无阵营池（顺序即展示顺序）
WORLD_POOL_ORDER = ["彻悟池", "无量池"]
# 有阵营联盟时额外显示的阵营池
CAMP_POOL_ORDER = ["轮回池", "圆满池"]

# 单个池子的许愿次数上下限（本次需求：每个池子 0-10 次）。
# 注意与配置区分：
#   Wish.wishCount    = 10 是每条 item 自己的字段（客户端 WPItem 里当等级缩放的除数用），不是次数上限；
#   WishCommon.wishMax= 3  是"本期占用格子总数"的上限；
#   本常量是"单个池子"各自的许愿次数上限，只作用于本目录的代码，不改配置文件。
WISH_MIN_PER_POOL = 0
WISH_MAX_PER_POOL = 10


def clamp_wish_count(n):
    """把许愿次数夹到 0-10。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return WISH_MIN_PER_POOL
    return max(WISH_MIN_PER_POOL, min(WISH_MAX_PER_POOL, n))


def _to_int_list(s):
    if isinstance(s, (int, float)):
        return [int(s)]
    out = []
    for part in str(s).split(","):
        part = part.strip()
        if part:
            out.append(int(float(part)))
    return out


def normalize_entry(raw):
    """把 Wish.json 一条原始配置整理成精简结构。"""
    union_type = int(raw.get("unionType", 0))
    return {
        "id": int(raw["id"]),
        "pool": raw.get("name", ""),
        "unionType": union_type,
        "camp": (union_type - 10) if union_type > 0 else 0,
        "pos": int(raw.get("wishPos", 0)),
        "consumeType": raw.get("consume_type", "coin"),
        "consumeSub": raw.get("consume_subType", "spirit"),
        "consumeCosts": _to_int_list(raw.get("consume_count", 0)),
        "base": {
            "type": raw.get("base_type", ""),
            "subType": raw.get("base_subType", 0),
            "count": raw.get("base_count", 0),
            "des": raw.get("des", ""),
        },
        "reward": {
            "type": raw.get("reward_type", ""),
            "subType": raw.get("reward_subType", 0),
            "count": raw.get("reward_count", 0),
        },
        "weight": int(raw.get("weight", 0)),
        "wishCount": int(raw.get("wishCount", 0)),
        "countAdd": raw.get("countAdd", 0),
        "icon": raw.get("icon", ""),
    }


def build_stages(config_dir=DEFAULT_CONFIG_DIR):
    """读取 Wish.json，归类整理四个目标池。

    返回：{
      "wishMax": 每期许愿上限,
      "world": {池名: [条目,...]},      # 彻悟池/无量池
      "camp":  {池名: {camp1:[...], camp2:[...], camp3:[...], camp4:[...]}},
    }
    """
    wish_path = os.path.join(config_dir, "Wish.json")
    common_path = os.path.join(config_dir, "WishCommon.json")
    with open(wish_path, encoding="utf-8") as f:
        wish = json.load(f)
    wish_max = 3
    try:
        with open(common_path, encoding="utf-8") as f:
            common = json.load(f)
        wish_max = int(next(iter(common.values())).get("wishMax", 3))
    except Exception:
        pass

    world = {name: [] for name in WORLD_POOL_ORDER}
    camp = {name: {c: [] for c in range(1, 5)} for name in CAMP_POOL_ORDER}

    for key, raw in wish.items():
        prefix = str(key)[:4]
        item = normalize_entry(raw)
        if prefix in WORLD_PREFIXES:
            pool = WORLD_PREFIXES[prefix]
            world[pool].append(item)
        elif prefix in CAMP_PREFIXES:
            pool = CAMP_PREFIXES[prefix]
            c = item["camp"]
            if 1 <= c <= 4:
                camp[pool][c].append(item)

    for pool in world:
        world[pool].sort(key=lambda x: x["pos"])
    for pool in camp:
        for c in camp[pool]:
            camp[pool][c].sort(key=lambda x: x["pos"])

    return {"wishMax": wish_max, "world": world, "camp": camp}


def save_stages(config_dir=DEFAULT_CONFIG_DIR, out_path=STAGES_FILE):
    data = build_stages(config_dir)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def load_stages(path=STAGES_FILE):
    """优先读落地数据；不存在则现场从配置目录生成。"""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return save_stages(out_path=path)


def visible_pools(stages, my_camp):
    """按玩家阵营返回需要显示的池及其条目。

    my_camp: 0=无阵营联盟；1-4=所在阵营。
    返回：[(池名, [条目,...], is_camp), ...]
    """
    out = []
    for pool in WORLD_POOL_ORDER:
        out.append((pool, stages["world"].get(pool, []), False))
    if my_camp and 1 <= my_camp <= 4:
        for pool in CAMP_POOL_ORDER:
            out.append((pool, stages["camp"].get(pool, {}).get(str(my_camp), [])
                        or stages["camp"].get(pool, {}).get(my_camp, []), True))
    return out


if __name__ == "__main__":
    d = save_stages()
    print("wishMax =", d["wishMax"])
    for pool in WORLD_POOL_ORDER:
        print("无阵营 %s: %d 项" % (pool, len(d["world"][pool])))
    for pool in CAMP_POOL_ORDER:
        counts = {c: len(d["camp"][pool][c]) for c in range(1, 5)}
        print("阵营 %s: 各阵营条目 %s" % (pool, counts))
    print("落地文件:", STAGES_FILE)
