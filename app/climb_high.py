"""重阳采菊：自定义分数，默认100，只使用当天剩余免费机会。"""
import time
from new_player_rewards import config
from teacher_trial import enter


def checked(reply, label):
    if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
        raise RuntimeError('%s失败：%s' % (label, reply.get('error') if isinstance(reply, dict) else reply))
    if reply.get('consume'):
        raise RuntimeError('%s出现非预期消耗，停止' % label)
    return reply


def parse_score(value):
    text = str(value).strip()
    if not text.isdecimal():
        raise ValueError('重阳采菊分数须为非负整数')
    return int(text)


def run(flow, info, slot, score=100):
    from activity_availability import require_open
    require_open('RUN_CLIMB_HIGH')
    row = config('ClimbHigh')['1']
    limit, item_id = int(row['freeNum']), str(row['itemId'])
    score = parse_score(score)
    expected = 0
    for tier in str(row['perItem']).split(';'):
        threshold, amount = map(int, tier.split(','))
        if score >= threshold:
            expected = amount
    print('[重阳采菊] 设置分数%s，配置奖励黄菊%s；超出100分的服务端接受情况尚未实测' % (score, expected))

    def ticket():
        user = checked(flow.request('connector.roleHandler.getUserInfo', {}), '读取点券').get('user') or {}
        if user.get('ticket') is None:
            raise RuntimeError('无法核对点券，停止重阳采菊')
        return int(user['ticket'])

    initial = ticket()
    completed = 0
    for _ in range(limit):
        fresh = enter(flow, slot)
        info.clear(); info.update(fresh)
        used = int((fresh.get('everyDaySetting') or {}).get('climbFreeNum') or 0)
        if used >= limit:
            print('[重阳采菊] 免费次数已用完（%s/%s），停止' % (used, limit))
            break
        if ticket() != initial:
            raise RuntimeError('点券余额变化，停止重阳采菊')
        bag = fresh.get('bag') or {}
        items = bag.get('item')
        if not isinstance(items, dict):
            raise RuntimeError('无法读取背包，停止重阳采菊')
        before_count = int((items.get(item_id) or {}).get('count') or 0)
        if before_count <= 0:
            occupied = sum(int(v.get('count', 0)) > 0 and bool(int(v.get('isConsume', 0))) for v in items.values())
            if bag.get('consumablesBagMax') is None or occupied >= int(bag['consumablesBagMax']):
                print('[重阳采菊] 消耗品栏不足，未入场；请同物归仓或清理后重试')
                break
        start = checked(flow.request('scene.activityHandler.beginClimbHigh', {}), '免费开始')
        current = (start.get('everyDaySetting') or {}).get('climbFreeNum')
        if current is None or int(current) != used + 1:
            raise RuntimeError('免费开始后的次数异常，停止；本次可能已使用机会')
        time.sleep(10)
        result = checked(flow.request('scene.activityHandler.endClimbHigh', {'score': score}), '%s分结算' % score)
        fresh = enter(flow, slot)
        info.clear(); info.update(fresh)
        after_count = int(((fresh.get('bag') or {}).get('item', {}).get(item_id) or {}).get('count') or 0)
        if ticket() != initial:
            raise RuntimeError('点券余额变化，停止重阳采菊')
        if after_count - before_count != expected:
            raise RuntimeError('黄菊入包数量不符（%s→%s），停止以便检查' % (before_count, after_count))
        completed += 1
        print('[重阳采菊] 第%s次完成：%s分，黄菊%s→%s，奖励%s；免费已用%s/%s' %
              (completed, score, before_count, after_count, result.get('give'), current, limit))
        time.sleep(3)
    print('[重阳采菊] 本轮完成%s次，点券%s→%s' % (completed, initial, ticket()))
