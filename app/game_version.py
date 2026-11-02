# -*- coding: utf-8 -*-
"""游戏版本及按版本轮换的邪角色活动。"""
from decimal import Decimal

# 游戏内版本号；每次游戏更新后改这里，例如 47.4 -> 47.5。
# 本轮按八戒/白龙组轮换；界面与后台共用此配置。
GAME_VERSION = "47.8"
ROTATION_BASE_VERSION = "47.4"

# 从基准版本起，每增加 0.1 进入下一组。
XIE_ROLE_CYCLE = (
    ("RUN_ACT_XBAJIE", "RUN_ACT_XBAILONG"),       # 八戒、白龙
    ("RUN_ACT_XSHASENG", "RUN_ACT_XYANGJIAN"),    # 沙僧、二郎神
    ("RUN_ACT_XWUKONG", "RUN_ACT_XYAOYAO"),       # 悟空、瑶瑶
    ("RUN_ACT_XTANG", "RUN_ACT_XLONG"),           # 唐僧、龙女
)
XIE_ROLE_NAMES = {
    "RUN_ACT_XBAJIE": "邪八戒",
    "RUN_ACT_XBAILONG": "邪白龙",
    "RUN_ACT_XSHASENG": "邪沙僧",
    "RUN_ACT_XYANGJIAN": "邪二郎神",
    "RUN_ACT_XWUKONG": "邪悟空",
    "RUN_ACT_XYAOYAO": "邪瑶瑶",
    "RUN_ACT_XTANG": "邪唐僧",
    "RUN_ACT_XLONG": "邪龙女",
}
XIE_ROLE_SWITCHES = frozenset(key for group in XIE_ROLE_CYCLE for key in group)


def active_xie_group(game_version=GAME_VERSION):
    """返回该游戏版本开放的邪角色开关组；只接受以 0.1 为步长的版本号。"""
    steps = (Decimal(str(game_version)) - Decimal(ROTATION_BASE_VERSION)) * 10
    if steps != steps.to_integral_value():
        raise ValueError("游戏版本必须按 0.1 递增: %s" % game_version)
    return XIE_ROLE_CYCLE[int(steps) % len(XIE_ROLE_CYCLE)]


def active_xie_switches(game_version=GAME_VERSION):
    return frozenset(active_xie_group(game_version))


def active_xie_names(game_version=GAME_VERSION):
    return tuple(XIE_ROLE_NAMES[key] for key in active_xie_group(game_version))
