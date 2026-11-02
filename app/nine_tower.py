"""普通九宫玄塔：优先领取法宝材料宝箱，再完成Boss房。"""
import time
from collections import defaultdict

# 按Dungeon的宝箱dropId与DropSvr实际奖励筛选，不按宝箱名称猜测。
ROOMS = {1: [2], 2: [2, 3], 3: [2, 3], 4: [8],
         5: [7, 8], 6: [2, 4, 6], 7: [4, 5], 8: [3], 9: [2]}

def route(mid):
    layer = (int(mid) - 100001) // 10
    if layer not in ROOMS or int(mid) != 100001 + layer * 10:
        raise ValueError('普通九宫玄塔入口无效')
    return [int(mid)] + [100000 + layer * 10 + r for r in ROOMS[layer]] + [
        100014 if layer == 1 else 100009 + layer * 10]

def clear(flow, info, mid, label, max_runs=None):
    from daily_auto import quota_remain, _NINE_POOL, NINE_TOWER_MAX, MAX_TIMES, SLEEP
    from main_farm import _create, _pickup_all, _finish
    bag = defaultdict(int)
    completed = 0
    path = route(mid)
    print('[%s] 法宝材料宝箱优先路线：%s' % (label, '→'.join(map(str, path))))
    for _ in range(MAX_TIMES if max_runs is None else max_runs):
        if quota_remain(info, _NINE_POOL, NINE_TOWER_MAX) <= 0:
            print('[%s] 免费次数用尽，停止（不花点券）' % label)
            break
        user = flow.request('connector.roleHandler.getUserInfo', {}).get('user') or {}
        if 'ticket' not in user:
            raise RuntimeError('无法核对点券，停止')
        points = user['ticket']
        active = None
        try:
            for room in path:
                rnd, created = _create(flow, room)
                active = created, rnd
                _, give, skip = _pickup_all(flow, created, rnd)
                for (kind, item), count in give.items():
                    bag['%s:%s' % (kind, item)] += count
                if skip:
                    raise RuntimeError('背包不足，停止')
                time.sleep(3)
            time.sleep(15)
            reply = _finish(flow, *active, win=True)
            active = None
            if reply.get('code') != 200 or reply.get('error'):
                raise RuntimeError('九宫玄塔结算失败')
            completed += 1
            rec = info.setdefault('dungeon', {}).setdefault(str(mid), {'id': mid, 'dailyCount': 0})
            rec['dailyCount'] = int(rec.get('dailyCount') or 0) + 1
        finally:
            if active:
                try:
                    _finish(flow, *active, win=False)
                except Exception:
                    pass
            after = flow.request('connector.roleHandler.getUserInfo', {}).get('user') or {}
            if after.get('ticket') != points:
                raise RuntimeError('点券发生变化，停止')
        print('[%s] 第%s次成功，点券不变；累计掉落：%s' % (label, completed, dict(bag)))
        time.sleep(SLEEP)
    return completed, dict(bag)
