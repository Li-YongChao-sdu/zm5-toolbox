"""噩梦天树王：服务器下发本周关卡，每周免费两次。"""
from teacher_trial import enter
import time
from collections import Counter


def run(flow, info, slot):
    from daily_auto import activity_bag_ready

    def status():
        reply = flow.request('scene.copyHandler.getDungeonWingId', {})
        if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
            raise RuntimeError('读取噩梦天树王失败：%s' % reply)
        count = reply.get('cnt')
        if not isinstance(count, int) or not 0 <= count <= 2:
            raise RuntimeError('本周次数无法确认或超出免费上限，停止：%s' % count)
        try:
            mid = int(reply.get('dungeonId') or 0)
        except (TypeError, ValueError):
            raise RuntimeError('服务器关卡ID格式异常')
        if count and mid not in (700601, 700602, 700603):
            raise RuntimeError('服务器返回未知噩梦天树王关卡：%s' % mid)
        return mid, count

    def ticket():
        reply = flow.request('connector.roleHandler.getUserInfo', {})
        value = (reply.get('user') or {}).get('ticket')
        if value is None:
            raise RuntimeError('无法确认点券余额，停止')
        return int(value)

    initial = ticket()
    completed = 0
    for _ in range(2):
        mid, count = status()
        if count == 0:
            print('[噩梦天树王] 本周无剩余次数，停止；不购买次数')
            break
        fresh = enter(flow, slot); info.clear(); info.update(fresh)
        if ticket() != initial:
            raise RuntimeError('点券变化，停止噩梦天树王')
        if not activity_bag_ready(info, '噩梦天树王'):
            break
        print('[噩梦天树王] 服务器本周关卡%s，剩余%s次' % (mid, count))
        def checked(reply, label):
            if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
                raise RuntimeError('%s失败：%s' % (label, reply))
            if reply.get('consume'):
                raise RuntimeError('%s出现非预期消耗，停止' % label)
            return reply
        before_counts = {str(k): int(v.get('count') or 0) for k, v in fresh['bag']['item'].items()}
        started = checked(flow.request('scene.copyHandler.beginDungeonWing', {}), '专用开始')
        if started.get('cnt') != count - 1:
            raise RuntimeError('开始后周次数异常，停止；本次可能已使用机会')
        listed = started.get('drop')
        if not isinstance(listed, list):
            raise RuntimeError('未返回专用宝箱掉落，停止')
        time.sleep(25)
        drops = Counter()
        for index, item in enumerate(listed):
            reply = checked(flow.request('scene.copyHandler.getDungeonWingReward',
                {'index': int(item.get('dropIndex', index))}), '专用宝箱拾取')
            for given in reply.get('give') or []:
                if isinstance(given, dict) and given.get('type') == 'item':
                    drops[str(given['subType'])] += int(given['count'])
            time.sleep(1)
        ended = checked(flow.request('scene.copyHandler.endDungeonWing',
            # ExitBattleServerCmd的isNewSkyTree专用分支固定为0，不能套用普通副本胜利值1。
            {'win': 0, 'maxCombo': 0, 'killMonsterCnt': {700601: 3, 700602: 2, 700603: 3}[mid],
             'useMagicWeaponCnt': 0, 'useBossCardCnt': 0}), '专用结算')
        # 部分版本可能在结算补发未拾取物品，空项不代表重复奖励。
        for given in ended.get('give') or []:
            if isinstance(given, dict) and given.get('type') == 'item':
                drops[str(given['subType'])] += int(given['count'])
        _, after_count = status()
        fresh = enter(flow, slot); info.clear(); info.update(fresh)
        if ticket() != initial:
            raise RuntimeError('点券变化，停止噩梦天树王')
        for key, amount in drops.items():
            actual = int((fresh['bag']['item'].get(key) or {}).get('count') or 0)
            if actual - before_counts.get(key, 0) != amount:
                raise RuntimeError('宝箱奖励入包核对失败：%s' % key)
        if after_count != count - 1:
            raise RuntimeError('周次数变化异常：%s→%s，停止' % (count, after_count))
        completed += 1
        print('[噩梦天树王] 已完成专用拾取与结算%s次，奖励入包已核对%s；周次数%s→%s，点券%s→%s' %
              (completed, drops, count, after_count, initial, initial))
