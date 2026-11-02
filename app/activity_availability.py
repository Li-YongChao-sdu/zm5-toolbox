"""限时活动开放时间：来自20261019配置，统一使用北京时间。"""
from datetime import datetime, timezone, timedelta
from game_version import XIE_ROLE_SWITCHES, active_xie_switches

WINDOWS = {'RUN_ACT_MONKIAN': ('2026-09-08T23:59:59', '2026-10-04T23:59:59'), 'RUN_ACT_DRAGON': ('2026-09-22T23:59:59', '2026-10-18T23:59:59'), 'RUN_ACT_GM': ('2026-09-30T23:59:59', '2026-11-01T23:59:59'), 'RUN_JIN_QIU': ('2026-09-22T23:59:59', '2026-10-18T23:59:59'), 'RUN_DRAGON_TREASURE_TASKS': ('2026-09-22T23:59:59', '2026-10-18T23:59:59'), 'RUN_MID_AUTUMN': ('2026-09-14T23:59:59', '2026-10-11T23:59:59'), 'RUN_CLOUD_LADDER': ('2026-08-25T23:59:59', '2026-10-11T23:59:59'), 'RUN_MAGIC_RABBIT': ('2026-09-14T23:59:59', '2026-10-11T23:59:59'), 'RUN_RELIC_TREASURE': ('2026-09-02T23:59:59', '2026-09-27T23:59:59'), 'RUN_XUANTA_EVENT': ('2026-09-01T00:00:00', '2026-10-07T23:59:59')}

WINDOWS['RUN_CLIMB_HIGH'] = ('2026-10-09T23:59:59', '2026-11-01T23:59:59')

# 20261019官方配置；过期项目同时限制页面选择与后台执行。
WINDOWS.update({'RUN_ACT_MONKIAN': ('2026-09-08T23:59:59', '2026-10-04T23:59:59'), 'RUN_ACT_DRAGON': ('2026-09-22T23:59:59', '2026-10-18T23:59:59'), 'RUN_ACT_GM': ('2026-09-30T23:59:59', '2026-11-01T23:59:59'), 'RUN_ACT_XINGTIAN': ('2026-10-15T23:59:59', '2026-11-08T23:59:59'), 'RUN_JIN_QIU': ('2026-09-22T23:59:59', '2026-10-18T23:59:59'), 'RUN_DRAGON_TREASURE_TASKS': ('2026-09-22T23:59:59', '2026-10-18T23:59:59'), 'RUN_MID_AUTUMN': ('2026-09-14T23:59:59', '2026-10-11T23:59:59'), 'RUN_CLOUD_LADDER': ('2026-10-13T23:59:59', '2026-11-29T23:59:59'), 'RUN_MAGIC_RABBIT': ('2026-09-14T23:59:59', '2026-10-11T23:59:59'), 'RUN_RELIC_TREASURE': ('2026-09-02T23:59:59', '2026-09-27T23:59:59'), 'RUN_CLIMB_HIGH': ('2026-10-09T23:59:59', '2026-11-01T23:59:59'), 'RUN_ACT_XTANG': ('2026-05-25T23:59:59', '2026-10-26T23:59:59'), 'RUN_ACT_XLONG': ('2026-05-25T23:59:59', '2026-10-26T23:59:59')})

def disabled_reason(key, now=None):
    if key in XIE_ROLE_SWITCHES and key not in active_xie_switches():
        return "本游戏版本未开放"
    if key not in WINDOWS:
        return ""
    now = now or datetime.now(timezone(timedelta(hours=8)))
    if now.tzinfo is not None:
        now = now.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    start, end = (datetime.fromisoformat(value) for value in WINDOWS[key])
    if now > end:
        return "已过期（%s结束）" % end.strftime("%Y-%m-%d")
    if now < start:
        return "尚未开放（%s开始）" % start.strftime("%Y-%m-%d")
    return ""


def is_expired(key,now=None):
    if key not in WINDOWS:return False
    now=now or datetime.now(timezone(timedelta(hours=8)))
    if now.tzinfo is not None:now=now.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    return now>datetime.fromisoformat(WINDOWS[key][1])


def hidden_activity(key):
    return is_expired(key) or (key in XIE_ROLE_SWITCHES and key not in active_xie_switches())
