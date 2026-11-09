"""神兽森林自动选已开启最高关；明确战力拒绝后只回退一级。"""
import json
from collections import Counter
from game_version import latest_config_folder


class ForestPowerInsufficient(RuntimeError):
    def __init__(self, mid, reply):
        self.mid = mid
        self.reply = reply
        super().__init__(str(reply.get('error')))


def is_power_rejection(reply):
    """只识别未开局/未发奖/未消耗的明确战力拒绝，不推断未知错误码。"""
    if not isinstance(reply, dict) or not isinstance(reply.get('error'), str):
        return False
    if reply.get('rnd') is not None or any(reply.get(k) for k in ('drops', 'give', 'consume')):
        return False
    return any(text in reply['error'] for text in (
        '战力不足', '战斗力不足', '战力不够', '战斗力不够',
        '战力未达到', '战斗力未达到', '战力没有达到', '战斗力没有达到',
        '战力低于', '战斗力低于'))


def highest_opened(info, stages, root=None):
    folder = latest_config_folder(root)
    if folder is None:
        raise RuntimeError('无法读取神兽森林解锁配置，请先更新cg1')
    table = json.loads((folder / 'Dungeon.json').read_text(encoding='utf-8-sig'))
    # 与旧AS Unify.playerLevel/getMaxPlayerLevel一致：单人用1P，双人取较高等级。
    roles = ('p1',) if info.get('pMode') == 1 else ('p1', 'p2')
    levels = [int(info[role]['level']) for role in roles
              if isinstance(info.get(role), dict) and info[role].get('level') is not None]
    if not levels or max(levels) < 1:
        raise RuntimeError('无法确认当前存档角色等级，未自动选关')
    available = []
    for mid in stages:
        row = table.get(str(mid))
        if not isinstance(row, dict) or row.get('needLevel') is None:
            raise RuntimeError('神兽森林关卡配置不完整，未猜测最高关')
        if int(row.get('isShow', 1)) and max(levels) >= int(row['needLevel']):
            available.append(mid)
    if not available:
        raise RuntimeError('当前等级没有已开启的神兽森林关卡')
    return max(available)


def run(flow, info, slot, stages, mode, selected, clear, sweep, *, max_runs=4, log=print):
    """clear(mid,n)->(完成数,掉落)，sweep(mid,n)->掉落；回包不明不重发。"""
    stages = tuple(stages)
    if mode not in ('manual', 'sweep'):
        raise ValueError('神兽森林执行模式无效')
    automatic = selected in (None, '')
    expected_id = info.get('_id')
    def refresh():
        reply = flow.request('connector.entryHandler.entry', {'index': slot, 'userAgent': flow.user_agent})
        current = reply.get('info') if isinstance(reply, dict) else None
        if not isinstance(current, dict) or reply.get('code') != 200 or reply.get('error'):
            raise RuntimeError('神兽森林状态读取失败，停止且不重发')
        if expected_id is not None and current.get('_id') != expected_id:
            raise RuntimeError('神兽森林存档发生变化，停止')
        info.clear();info.update(current)
    def used():
        return sum(int(((info.get('dungeon') or {}).get(str(mid)) or {}).get('dailyCount') or 0) for mid in stages)
    def passed(mid):
        return int(((info.get('dungeon') or {}).get(str(mid)) or {}).get('passNum') or 0) > 0
    def wallet():
        reply = flow.request('connector.roleHandler.getUserInfo', {})
        user = reply.get('user') if isinstance(reply, dict) else None
        if not isinstance(user, dict) or reply.get('code') != 200 or reply.get('error'):
            raise RuntimeError('无法核对神兽森林货币余额')
        if any(user.get(k) is None for k in ('ticket', 'yuanbao')):
            raise RuntimeError('神兽森林货币余额缺失')
        return {k: user[k] for k in ('ticket', 'yuanbao')}
    refresh()
    budget = min(4, int(max_runs), max(0, 4 - used()))
    result = {'status': 'daily_limit', 'completed': 0, 'drops': {}, 'mid': None, 'fallback_from': None}
    if budget <= 0:
        log('[神兽森林] 免费次数或执行上限已用尽，未尝试入场')
        return result
    mid = highest_opened(info, stages) if automatic else int(selected)
    if mid not in stages:
        raise ValueError('神兽森林关卡设置无效')
    balance = wallet()
    drops = Counter()
    downgraded = False
    while True:
        result['mid'] = mid
        before = used()
        log('[神兽森林] %s关卡%s；%s' % ('自动' if automatic else '指定', mid, '已通关' if passed(mid) else '已开启但未通关'))
        def verify(count=None):
            refresh()
            delta = used() - before
            if wallet() != balance:
                raise RuntimeError('神兽森林点券或元宝变化，停止且不重发')
            if delta < 0 or delta > budget or (count is not None and delta != count):
                raise RuntimeError('神兽森林共享次数变化不符，停止且不重发')
            return delta
        try:
            if not passed(mid):
                if mode == 'sweep' and not automatic:
                    log('[神兽森林] 指定关卡尚未通关，不能扫荡；请改为手打')
                    result['status'] = 'uncleared';break
                log('[神兽森林] 未通关关卡先手打1次，通过后再按原方式继续')
                count, loot = clear(mid, 1)
                drops.update(loot)
                delta = verify(count)
                if count != 1 or not passed(mid):
                    result['status'] = 'stopped';break
                result['completed'] += delta
                budget -= delta
                before = used()
            available = min(budget, max(0, 4 - used()))
            if available > 0:
                if mode == 'sweep':
                    drops.update(sweep(mid, available))
                    delta = verify()
                else:
                    count, loot = clear(mid, available)
                    drops.update(loot)
                    delta = verify(count)
                result['completed'] += delta
                budget -= delta
            result['status'] = 'complete' if budget == 0 or used() >= 4 else 'stopped'
            break
        except ForestPowerInsufficient as exc:
            if exc.mid != mid or not is_power_rejection(exc.reply):
                raise RuntimeError('神兽森林回包不能确认是未开局战力拒绝，未回退') from None
            # 失败请求确认不扣次数、不扣货币，才允许创建前一关；已有成功局不回退。
            verify(0)
            if not automatic or downgraded or result['completed'] or stages.index(mid) == 0:
                log('[神兽森林] 战力不足；%s，停止' % ('指定关卡不自动改动' if not automatic else '不再继续降关'))
                result['status'] = 'power_insufficient';break
            previous = stages[stages.index(mid) - 1]
            log('[神兽森林] %s战力不足，未消耗次数；回退到前一关%s' % (mid, previous))
            result['fallback_from'] = mid
            mid = previous
            downgraded = True
    result['drops'] = dict(drops)
    return result
