"""庆典每日任务：复用已验证的战斗、用药、炼丹与在线领奖流程。"""

import random

import time

from new_player_rewards import config



# 庆典每日任务按 taskType 识别，不依赖期号（9553/9554...），换期只需更新配置
DAILY_TYPES = {27: 'online', 32: 'item', 33: 'combo', 40: 'kill', 34: 'weapon', 28: 'craft'}

_WARNED = set()





def run(flow, info, slot, scope='all', allow_spirit_backup=False, password=''):
    from activity_availability import require_open
    require_open('RUN_CELEBRATION_ONLINE' if scope=='online' else 'RUN_CELEBRATION')
    if scope not in ('all','tasks','online'):raise ValueError('庆典任务分支无效')
    allowed_types = {27} if scope=='online' else ({32,33,40,34,28} if scope=='tasks' else set(DAILY_TYPES))

    from teacher_trial import enter

    from main_farm import _create, _finish

    from union_warehouse import quantity

    configured = config('HolidayWelfareTask')

    rows = {}

    points = flow.request('connector.roleHandler.getUserInfo', {}).get('user', {}).get('ticket')

    if points is None: raise RuntimeError('庆典任务无法核对点券')



    def checked(r):

        if r.get('code') != 200 or r.get('error'):

            raise RuntimeError(str(r.get('error') or r.get('code')))

        if any(x.get('subType') == 'ticket' for x in r.get('consume') or []):

            raise RuntimeError('庆典任务出现点券消耗，停止')

        return r



    def tasks():

        result = {}

        unknown = set()

        missing = []

        for q in checked(flow.request('scene.questHandler.getQuestList', {})).get('quest') or []:

            row = configured.get(str(q['id']), {})

            if not row:
                if q.get('taskClass') == 95: missing.append(q['id'])
                continue

            task_type = int(row.get('taskType', -1))

            is_daily = row.get('resetType') == 1 and q.get('taskClass') == 95

            if not is_daily:continue

            alias = DAILY_TYPES.get(task_type)

            if task_type not in allowed_types:

                if alias is None: unknown.add(task_type)

                continue

            if alias in result:

                raise RuntimeError('发现多期同类庆典任务，停止以免领错')

            result[alias] = q

            rows[alias] = row

        if unknown and tuple(sorted(unknown)) not in _WARNED:
            _WARNED.add(tuple(sorted(unknown)))
            print('[庆典任务] 出现未适配的任务类型 %s，请更新配置后重试' % sorted(unknown))

        if missing and tuple(missing) not in _WARNED:
            _WARNED.add(tuple(missing))
            print('[庆典任务] 配置缺少任务 %s，请更新配置（当前配置未含本期活动）' % missing)

        return result



    def refresh():

        fresh = enter(flow, slot); info.clear(); info.update(fresh)

        end = flow.request('connector.roleHandler.getUserInfo', {}).get('user', {}).get('ticket')

        if end != points: raise RuntimeError('庆典任务点券发生变化，停止')



    def claim_ready(qs):

        for key, q in qs.items():

            if q.get('status') == 2:

                r = checked(flow.request('scene.questHandler.commitQuest', {'qId': q['id']}))

                print('[庆典任务] %s领奖：%s' % (rows[key]['name'], r.get('give') or []))



    qs = tasks()

    if not qs:

        print('[庆典任务] 当前未开放，跳过'); return

    claim_ready(qs); qs = tasks()

    active = None

    try:

        pending = {k for k, q in qs.items() if q.get('status') == 1}

        if pending & {'item','craft'}:
            from celebration_craft_first import prepare
            if not prepare(flow,info,refresh,checked):
                if not allow_spirit_backup:return
                from celebration_craft_first import spirit_backup
                spirit_backup(flow,info,refresh,checked,password)
            claim_ready(tasks());qs=tasks()
            pending={k for k,q in qs.items() if q.get('status')==1}
        compose = 'craft' in pending

        needs_battle = bool(pending & {'item','combo','kill','weapon'})

        needs_herb = compose and quantity(info, 101002000) < 2

        if needs_battle or needs_herb:

            use = 0

            if 'item' in pending:

                progress = qs['item'].get('progress') or {}

                use = max(0, 2 - max([int(x) for x in progress.values()] or [0]))

                from celebration_craft_first import POTIONS,potion_count,spirit_backup
                if potion_count(info)<use and allow_spirit_backup:
                    spirit_backup(flow,info,refresh,checked,password,craft_remaining=False)
                if potion_count(info)<use:raise RuntimeError('两次炼制后的回元露仍不足，未启用可用的备用补药，停止')
            rnd, created = _create(flow, 1); active = created, rnd

            if needs_herb:

                for i, d in enumerate(created.get('drops') or []):

                    if d.get('type') != 'item' or str(d.get('subType')) != '101002000': continue

                    salt = random.randint(1, 10000)

                    checked(flow.request('scene.copyHandler.syncDropInfo', {

                        'index': (int(d.get('dropIndex', i)) + salt) ^ (int(created['rnd']) ^ rnd),

                        'key': salt ^ rnd}))

            for _ in range(use):
                potion_id=next((k for k in (101009001,101009002) if quantity(info,k)>0),None)
                if potion_id is None:raise RuntimeError('回元露不足，停止')

                checked(flow.request('scene.itemHandler.useItem', {'index': 0, 'count': 1, 'id': str(potion_id)}))

                ((info.get('bag') or {}).get('item') or {})[str(potion_id)]['count'] = quantity(info,potion_id)-1
                time.sleep(1)

            time.sleep(25)

            checked(flow.request('scene.copyHandler.finishSingleCopy', {

                'win': 1, 'rnd': int(created['rnd']) ^ rnd, 'star': 3,

                'maxCombo': 15, 'killMonsterCnt': 36, 'useMagicWeaponCnt': 3, 'useBossCardCnt': 0}))

            active = None

            refresh(); claim_ready(tasks()); time.sleep(5)

        # 原客户端将当前真实在线时长加到已存进度；等待时不重新进入存档。

        qs = tasks(); online = qs.get('online') or {}

        if online.get('status') == 1:

            target = int(rows['online']['targetNum'])

            stored = int((online.get('progress') or {}).get('0', 0))

            wait = max(0, target - stored); start = time.monotonic()

            print('[庆典任务] 在线15分钟：已存%s秒，本次最多维持%s秒；窗口停止按钮可中止' % (stored, wait))

            # Pomelo客户端自带后台心跳；等待期间不轮询任务、不重入存档。
            while time.monotonic() - start < wait:
                time.sleep(max(0, min(30, wait - (time.monotonic() - start))))
            online = tasks().get('online') or {}
            if not online.get('id'):
                raise RuntimeError('在线等待结束后任务已变化，未提交领奖')

            if online.get('status') != 3:

                r = flow.request('scene.questHandler.commitQuest', {'qId': online['id']})

                if r.get('code') == 200 and not r.get('error'):

                    checked(r); print('[庆典任务] 在线任务领奖：%s' % (r.get('give') or []))

                else: print('[庆典任务] 在线任务暂不可领奖：%s' % (r.get('error') or r.get('code')))

        claim_ready(tasks())

        for key, q in tasks().items():

            print('[庆典任务] %s：%s，进度%s' % (rows[key]['name'],

                {1: '未完成', 2: '可领取', 3: '已领取'}.get(q.get('status'), '未知'), q.get('progress') or {}))

    finally:

        if active:

            try: _finish(flow, *active, False)

            except Exception: pass

        refresh()

        print('[庆典任务] 点券%s→%s' % (points, points))

