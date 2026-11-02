# -*- coding: utf-8 -*-
"""幻兽试炼（幻兽派遣）协议层 API（独立，不改动工具箱已有文件）。

路由（均由客户端 modules/fairySend 反编译源码确认）：
  刷新：scene.fairyHandler.refreshCollectTask  {"type":0} 免费 / {"type":1} 用点券
  派遣：scene.fairyHandler.collect             {"pos":N,"ids":[幻兽entityId, 幻兽entityId]}
  领奖：scene.fairyHandler.getCollectReward   {"pos":N}
  召回：scene.fairyHandler.reset               {"pos":N}   (未到期提前召回，消耗 sendTicket)
  完成：scene.fairyHandler.complete            {"pos":N}   (消耗 completeTicket 立即完成)

配额（everyDaySetting 字段，缺省即 0）：
  fairyRefreshDayNum      今日已免费刷新次数
  fairyRefreshTicketDayNum 今日已点券刷新次数
  fairySendDayNum         今日已派遣次数
状态（entry.info.fairyCollectData）：{"0":{...},"1":{...},"2":{...}} 三个档位
"""
import fairy_data as fd

ROUTE_REFRESH = "scene.fairyHandler.refreshCollectTask"
ROUTE_COLLECT = "scene.fairyHandler.collect"
ROUTE_REWARD = "scene.fairyHandler.getCollectReward"
ROUTE_RESET = "scene.fairyHandler.reset"
ROUTE_COMPLETE = "scene.fairyHandler.complete"
ROUTE_BUY_COUNT = "scene.fairyHandler.buyCollectCount"

REFRESH_FREE = 0
REFRESH_TICKET = 1


def _ok(result):
    return isinstance(result, dict) and not result.get("error") \
        and result.get("code", 200) == 200


def _err(result):
    if isinstance(result, dict):
        return result.get("error") or result.get("msg") or result
    return result


# ---------- 状态读取 ----------

def slots(info):
    """三个档位原始数据：{0: {...}, 1: {...}, 2: {...}}（键统一成 int）。"""
    raw = (info or {}).get("fairyCollectData") or {}
    out = {}
    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        try:
            out[int(key)] = val
        except (TypeError, ValueError):
            continue
    return out


def slot_state(slot):
    """判断单个档位的状态。

    expiredTime == 0          -> 未派遣（可以派遣）
    expiredTime >  0 且未到   -> 派遣中
    expiredTime >  0 且已到   -> 可领取
    返回 {state, remainMs, dispatched, claimable}
    """
    if not isinstance(slot, dict):
        return {"state": "empty", "remainMs": 0, "dispatched": False,
                "claimable": False}
    fairies = slot.get("fairy") or []
    try:
        expired = int(slot.get("expiredTime") or 0)
    except (TypeError, ValueError):
        expired = 0
    if expired <= 0 or not fairies:
        return {"state": "idle", "remainMs": 0, "dispatched": False,
                "claimable": False}
    now_ms = int(__import__("time").time() * 1000)
    remain = expired - now_ms
    if remain <= 0:
        return {"state": "claimable", "remainMs": 0, "dispatched": True,
                "claimable": True}
    return {"state": "running", "remainMs": remain, "dispatched": True,
            "claimable": False}


def _used(info, field):
    eds = (info or {}).get("everyDaySetting") or {}
    try:
        return int(eds.get(field) or 0)
    except (TypeError, ValueError):
        return 0


def quota(info, help_=None):
    """今日配额状态。"""
    if help_ is None:
        help_ = fd.load_help()
    free_used = _used(info, "fairyRefreshDayNum")
    ticket_used = _used(info, "fairyRefreshTicketDayNum")
    send_used = _used(info, "fairySendDayNum")
    free_total = int(help_["refreshDayNum"])
    ticket_total = int(help_["refreshTicketMaxNum"])
    send_total = int(help_["sendDayNum"])
    return {
        "refreshFreeUsed": free_used,
        "refreshFreeTotal": free_total,
        "refreshFreeLeft": max(0, free_total - free_used),
        "refreshTicketUsed": ticket_used,
        "refreshTicketTotal": ticket_total,
        "refreshTicketLeft": max(0, ticket_total - ticket_used),
        "sendUsed": send_used,
        "sendTotal": send_total,
        "sendLeft": max(0, send_total - send_used),
    }


# ---------- 动作 ----------

def refresh(flow, use_ticket=False, config_dir=fd.DEFAULT_CONFIG_DIR):
    """刷新三个档位的任务。

    use_ticket=False -> {"type":0} 走每日免费次数
    use_ticket=True  -> {"type":1} 消耗点券(refreshTicket)
    """
    args = {"type": REFRESH_TICKET if use_ticket else REFRESH_FREE}
    r = flow.request(ROUTE_REFRESH, args)
    if not _ok(r):
        raise RuntimeError("刷新派遣任务失败: %s" % _err(r))
    return r


def collect(flow, pos, fairy_ids):
    """派遣幻兽。fairy_ids 必须是 2 个 entityId。"""
    if len(fairy_ids) != 2:
        raise ValueError("派遣需要正好 2 只幻兽")
    r = flow.request(ROUTE_COLLECT, {"pos": int(pos), "ids": list(fairy_ids)})
    if not _ok(r):
        raise RuntimeError("派遣失败: %s" % _err(r))
    return r


def get_reward(flow, pos):
    """领取某个档位已到期任务的奖励。"""
    r = flow.request(ROUTE_REWARD, {"pos": int(pos)})
    if not _ok(r):
        raise RuntimeError("领取派遣奖励失败: %s" % _err(r))
    return r


def reset(flow, pos):
    """提前召回（未到期，消耗 sendTicket=100）。"""
    r = flow.request(ROUTE_RESET, {"pos": int(pos)})
    if not _ok(r):
        raise RuntimeError("召回失败: %s" % _err(r))
    return r


def complete(flow, pos):
    """立即完成（消耗 completeTicket=10）。"""
    r = flow.request(ROUTE_COMPLETE, {"pos": int(pos)})
    if not _ok(r):
        raise RuntimeError("立即完成失败: %s" % _err(r))
    return r


def buy_count(flow):
    """购买今日派遣次数（消耗 sendTicket=100）。"""
    r = flow.request(ROUTE_BUY_COUNT, {})
    if not _ok(r):
        raise RuntimeError("购买派遣次数失败: %s" % _err(r))
    return r


# ---------- 回包解析 ----------

def slots_from_reply(raw, info=None):
    """从动作回包里取最新的 fairyCollectData；没有就用传入 info 的。"""
    data = (raw or {}).get("fairyCollectData")
    if isinstance(data, dict):
        out = {}
        for key, val in data.items():
            if isinstance(val, dict):
                try:
                    out[int(key)] = val
                except (TypeError, ValueError):
                    continue
        return out
    return slots(info or {})


def quota_from_reply(raw, help_=None):
    """从动作回包里的 everyDaySetting 刷新配额。"""
    eds = (raw or {}).get("everyDaySetting")
    if not isinstance(eds, dict):
        return None
    info = {"everyDaySetting": eds}
    return quota(info, help_)


def parse_give(raw):
    """回包里的道具（give / reward 字段都可能出现）。"""
    for field in ("give", "reward"):
        rows = (raw or {}).get(field)
        if isinstance(rows, list) and rows:
            out = []
            for entry in rows:
                if not isinstance(entry, dict):
                    continue
                out.append({
                    "type": entry.get("type"),
                    "subType": entry.get("subType"),
                    "count": entry.get("count", 1),
                })
            if out:
                return out
    return []


def format_give(raw, names=None):
    items = parse_give(raw)
    if not items:
        return ""
    names = names or {}
    parts = []
    for it in items:
        sub = it["subType"]
        label = names.get(sub)
        if not label:
            try:
                label = names.get(int(sub))
            except (TypeError, ValueError):
                label = None
        parts.append("%s×%s" % (label or ("item%s" % sub), it["count"]))
    return "、".join(parts)
