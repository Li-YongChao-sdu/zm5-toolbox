# -*- coding: utf-8 -*-
"""善法堂点赞（赠送爱心）数据整理模块（独立，不改动工具箱已有文件）。

玩法（客户端 prefabs/ManRank.as + prefabs/scripts/ManRankDisplayEntity.as 实测确认）：
  在善法堂里展示各职业战力排行第一名的玩家形象，点爱心即为"给TA点赞"，
  系统回赠一份小礼物；每个账号每天可赠送一次爱心。

涉及的路由：
  数据：scene.rankHandler.getAllTop1   {}          -> data.type_1 .. type_8
  点赞：scene.userHandler.criticiseTop1Like {uid,type} -> give[]
  进场景：scene.userHandler.enterScene  {sceneId}  -> 必须先进善法堂

配置来源（只读，不修改）：
  Common.json : loveGiftFreeNum 每天可赠送爱心次数
                loveGiftDropId  点赞掉落表 id
  Scene.json  : 善法堂场景 id（name == "善法堂"）
  Drop.json   : 掉落表 -> itemId / itemProbability / itemMaxNum
  Prop.json   : 道具名字
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG_DIR = os.path.join(HERE, "feature_config")

# 兜底值（配置缺失时用）
FALLBACK_FREE_NUM = 1
FALLBACK_DROP_ID = 15003
FALLBACK_SCENE_IDS = [13, 14, 15, 16, 17]

# 点赞相关关键词（用于在配置里定位善法堂场景）
SHANFA_NAME = "善法堂"


def _load(config_dir, name):
    path = os.path.join(config_dir, name)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _first_record(table):
    """配置表形如 {"1": {...}}，取第一条记录。"""
    if not isinstance(table, dict):
        return {}
    for _, v in table.items():
        if isinstance(v, dict):
            return v
    return {}


def load_common(config_dir=DEFAULT_CONFIG_DIR):
    """读 Common.json，取出每天免费次数与点赞掉落表 id。"""
    free_num = FALLBACK_FREE_NUM
    drop_id = FALLBACK_DROP_ID
    try:
        common = _first_record(_load(config_dir, "Common.json"))
        if common.get("loveGiftFreeNum") is not None:
            free_num = int(common["loveGiftFreeNum"])
        if common.get("loveGiftDropId") is not None:
            drop_id = int(common["loveGiftDropId"])
    except Exception:
        pass
    return {"freeNum": free_num, "dropId": drop_id}


def shanfa_scene_ids(config_dir=DEFAULT_CONFIG_DIR):
    """从 Scene.json 里找出名字是"善法堂"的场景 id（实测为 13-17）。"""
    try:
        scenes = _load(config_dir, "Scene.json")
    except Exception:
        return list(FALLBACK_SCENE_IDS)
    ids = []
    for key, v in (scenes or {}).items():
        if isinstance(v, dict) and v.get("name") == SHANFA_NAME:
            try:
                ids.append(int(v.get("id", key)))
            except (TypeError, ValueError):
                pass
    return sorted(ids) or list(FALLBACK_SCENE_IDS)


def load_drop(drop_id=FALLBACK_DROP_ID, config_dir=DEFAULT_CONFIG_DIR):
    """读点赞掉落表，返回 [(itemId, 权重), ...] 与单次最大数量。"""
    try:
        drop = _load(config_dir, "Drop.json")
    except Exception:
        return {"dropId": drop_id, "items": [], "itemMaxNum": 1, "describe": ""}
    node = (drop or {}).get(str(drop_id)) or (drop or {}).get(drop_id)
    if not isinstance(node, dict):
        return {"dropId": drop_id, "items": [], "itemMaxNum": 1, "describe": ""}
    ids = str(node.get("itemId", "") or "").split(";")
    probs = str(node.get("itemProbability", "") or "").split(";")
    items = []
    for i, raw_id in enumerate(ids):
        raw_id = raw_id.strip()
        if not raw_id:
            continue
        try:
            item_id = int(raw_id)
        except ValueError:
            continue
        weight = 0
        if i < len(probs):
            try:
                weight = int(float(probs[i]))
            except ValueError:
                weight = 0
        items.append((item_id, weight))
    try:
        item_max = int(node.get("itemMaxNum", 1))
    except (TypeError, ValueError):
        item_max = 1
    return {
        "dropId": drop_id,
        "items": items,
        "itemMaxNum": max(1, item_max),
        "describe": node.get("describe", ""),
    }


def item_names(item_ids, config_dir=DEFAULT_CONFIG_DIR):
    """道具 id -> 名字（来自 Prop.json）。"""
    try:
        props = _load(config_dir, "Prop.json")
    except Exception:
        return {}
    out = {}
    for item_id in item_ids:
        node = (props or {}).get(str(item_id))
        if isinstance(node, dict):
            out[int(item_id)] = node.get("name", "")
    return out


if __name__ == "__main__":
    common = load_common()
    print("每天可赠送爱心次数 loveGiftFreeNum =", common["freeNum"])
    print("点赞掉落表 loveGiftDropId =", common["dropId"])
    print("善法堂场景 id =", shanfa_scene_ids())
    drop = load_drop(common["dropId"])
    print("掉落表说明:", drop["describe"], "| 单次最大", drop["itemMaxNum"], "件")
    names = item_names([i for i, _ in drop["items"]])
    total = sum(w for _, w in drop["items"]) or 1
    print("可能的回礼 (%d 种):" % len(drop["items"]))
    for item_id, weight in sorted(drop["items"], key=lambda x: -x[1]):
        print("   %-10d %-16s 权重%-6d %.2f%%"
              % (item_id, names.get(item_id, "?"), weight, weight * 100.0 / total))
