"""邪角色以最新本地 cg1 的 Activity 表为准，不按版本号推算。"""
import re
import sys
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

def app_home(root=None):
    """配置与账号目录：打包后为 exe 同级目录，源码运行为 app 目录。"""
    if root is not None:
        return Path(root)
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return ROOT

def feature_config_path(name, root=None):
    """定位配置表：运行目录 → 模块目录 → 最新完整 cg1 配置目录。"""
    fname = name if str(name).endswith('.json') else str(name) + '.json'
    home = app_home(root)
    for folder in (home / 'feature_config', ROOT / 'feature_config'):
        path = folder / fname
        if path.is_file():
            return path
    for base in (home, ROOT):
        folder = latest_config_folder(base)
        if folder is not None and (folder / fname).is_file():
            return folder / fname
    return home / 'feature_config' / fname

def config_table_path(name, root=None):
    """定位游戏数值表：优先最新完整 cg1，缺失时回退 feature_config。"""
    fname = name if str(name).endswith('.json') else str(name) + '.json'
    for base in (app_home(root), ROOT):
        folder = latest_config_folder(base)
        if folder is not None and (folder / fname).is_file():
            return folder / fname
    return feature_config_path(fname, root)


def config_folder_date(folder):
    """从 cg_config_out_cg1_YYYYMMDD_N 目录名解析配置日期。"""
    match = re.fullmatch(r'cg_config_out_cg1_(\d{8})_\d+', Path(folder).name)
    return datetime.strptime(match.group(1), '%Y%m%d').date() if match else None


def config_is_stale(folder=None, now=None, days=8, hour=12):
    """本地配置日期 + days 天的 hour 点（北京时间）之后视为过期。"""
    folder = folder or latest_config_folder()
    if folder is None:
        return True
    config_date = config_folder_date(folder)
    if config_date is None:
        return True
    deadline = datetime(config_date.year, config_date.month, config_date.day,
                        hour, tzinfo=BEIJING) + timedelta(days=days)
    return beijing_now(now) >= deadline


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
