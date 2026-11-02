"""角色新手活动：补做未完成的日常任务，只用免费副本次数。"""
import random
import time
from new_player_rewards import config, run as claim_rewards

DAILY_IDS = range(8440001, 8440009)


def run(flow, info, slot, password=''):
    from teacher_trial import enter
    from main_farm import _create, _finish, _pickup_all
    from daily_auto import clear_dungeon, quota_remain, _NINE_POOL, NINE_TOWER_MAX
    from union_warehouse import quantity
    if not (info.get('whiteDragon') or {}).get('enable'):
        print('[角色日常] 当前存档无活动，跳过'); return
    points = flow.request('connector.roleHandler.getUserInfo', {}).get('user', {}).get('ticket')
    if points is None: raise RuntimeError('角色日常无法核对点券')
    quests = {}

    def checked(reply):
        if reply.get('code') != 200 or reply.get('error'):
            raise RuntimeError(str(reply.get('error') or reply.get('code')))
        if any(x.get('subType') == 'ticket' for x in reply.get('consume') or []):
            raise RuntimeError('角色日常出现点券消耗，停止')
        return reply

    def refresh():
        fresh = enter(flow, slot); info.clear(); info.update(fresh)
        end = flow.request('connector.roleHandler.getUserInfo', {}).get('user', {}).get('ticket')
        if end != points: raise RuntimeError('角色日常点券发生变化，停止')
        claim_rewards(flow, info, slot, 'dragon', only_claim_ids=DAILY_IDS)
        reply = checked(flow.request('scene.questHandler.getQuestList', {}))
        quests.clear(); quests.update({str(q['id']): q for q in reply.get('quest') or []})

    def remaining(qid, target):
        q = quests.get(str(qid))
        if not q or int(q.get('state', q.get('status', 0))) != 1: return 0
        return max(0, target - max([int(v) for v in (q.get('progress') or {}).values()] or [0]))

    def battle(mid, herb=False, use=0, fortune=False, loot=False):
        rnd, created = _create(flow, mid); active = True
        try:
            if loot: _pickup_all(flow, created, rnd)
            if herb:
                for i, d in enumerate(created.get('drops') or []):
                    if d.get('type') != 'item' or str(d.get('subType')) != '101002000': continue
                    salt = random.randint(1, 10000)
                    checked(flow.request('scene.copyHandler.syncDropInfo', {
                        'index': (int(d.get('dropIndex', i)) + salt) ^ (int(created['rnd']) ^ rnd),
                        'key': salt ^ rnd}))
            for _ in range(use):
                checked(flow.request('scene.itemHandler.useItem', {'index': 0, 'count': 1, 'id': '101009001'}))
                time.sleep(1)
            time.sleep(25)
            if fortune:
                checked(flow.request('scene.copyHandler.finishSingleCopy', {
                    'win': 1, 'rnd': int(created['rnd']) ^ rnd, 'star': 3,
                    'sceneBuffScore': 120, 'maxCombo': 9, 'killMonsterCnt': 66,
                    'useMagicWeaponCnt': 0, 'useBossCardCnt': 0}))
            else: _finish(flow, created, rnd, True)
            active = False
        finally:
            if active:
                try: _finish(flow, created, rnd, False)
                except Exception: pass
        time.sleep(5)

    def attempt(label, action):
        try: action()
        except RuntimeError as exc: print('[角色日常] %s：%s' % (label, exc))
        refresh()  # 即便操作失败也核对点券，再读取真实任务进度。

    refresh()
    def compose():
        needed = remaining(8440004, 3)
        for _ in range(3):
            if quantity(info, 101002000) >= needed * 2: break
            battle(1, herb=True); refresh()
        for _ in range(needed):
            if quantity(info, 101002000) < 2: break
            checked(flow.request('scene.itemHandler.compose', {'composeId': 1}))
            fresh = enter(flow, slot); info.clear(); info.update(fresh); time.sleep(2)
    if remaining(8440004, 3): attempt('炼丹3次', compose)

    def medicine():
        needed = remaining(8440003, 2)
        from celebration_craft_first import prepare, potion_count, spirit_buy_potions
        missing = max(0, needed - potion_count(info))
        if missing:
            # 按庆典同一套流程：先打止血草（第一关最多3局）→ 炼丹合成，合成后再去关卡内用药
            print('[角色日常] 缺回元露%s瓶：先按庆典流程打止血草并炼制' % missing)
            prepare(flow, info, refresh, checked)
            still = max(0, needed - potion_count(info))
            if still:
                spirit_buy_potions(flow, info, refresh, checked, still, password,
                                   label='[角色日常] 备用')
        battle(1, use=needed)
    if remaining(8440003, 2): attempt('关卡内用药', medicine)

    if remaining(8440002, 1):
        limit = 2 if int((info.get('vip') or {}).get('level') or 0) >= 3 else 1
        if quota_remain(info, [200101], limit) > 0:
            attempt('福星挑战', lambda: battle(200101, fortune=True))
        else: print('[角色日常] 福星免费次数已用尽')
    if remaining(8440005, 1) and quota_remain(info, _NINE_POOL, NINE_TOWER_MAX) > 0:
        attempt('九宫玄塔', lambda: clear_dungeon(flow, info, 100011, '角色日常-九宫', max_runs=1))

    # 优先已有通关记录的精英关；新档仅尝试第一关，不自动推进整条主线。
    candidates = [int(k) for k,v in (info.get('dungeon') or {}).items()
                  if str(k).isdigit() and 30010 <= int(k) <= 30800 and v.get('passNum')]
    def elite(mid, count):
        for _ in range(count):
            battle(mid, loot=True)
            refresh()
            if not remaining(8440007, 2): break
    for mid in sorted(candidates, reverse=True) or [30010]:
        needed = remaining(8440007, 2)
        if not needed: break
        free = quota_remain(info, [mid], 2)
        if free > 0:
            attempt('精英挑战', lambda mid=mid, n=min(needed, free): elite(mid, n))

    for row in sorted(config('Sweep').values(), key=lambda x: int(x.get('powerMin') or 0)):
        if not remaining(8440006, 2): break
        mid = int(row['id']); rec = (info.get('dungeon') or {}).get(str(mid)) or {}
        opening = (info.get('dungeon') or {}).get(str(row.get('openSweepDungeonId'))) or {}
        if row.get('type') != 0 or not 30010 <= mid <= 30800 or not rec.get('passNum') or not opening.get('passNum'): continue
        if int(info.get('power') or 0) < int(row.get('powerMin') or 0): continue
        for _ in range(min(remaining(8440006, 2), quota_remain(info, [mid], 2))):
            if int(info.get('sweepEnergy') or 0) < 10: break
            attempt('免费速通', lambda mid=mid: checked(flow.request('scene.copyHandler.sweep', {
                'mid': mid, 'type': 0, 'passNum': info['dungeon'][str(mid)]['passNum']})))
            time.sleep(5)

    def arena():
        if int((info.get('p1') or {}).get('level') or 0) < 30: raise RuntimeError('竞技场需要30级')
        for _ in range(remaining(8440008, 3)):
            a = checked(flow.request('scene.arenaHandler.getArenaInfo', {}))
            recs = a.get('recommend') or []
            if not recs: raise RuntimeError('无推荐对手')
            rid = random.choice(recs)['rid']
            checked(flow.request('scene.arenaHandler.beginArenaBattle', {'targetId': rid})); time.sleep(3)
            checked(flow.request('scene.arenaHandler.endArenaBattle', {'targetId': rid, 'win': 1})); time.sleep(5)
    if remaining(8440008, 3): attempt('竞技场3次（仅免费）', arena)
    for qid in DAILY_IDS:
        q = quests.get(str(qid)) or {}
        if q.get('status') == 1:
            print('[角色日常] 尚未完成：%s；进度%s；条件/材料/免费次数不足时跳过' % (
                config('WhiteDragonTask')[str(qid)]['name'], q.get('progress') or {}))
