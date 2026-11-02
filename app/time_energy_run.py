"""时光之舟：每轮兑换一次并使用一次，异常停止，不重发。"""
import json
from pathlib import Path

def counter(info, config):
    category = int(config['type'])
    if category == 0:
        return sum(int(((info.get('dungeon') or {}).get(mid) or {}).get('dailyCount') or 0) for mid in config['dungeonId'].split(';'))
    if category == 1:return int((info.get('everyDaySetting') or {}).get('landformChallengeCnt') or 0)
    if category == 2:return -int((info.get('demonTower') or {}).get('count') or 0)
    if category == 4:return -int(((info.get('dungeonTreasure') or {}).get(str(config['dungeonTreasureShareId'])) or {}).get('remainCnt') or 0)
    raise ValueError('不支持的兑换类型')

def refresh(flow, slot):
    reply = flow.request('connector.entryHandler.entry', {'index':slot, 'userAgent':flow.user_agent})
    if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error') or not isinstance(reply.get('info'), dict):
        raise RuntimeError('无法核对当前次数，停止且不重试')
    return reply['info']

def preflight(daily, info, energy_id, cave_plan, slot):
    if energy_id == 6:
        account = daily._ACC
        from my_daily_catalog import validate_plan
        jobs = validate_plan(['RUN_FUN_CARD_CAVE'], cave_plan, str(account['uid']), slot)
        return dict(jobs[0]['args'])
    if energy_id == 2 and daily.FOREST_MODE == 'preview':raise ValueError('神兽森林当前为材料预览，请先选择扫荡或手打')
    if energy_id == 4 and daily.NIGHTMARE_CLAIM_FREE_CARD and daily.NIGHTMARE_CARD_STRATEGY != 'free':
        raise ValueError('此按钮仅支持免费翻牌，请先调整噩梦翻牌设置')
    groups = {2:('forest', daily._FOREST), 3:('nine', daily._NINE_POOL), 5:('ten', daily._TEN), 7:('sky', daily._SKY)}
    if energy_id in groups:
        key, pool = groups[energy_id]
        mid = int(daily.STAGE_OVERRIDE.get(key) or daily.pick_highest_cleared(info, pool))
        if mid not in pool:raise ValueError('原页面关卡设置无效')
        rec = daily._dungeon_rec(info, mid)
        if not rec or int(rec.get('passNum') or 0) <= 0:raise ValueError('原配置关卡尚未通关，请先解锁')
        if energy_id == 2 and daily.FOREST_MODE == 'sweep' and int(info.get('sweepEnergy') or 0) < 10 and not daily.FOREST_AUTO_CRYSTAL:
            raise ValueError('扫荡能量不足10，未兑换')
        return mid
    if energy_id == 4:
        rec = daily._dungeon_rec(info, int(daily.NIGHTMARE_MID))
        if not rec or int(rec.get('passNum') or 0) <= 0:raise ValueError('原噩梦关卡尚未解锁，未兑换')
    if energy_id == 11 and int(daily.STAGE_OVERRIDE.get('wanxiang') or 300113) != 300113:
        raise ValueError('万象古树关卡配置无效')
    return None

def play_once(daily, flow, info, slot, energy_id, target):
    if energy_id in (1,8,9):
        mid = {1:200101,8:200201,9:200301}[energy_id]
        daily.FLUSHOU_MIDS = [(mid, {1:'福',8:'禄',9:'寿'}[energy_id])]
        daily.FLUSHOU_MODE = 'once'
        daily.run_flushou(flow, info)
    elif energy_id == 2:
        if daily.FOREST_MODE == 'sweep':daily.sweep_forest(flow, info, target, max_runs=1)
        else:daily.clear_dungeon(flow, info, target, '神兽森林', quota=(daily._FOREST,4), max_runs=1)
    elif energy_id in (3,5,7):
        pool, limit = {3:(daily._NINE_POOL, daily.NINE_TOWER_MAX),5:(daily._TEN,3),7:(daily._SKY,2)}[energy_id]
        daily.clear_dungeon(flow, info, target, '时光之舟·原配置', quota=(pool,limit), max_runs=1)
    elif energy_id == 4:daily.run_nightmare(flow, info, max_runs=1)
    elif energy_id == 6:
        from card_cave_target import run_matches
        args = dict(target);args['matches'] = 1
        run_matches(flow, slot, **args)
    elif energy_id == 10:daily.run_demon_tower(flow, info)
    elif energy_id == 11:daily.run_wanxiang(flow, info)
    else:raise ValueError('没有对应的执行入口')

def run(flow, info, slot, energy_id, times, cave_plan=None):
    import daily_auto as daily
    from time_energy import CATALOG, exchange
    from my_daily_policy import FreeDailyFlow
    if energy_id not in CATALOG or not 1 <= times <= 15:raise ValueError('兑换项目或次数无效')
    daily.RECORD_INDEX = slot
    daily.MAX_TIMES = 1
    shops = json.loads((Path(__file__).resolve().parent / 'cg_config_out_cg1_20261019_1/Shop.json').read_text(encoding='utf-8-sig'))
    class CheckedBattleFlow(FreeDailyFlow):
        def request(self, route, params=None, *args, **kwargs):
            reply = super().request(route, params, *args, **kwargs)
            if not isinstance(reply, dict) or reply.get('error') or reply.get('code') not in (None, 200):
                self.halted = True
                raise RuntimeError('副本请求失败，停止后续兑换：' + route)
            return reply
    guarded = CheckedBattleFlow(flow, shops)
    config = CATALOG[energy_id]
    done = 0
    for number in range(1, times + 1):
        info = refresh(flow, slot)
        target = preflight(daily, info, energy_id, cave_plan, slot)
        before = counter(info, config)
        info, exchanged = exchange(flow, info, slot, energy_id, 1)
        if exchanged != 1:raise RuntimeError('本轮未确认兑换成功，未开局，停止后续循环')
        if counter(info, config) != before - 1:raise RuntimeError('兑换后的副本次数变化不符，停止且不重试')
        credited = counter(info, config)
        play_once(daily, guarded, info, slot, energy_id, target)
        if guarded.halted:raise RuntimeError('本轮请求未确认，停止后续循环')
        after = refresh(flow, slot)
        if counter(after, config) != credited + 1:raise RuntimeError('本轮未确认正好使用1次，停止后续兑换')
        done += 1
        print('[时光之舟] %s 第%d/%d轮：兑换1次＋执行1次已核对' % (config['name'], number, times), flush=True)
    print('[时光之舟] 完成%d/%d轮' % (done,times), flush=True)
    return done
