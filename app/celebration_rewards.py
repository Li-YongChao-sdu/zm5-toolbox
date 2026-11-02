"""盛典已完成任务积分与已解锁等级奖品，两个独立领取入口。"""
import argparse
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from new_player_rewards import config
from teacher_trial import connect, enter


def checked(reply, label):
    if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
        raise RuntimeError('%s失败：%s' % (label, reply))
    if reply.get('consume'):
        raise RuntimeError('%s出现非预期消耗，停止' % label)
    return reply


def ticket(flow):
    user = checked(flow.request('connector.roleHandler.getUserInfo', {}), '读取点券').get('user') or {}
    if user.get('ticket') is None:
        raise RuntimeError('无法读取点券，停止')
    return int(user['ticket'])


def claim_tasks(flow, info, slot):
    helper = config('HolidayWelfareHelper')['1']
    activities = set(str(helper['activityTimeId']).split(';'))
    activity_rows = config('Activity')
    now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    activities = {key for key in activities if key in activity_rows and
                  datetime.strptime(activity_rows[key]['shelfTime'], '%Y/%m/%d-%H:%M:%S') <= now <=
                  datetime.strptime(activity_rows[key]['underTime'], '%Y/%m/%d-%H:%M:%S')}
    rows = config('HolidayWelfareTask')
    eligible = {k: row for k, row in rows.items() if str(row.get('activityId')) in activities}
    before_ticket = ticket(flow)
    before_money = int((info.get('holidayWelfare') or {}).get('holidayMoney') or 0)
    done = set()
    received = 0
    for _ in range(len(eligible) + 1):
        listed = checked(flow.request('scene.questHandler.getQuestList', {}), '读取盛典任务')
        ready = sorted((q for q in listed.get('quest') or []
                        if str(q['id']) in eligible and q.get('status') == 2 and str(q['id']) not in done),
                       key=lambda q: int(q['id']))
        if not ready:
            break
        # 每次领奖后重读列表，让下一档已完成任务进入下一轮。
        q = ready[0]
        result = checked(flow.request('scene.questHandler.commitQuest', {'qId': q['id']}), '领取任务积分')
        if ticket(flow) != before_ticket:
            raise RuntimeError('点券发生变化，停止')
        amount = sum(int(v.get('count') or 0) for v in result.get('give') or []
                     if isinstance(v, dict) and v.get('subType') == 'holidayMoney')
        received += amount
        done.add(str(q['id']))
        print('[盛典任务积分] %s（%s）：+%s，奖励%s' %
              (eligible[str(q['id'])]['describe'], q['id'], amount, result.get('give')), flush=True)
        time.sleep(0.5)
    fresh = enter(flow, slot)
    info.clear(); info.update(fresh)
    after_money = int((fresh.get('holidayWelfare') or {}).get('holidayMoney') or 0)
    if after_money - before_money != received:
        raise RuntimeError('盛典积分核对不符：%s→%s，响应累计%s' % (before_money, after_money, received))
    print('[盛典任务积分] 共领取%s项，积分%s→%s；点券%s→%s。未完成任务不执行、不挂机。' %
          (len(done), before_money, after_money, before_ticket, ticket(flow)), flush=True)


def reward_space(info, row, props):
    if row.get('type') != 'item':
        return True
    key = str(row['subType'])
    bag = info.get('bag') or {}
    items = bag.get('item') or {}
    if int((items.get(key) or {}).get('count') or 0) > 0:
        return True
    prop = props.get(key)
    if not prop:
        raise RuntimeError('缺少奖励道具配置：%s' % key)
    consume = bool(int(prop.get('isConsume') or 0))
    limit = bag.get('consumablesBagMax' if consume else 'itemBagMax')
    if limit is None:
        raise RuntimeError('无法确认奖励背包容量')
    used = sum(int(v.get('count') or 0) > 0 and bool(int(v.get('isConsume') or 0)) == consume
               for v in items.values())
    return used < int(limit)


def claim_levels(flow, info, slot):
    rows, props = config('HolidayWelfare'), config('Prop')
    before_ticket = ticket(flow)
    completed = 0
    current = enter(flow, slot).get('holidayWelfare') or {}
    candidates = [(key, row) for key, row in rows.items()
                  if str(row.get('subType')) != '-1' and
                  str(row.get('levelType')) in (current.get('open') or {}) and
                  key not in (current.get('rewardHistory') or {}) and
                  int(current.get('holidayMoney') or 0) >= int(row['holidayMoney'])]
    for key, row in sorted(candidates, key=lambda pair: int(pair[0])):
        fresh = enter(flow, slot)
        state = fresh.get('holidayWelfare') or {}
        if not state.get('startTime'):
            print('[盛典等级奖励] 当前存档未开放盛典', flush=True)
            break
        if str(row.get('subType')) == '-1' or str(row.get('levelType')) not in (state.get('open') or {}):
            continue
        if key in (state.get('rewardHistory') or {}) or int(state.get('holidayMoney') or 0) < int(row['holidayMoney']):
            continue
        if not reward_space(fresh, row, props):
            print('[盛典等级奖励] 背包空间不足，停止：%s' % row['describe'], flush=True)
            break
        result = checked(flow.request('scene.activityHandler.getHolidayWelfare', {'id': int(key)}), '领取等级奖品')
        after = enter(flow, slot)
        if key not in ((after.get('holidayWelfare') or {}).get('rewardHistory') or {}):
            raise RuntimeError('已请求领奖但无法确认记录：%s，请在游戏内核实，停止重试' % key)
        if ticket(flow) != before_ticket:
            raise RuntimeError('点券发生变化，停止')
        if row.get('type') == 'item':
            item = str(row['subType'])
            before_count = int(((fresh.get('bag') or {}).get('item', {}).get(item) or {}).get('count') or 0)
            after_count = int(((after.get('bag') or {}).get('item', {}).get(item) or {}).get('count') or 0)
            if after_count - before_count != int(row['count']):
                raise RuntimeError('等级奖品入包数量不符：%s' % key)
        completed += 1
        info.clear(); info.update(after)
        print('[盛典等级奖励] %s（%s）已领取：%s' % (row['describe'], key, result.get('give')), flush=True)
        time.sleep(0.5)
    print('[盛典等级奖励] 共领取%s档；只领取已解锁奖励，不购买等级或高级盛典。点券%s→%s' %
          (completed, before_ticket, ticket(flow)), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=('tasks', 'levels'), required=True)
    args = parser.parse_args()
    account = json.loads((Path(__file__).parent / 'account.local.json').read_text(encoding='utf-8'))
    slot = int(account.get('record_index', 0))
    flow, info = connect(account, slot)
    try:
        if not (info.get('holidayWelfare') or {}).get('startTime'):
            print('[盛典领取] 当前存档未开放盛典', flush=True)
            return
        (claim_tasks if args.kind == 'tasks' else claim_levels)(flow, info, slot)
    finally:
        flow.disconnect()


if __name__ == '__main__':
    main()
