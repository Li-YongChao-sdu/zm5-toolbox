# -*- coding: utf-8 -*-
"""善法堂点赞 协议层 API（独立模块，不改动工具箱已有文件）。

路由（均由客户端反编译源码确认）：
  scene.userHandler.enterScene          {sceneId}      先进入善法堂（不在场景里 get* 会报离线）
  scene.rankHandler.getAllTop1          {}             取各职业战力第一
  scene.userHandler.criticiseTop1Like   {uid, type}    赠送爱心，服务器回 give[] 道具

实测要点：
  * getAllTop1 偶尔返回 code=500（"由于网络原因你已离线"），重试即可；
  * 点赞路由对 uid/type 不做校验（实测传空也成功并给道具）；
  * 返回体 everyDaySetting.criticiseTop1 是"今日已赠送次数"。
"""
import time

import shanfa_data as sd

ROUTE_ENTER_SCENE = "scene.userHandler.enterScene"
ROUTE_GET_TOP1 = "scene.rankHandler.getAllTop1"
ROUTE_LIKE = "scene.userHandler.criticiseTop1Like"

# 需要重试的错误码/文案
RETRY_CODES = (500,)


def _ok(result):
    return isinstance(result, dict) and not result.get("error") \
        and result.get("code", 200) == 200


def _err(result):
    if isinstance(result, dict):
        return result.get("error") or result.get("msg") or result
    return result


def _request_retry(flow, route, args, tries=4, delay=1.5):
    """带重试的请求：getAllTop1 偶尔 500（离线误报），重试即可。"""
    last = None
    for _ in range(max(1, tries)):
        last = flow.request(route, args)
        if _ok(last):
            return last
        if isinstance(last, dict) and last.get("code") in RETRY_CODES:
            time.sleep(delay)
            continue
        return last
    return last


# ---------- 进场景 ----------

def enter_shanfa(flow, config_dir=sd.DEFAULT_CONFIG_DIR, prefer=None):
    """进入善法堂。返回 (ok, sceneId, raw)。

    config_dir 仅用于查善法堂场景 id；prefer 可指定优先场景。
    """
    ids = sd.shanfa_scene_ids(config_dir)
    if prefer is not None and int(prefer) in ids:
        ids = [int(prefer)] + [i for i in ids if i != int(prefer)]
    last = None
    for scene_id in ids:
        r = flow.request(ROUTE_ENTER_SCENE, {"sceneId": scene_id})
        last = r
        if _ok(r):
            return True, scene_id, r
    return False, None, last


def current_scene(info):
    """从 entry info 取当前场景 id。"""
    try:
        return int((info or {}).get("sceneId"))
    except (TypeError, ValueError):
        return None


# ---------- 取目标 ----------

def get_top1(flow):
    """取各职业战力第一。返回 {type_1: {...}, ...}（原样透传服务器 data）。"""
    r = _request_retry(flow, ROUTE_GET_TOP1, {})
    if not _ok(r):
        raise RuntimeError("getAllTop1 失败: %s" % _err(r))
    return r.get("data") or {}


def parse_top1(data):
    """把 getAllTop1 的 data 整理成可点的目标列表。

    服务器键形如 type_1..type_8，值是该职业战力第一的玩家。
    type_0 是宠物榜（数组），没有可点对象，跳过。
    返回 [{"type":N,"uid":..,"rid":..,"name":..,"score":..,"leagueName":..}, ...]
    """
    out = []
    for key, val in sorted((data or {}).items()):
        if not isinstance(val, dict):
            continue  # type_0 是数组（宠物榜），不可点赞
        name = str(key)
        if not name.startswith("type_"):
            continue
        suffix = name.split("_", 1)[1]
        try:
            type_no = int(suffix)
        except ValueError:
            continue
        uid = val.get("uid")
        if uid in (None, ""):
            continue
        out.append({
            "type": type_no,
            "uid": uid,
            "rid": val.get("rid", ""),
            "name": val.get("name", ""),
            "score": val.get("score", 0),
            "leagueName": val.get("leagueName", ""),
        })
    return out


def pick_target(data, type_no=None):
    """从 top1 数据里挑一个目标；type_no 为空则取 type 最小的（即 type_1）。"""
    targets = parse_top1(data)
    if not targets:
        return None
    if type_no is None:
        return targets[0]
    for t in targets:
        if t["type"] == int(type_no):
            return t
    return None


# ---------- 配额 ----------

def like_state(info, free_num=None):
    """今日点赞配额状态。返回 {used, free, remaining, canLike}。

    服务器字段：everyDaySetting.criticiseTop1 = 今日已赠送次数。
    """
    if free_num is None:
        free_num = sd.load_common()["freeNum"]
    eds = (info or {}).get("everyDaySetting") or {}
    try:
        used = int(eds.get("criticiseTop1") or 0)
    except (TypeError, ValueError):
        used = 0
    remaining = max(0, int(free_num) - used)
    return {"used": used, "free": int(free_num),
            "remaining": remaining, "canLike": remaining > 0}


# ---------- 点赞 ----------

def like_top1(flow, uid, type_=0):
    """给指定玩家赠送爱心。返回服务器原始回包（含 everyDaySetting、give）。"""
    r = flow.request(ROUTE_LIKE, {"uid": str(uid), "type": str(type_)})
    if not _ok(r):
        raise RuntimeError("criticiseTop1Like 失败: %s" % _err(r))
    return r


def parse_give(raw):
    """把回包的 give[] 整理成 [{type, subType, count, isConsume}, ...]。"""
    out = []
    for entry in (raw or {}).get("give") or []:
        if not isinstance(entry, dict):
            continue
        out.append({
            "type": entry.get("type"),
            "subType": entry.get("subType"),
            "count": entry.get("count", 1),
            "isConsume": entry.get("isConsume", 1),
        })
    return out


def state_after(raw):
    """点赞回包里带的最新 everyDaySetting（用于刷新配额）。"""
    eds = (raw or {}).get("everyDaySetting")
    return eds if isinstance(eds, dict) else None


def format_give(raw, names=None):
    """把回包道具格式化成可读文字。"""
    items = parse_give(raw)
    if not items:
        return "（回包没有 give 字段）"
    if names is None:
        names = {}
    parts = []
    for it in items:
        sub = it["subType"]
        label = None
        for key in (sub, str(sub)):
            if key in names:
                label = names[key]
                break
        if not label:
            try:
                label = names.get(int(sub))
            except (TypeError, ValueError):
                label = None
        parts.append("%s×%s" % (label or ("item%s" % sub), it["count"]))
    return "、".join(parts)
