"""斗宠历史次数找回：只读报价与前后状态核对，不包含网络写操作。"""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
RECOVER = 'scene.petArenaHandler.buyArenaCount'
BEGIN = 'scene.petArenaHandler.beginArenaBattle'
END = 'scene.petArenaHandler.endArenaBattle'


def now():
    return datetime.now(TZ)


def unit_price(handler='petArena'):
    from game_version import latest_config_folder
    folder = latest_config_folder()
    if folder is None:
        raise ValueError('缺少当前配置，不能核算找回费用')
    value = json.loads((folder / 'Challenge.json').read_text(encoding='utf-8-sig'))['1' if handler=='arena' else '2']['jjcChallengeFindBackTicket']
    price = int(value)
    if price <= 0:
        raise ValueError('找回单价无效')
    return price


def state(info, user, home, at=None, handler='petArena'):
    if handler not in ('arena','petArena'):raise ValueError('未知玩法')
    at = (at or now()).astimezone(TZ)
    weekly = copy.deepcopy(info.get('everyWeekSetting') or {})
    weekly.update(copy.deepcopy(home.get('everyWeekSetting') or {}))
    setting = weekly.get(handler+'Setting')
    if not isinstance(setting, dict) or not isinstance(setting.get('week'), dict):
        raise ValueError('服务器缺少斗宠本周次数')
    week = {str(k): int(v) for k, v in setting['week'].items()}
    limits = [int(n) for n in str(home.get('jjcChallengeNum', '')).split(';')]
    day = at.isoweekday() % 7
    actor = home.get('self') or {}
    rid = info.get('_id')
    if len(limits) != 7 or any(n <= 0 for n in limits) or actor.get('rid') != rid or not rid:
        raise ValueError('实际存档身份或每日次数配置不完整')
    if actor.get('rank') is None or int(actor['rank']) < 0:
        raise ValueError('当前存档未报名，不能执行找回挑战')
    used = week.get(str(day), 0)
    if any(k not in tuple(map(str, range(7))) or v < 0 for k, v in week.items()):
        raise ValueError('本周计数格式异常')
    if any(v > limits[int(k)] for k, v in week.items()):
        raise ValueError('本周次数超出每日上限，不能自动找回')
    result = dict(uid=str(info['uid']), rid=rid, date=at.date().isoformat(),
                  day=day, reset=weekly.get('resetTime'), period=home.get('index'),
                  week=week, limits=limits, used=used, limit=limits[day],
                  remaining=max(0, limits[day] - used), money=info.get('arenaMoney' if handler=='arena' else 'petArenaMoney'),
                  arenaMoney=info.get('petArenaMoney' if handler=='arena' else 'arenaMoney'), ticket=user.get('ticket'),
                  yuanbao=user.get('yuanbao'), wins=weekly.get(handler+'WinNumCurr'))
    if any(result[k] is None for k in ('reset', 'period', 'money', 'arenaMoney', 'ticket', 'yuanbao', 'wins')):
        raise ValueError('服务器缺少期次、胜场或余额，停止执行')
    for key in ('money', 'arenaMoney', 'ticket', 'yuanbao', 'wins'):
        result[key] = int(result[key])
    if handler == 'arena':result['handler']=handler
    return result


def plan(s, scope='all', price=None):
    price = unit_price(s.get('handler','petArena')) if price is None else int(price)
    if price <= 0:
        raise ValueError('找回单价无效')
    if scope != 'all' and str(scope) not in tuple(map(str, range(1, 7))):
        raise ValueError('请选择全部历史日或周一至周六')
    today = s['day'] or 7
    if scope != 'all' and int(scope) >= today:
        raise ValueError('只能找回本周已经过去的日期')
    days = []
    for day in range(1, today):
        count = s['limits'][day] - s['week'].get(str(day), 0)
        if count > 0 and (scope == 'all' or day == int(scope)):
            days.append(dict(day=day, count=count, cost=count * price))
    return dict(scope=scope, price=price, days=days,
                cost=sum(d['cost'] for d in days),
                rounds=s['remaining'] + sum(d['count'] for d in days),
                existing=s['remaining'])


def digest(s, p, target_fp):
    return hashlib.sha256(json.dumps([s, p, target_fp], sort_keys=True).encode()).hexdigest()


def unchanged(a, b, exclude=()):
    for key in a:
        if key not in exclude and a[key] != b.get(key):
            raise ValueError('服务器状态发生额外变化：' + key)


def battle_started(a, b):
    expected = copy.deepcopy(a)
    expected['week'][str(a['day'])] = a['used'] + 1
    expected.update(used=a['used'] + 1, remaining=max(0, a['remaining'] - 1))
    unchanged(expected, b)


def battle_won(a, b):
    expected = copy.deepcopy(b)
    expected['wins'] = a['wins']
    expected['money'] = a['money']
    battle_started(a, expected)
    if b['wins'] != a['wins'] + 1 or b['money'] <= a['money']:
        raise ValueError('胜场或斗宠币未确认到账，不重复结算')


def recovered(a, b, batch):
    expected = copy.deepcopy(a)
    day, count, cost = batch['day'], batch['count'], batch['cost']
    expected['week'][str(day)] = a['limits'][day]
    expected['week'][str(a['day'])] = a['used'] - count
    expected.update(used=a['used'] - count, remaining=a['remaining'] + count,
                    ticket=a['ticket'] - cost)
    unchanged(expected, b)


def redact(value):
    if isinstance(value, dict):
        return {k: ('[已隐去]' if any(x in k.lower() for x in ('password', 'cookie', 'token'))
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return copy.deepcopy(value)
