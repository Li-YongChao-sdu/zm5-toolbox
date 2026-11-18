"""限时入口统一读取最新cg1；只保留玩法关联，不保存活动日期快照。"""
import json
from functools import lru_cache
from pathlib import Path
from game_version import (XIE_ROLE_SWITCHES, XIE_DUNGEONS, beijing_now,
                          latest_config_folder, _date)

# 有副本的玩法按副本ID匹配，避免同名礼包/商店误匹配。
# 有官方关联字段的玩法优先沿字段找Activity行；缺辅助表时才使用精确名称。
RULES = {
    'RUN_ACT_XINGTIAN': {'dungeons': (500105, 500111)},
    'RUN_ACT_MONKIAN': {'dungeons': (500104, 500110)},
    'RUN_ACT_DRAGON': {'dungeons': (500107, 500108)},
    'RUN_ACT_GM': {'dungeons': (500120, 500127)},
    'RUN_ACT_FIGHT_GM': {'dungeons': (500112, 500113)},
    'RUN_JIN_QIU': {'ref': ('Common', 'redPacketActivityId'), 'names': ('金秋送福',)},
    'RUN_DRAGON_TREASURE_TASKS': {'ref': ('DragonTreasureHelper', 'activityId'), 'names': ('龙宫寻宝',)},
    'RUN_MID_AUTUMN': {'names': ('中秋博饼',)},
    'RUN_CLOUD_LADDER': {'ref': ('CloudLadderHelp', 'activityId'), 'names': ('登云梯',)},
    'RUN_MAGIC_RABBIT': {'names': ('魔玉兔悬赏',)},
    'RUN_RELIC_TREASURE': {'ref': ('Common', 'relicTreasureActivityId'), 'names': ('遗迹寻宝',)},
    'RUN_XUANTA_EVENT': {'task': '玄塔有灵'},
    'RUN_CLIMB_HIGH': {'ref': ('ClimbHigh', 'activityId'), 'names': ('登高采菊',)},
    'RUN_DOG_CARD': {'ref': ('Double11Common', 'startActivityId')},
    'RUN_MAGIC_CRYSTAL': {'ref': ('ActivityCommon', 'hallowmasId')},
    'RUN_CELEBRATION': {'ref': ('HolidayWelfareHelper', 'activityId')},
    'RUN_CELEBRATION_ONLINE': {'ref': ('HolidayWelfareHelper', 'activityId')},
    'RUN_NATIONAL_WISH': {'names': ('国庆许愿',)},
    'RUN_REBIRTH_TRIAL': {'prefix': '轮回试炼-'},
    'RUN_REBIRTH_REWARD': {'prefix': '轮回试炼-', 'reward_window': True},
}
RULES.update({key: {'dungeons': mids} for key, mids in XIE_DUNGEONS.items()})
# 动态模块键来自已有GUI命令绑定；保持用户原收藏键不变。
ALIASES = {'RUN_MODULE_DCE2B544B5171119': 'RUN_REBIRTH_TRIAL',
           'RUN_MODULE_2A934499C1CD4B2E': 'RUN_REBIRTH_REWARD'}
MANAGED_ACTIVITY_KEYS = frozenset(RULES) | frozenset(ALIASES)
TABLES = ('Activity', 'Common', 'DragonTreasureHelper', 'CloudLadderHelp',
          'ClimbHigh', 'Double11Common', 'ActivityCommon', 'HolidayWelfareHelper', 'TaskType')

def _ids(value):
    return tuple(v for v in str(value).split(';') if v and v != '-1')

@lru_cache(maxsize=8)
def _records(folder, signature):
    cache = {}
    def table(name):
        if name not in cache:
            path = Path(folder) / (name + '.json')
            if not path.is_file():
                cache[name] = None
            else:
                value = json.loads(path.read_text(encoding='utf-8-sig'))
                if not isinstance(value, dict):
                    raise ValueError(name + '表格式无效')
                cache[name] = value
        return cache[name]
    activity = table('Activity')
    if not activity:
        raise ValueError('Activity表缺失或为空')
    result = {}
    for key, rule in RULES.items():
        try:
            linked = None
            if rule.get('ref'):
                name, field = rule['ref']
                helper = table(name)
                if helper is not None:
                    value = (helper.get('1') or {}).get(field)
                    if value is None:
                        raise ValueError('%s.%s关联缺失' % (name, field))
                    linked = _ids(value)
            elif rule.get('task'):
                tasks = table('TaskType') or {}
                linked = tuple(str(row['activityId']) for row in tasks.values()
                               if row.get('name') == rule['task'])
            if linked is not None:
                if not linked or any(k not in activity for k in linked):
                    raise ValueError('关联的Activity条目缺失')
                matches = [activity[k] for k in linked]
            elif rule.get('dungeons'):
                matches = [r for r in activity.values() if isinstance(r, dict)
                           and set(_ids(r.get('dungeonId'))).intersection(map(str, rule['dungeons']))]
            else:
                matches = [r for r in activity.values() if isinstance(r, dict) and (
                    r.get('name') in rule.get('names', ()) or
                    bool(rule.get('prefix') and str(r.get('name', '')).startswith(rule['prefix'])))]
            windows = []
            for row in matches:
                start = _date(row['shelfTime'])
                # 轮回挑战和领奖各用自己的截止字段，不能把展示期当挑战期。
                end = _date(row['showUnderTime'] if rule.get('reward_window') else row['underTime'])
                if start > end:
                    raise ValueError('活动起止时间倒置')
                weekdays = frozenset(int(v) for v in str(row.get('weekDay', '0;1;2;3;4;5;6')).split(';'))
                windows.append({'id': row.get('id'), 'name': row.get('name'),
                                'start': start, 'end': end, 'weekdays': weekdays})
            result[key] = {'windows': tuple(windows), 'error': '' if windows else '当前配置没有该活动'}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result[key] = {'windows': (), 'error': str(exc)}
    return result

def availability_snapshot(now=None, root=None):
    """一次快照供整页刷新使用；按文件变化失效，不在导入时冻结日期。"""
    now = beijing_now(now)
    folder = latest_config_folder(root, now)
    source = folder.name if folder else ''
    try:
        if folder is None:
            raise ValueError('未找到完整cg1配置，请更新配置')
        signature = tuple((name, (folder / (name + '.json')).stat().st_mtime_ns,
                           (folder / (name + '.json')).stat().st_size)
                          for name in TABLES if (folder / (name + '.json')).is_file())
        records = _records(str(folder), signature)
        error = ''
    except (OSError, ValueError, TypeError, KeyError) as exc:
        records = {};error = '配置读取失败：' + str(exc)
    states = {}
    for key in RULES:
        entry = records.get(key, {'windows': (), 'error': error})
        windows = entry['windows']
        current = [w for w in windows if w['start'] <= now <= w['end']]
        eligible = [w for w in current if (now.weekday() + 1) % 7 in w['weekdays']]
        chosen = None
        if eligible:
            status, reason, chosen = 'open', '', max(eligible, key=lambda w: w['start'])
        elif entry['error']:
            status, reason = 'unknown', entry['error']
        elif current:
            status, reason, chosen = 'weekday_closed', '当前不在开放星期', max(current, key=lambda w: w['start'])
        elif any(w['start'] > now for w in windows):
            chosen = min((w for w in windows if w['start'] > now), key=lambda w: w['start'])
            status, reason = 'future', '尚未开放（%s开始）' % chosen['start'].strftime('%Y-%m-%d')
        else:
            chosen = max(windows, key=lambda w: w['end'])
            status, reason = 'expired', '已过期（%s结束）' % chosen['end'].strftime('%Y-%m-%d')
        states[key] = {'status': status, 'reason': reason, 'source': source,
                       'id': chosen['id'] if chosen else None,
                       'name': chosen['name'] if chosen else '',
                       'start': chosen['start'].isoformat() if chosen else '',
                       'end': chosen['end'].isoformat() if chosen else ''}
    states.update({key: dict(states[target]) for key, target in ALIASES.items()})
    return states

def disabled_reason(key, now=None):
    if key not in MANAGED_ACTIVITY_KEYS:
        return ''
    return availability_snapshot(now)[key]['reason']

def is_expired(key, now=None):
    return key in MANAGED_ACTIVITY_KEYS and availability_snapshot(now)[key]['status'] == 'expired'

def hidden_activity(key):
    return key in MANAGED_ACTIVITY_KEYS and bool(disabled_reason(key))

def require_open(key, now=None):
    reason = disabled_reason(key, now)
    if reason:
        raise RuntimeError(reason + '；未执行该活动')
