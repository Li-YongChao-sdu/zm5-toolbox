"""感恩节五日登录的当天免费领奖。"""
import json
from datetime import datetime

from activity_availability import availability_snapshot
from game_version import BEIJING, beijing_now, config_table_path
from teacher_trial import checked, enter

TASK = 'RUN_THANKSGIVING_LOGIN'


def claim(flow, slot):
    activity = availability_snapshot()[TASK]
    if activity['status'] != 'open' or activity['name'] != '感恩节-5天登录':
        print('[感恩节五日登录] 当前未开放，跳过')
        return

    with config_table_path('LandingRewardOther').open(encoding='utf-8-sig') as stream:
        days = sorted(int(row['id']) for row in json.load(stream).values()
                      if row.get('activityId') == activity['id'])
    if days != [1, 2, 3, 4, 5]:
        raise ValueError('感恩节五日登录档位无法核实')

    info = enter(flow, slot)
    with config_table_path('FunctionOpen').open(encoding='utf-8-sig') as stream:
        gate = next(row for row in json.load(stream).values() if row.get('name') == 'thank_day')
    level = max(int((info.get(role) or {}).get('level') or 0) for role in ('p1', 'p2'))
    history = info.get('dungeon') or {}
    passed = all(int((history.get(mid) or {}).get('passNum') or 0) > 0
                 for mid in str(gate['dungeonId']).split(';') if int(mid) > 0)
    if gate['activityId'] != activity['id'] or level < gate['level'] or not passed:
        print('[感恩节五日登录] 尚未满足入口条件，跳过')
        return

    progress = info.get('landingRewardOther') or {}
    claimed = int(progress.get('day') or 0)
    last = int(progress.get('lastGetTime') or 0)
    if not 0 <= claimed <= len(days) or last < 0:
        raise ValueError('感恩节五日登录进度异常')
    if claimed == len(days) or (last and datetime.fromtimestamp(last / 1000, BEIJING).date() >= beijing_now().date()):
        print('[感恩节五日登录] 今日已领或五档已领满，跳过')
        return

    reply = checked(flow.request('scene.activityHandler.getLandingRewardOther', {}), '感恩节五日登录')
    if reply.get('consume') or int((reply.get('landingReward') or {}).get('day', -1)) != claimed + 1:
        raise RuntimeError('感恩节五日登录回包未确认，请核对进度')
    print('[感恩节五日登录] 已领取第%s天奖励：%s' % (claimed + 1, reply.get('give', [])))
    return reply
