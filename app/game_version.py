"""邪角色以最新本地 cg1 的 Activity 表为准，不按版本号推算。"""
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BEIJING = timezone(timedelta(hours=8))
GAME_VERSION = '配置自动识别'  # 仅兼容旧导入，不参与开放判断。
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
XIE_ROLE_SWITCHES = frozenset(XIE_ROLE_NAMES)
XIE_DUNGEONS = {
    'RUN_ACT_XWUKONG': (500114, 500115), 'RUN_ACT_XYAOYAO': (500137, 500138),
    'RUN_ACT_XTANG': (500116, 500117), 'RUN_ACT_XLONG': (500118, 500119),
    'RUN_ACT_XYANGJIAN': (500121, 500122), 'RUN_ACT_XBAJIE': (500123, 500124),
    'RUN_ACT_XSHASENG': (500125, 500126), 'RUN_ACT_XBAILONG': (500128, 500129),
}


def beijing_now(now=None):
    now = now or datetime.now(BEIJING)
    return now.astimezone(BEIJING) if now.tzinfo else now.replace(tzinfo=BEIJING)

def latest_config_folder(root=None, now=None):
    """按日期、数值热更序号选择完整目录，不读取未来日期配置。"""
    candidates = []
    today = beijing_now(now).strftime('%Y%m%d')
    for folder in Path(root or ROOT).glob('cg_config_out_cg1_*'):
        match = re.fullmatch(r'cg_config_out_cg1_(\d{8})_(\d+)', folder.name)
        if match and folder.is_dir() and match[1] <= today:
            if all((folder / (table + '.json')).is_file()
                   for table in ('Pet', 'Shop', 'Dungeon', 'Activity', 'Prop')):
                candidates.append((match[1], int(match[2]), folder))
    return max(candidates, default=('', 0, None))[-1]

def _date(value):
    return datetime.strptime(str(value), '%Y/%m/%d-%H:%M:%S').replace(tzinfo=BEIJING)

def xie_activity_state(now=None, root=None):
    # 延迟导入以避免常量定义之间循环；页面与后台共用同一份日历状态。
    from activity_availability import availability_snapshot
    rows = availability_snapshot(now, root)
    return {'source': rows[next(iter(XIE_ROLE_NAMES))]['source'],
            'active': tuple(key for key in XIE_ROLE_NAMES if rows[key]['status'] == 'open'),
            'records': {key: [dict(rows[key], open=rows[key]['status'] == 'open')] for key in XIE_ROLE_NAMES},
            'error': '；'.join(sorted({rows[key]['reason'] for key in XIE_ROLE_NAMES
                                    if rows[key]['status'] == 'unknown'}))}

def active_xie_group(now=None, root=None):
    return xie_activity_state(now, root)['active']


def active_xie_switches(now=None, root=None):
    return frozenset(active_xie_group(now, root))


def active_xie_names(now=None, root=None):
    return tuple(XIE_ROLE_NAMES[key] for key in active_xie_group(now, root))

def xie_status_text(now=None):
    state = xie_activity_state(now)
    return ('配置：%s · 当前邪角色：%s' %
            (state['source'] or '未加载', '、'.join(XIE_ROLE_NAMES[k] for k in state['active']) or '无')) + (
                '；' + state['error'] if state['error'] else '')
