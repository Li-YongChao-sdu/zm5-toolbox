"""魔玉兔：主线追加活动怪，只领取服务器下发的目标怪掉落。"""
import json,random,time
from pathlib import Path

def run(flow,info,slot):
    from activity_availability import require_open
    require_open('RUN_MAGIC_RABBIT')
    from teacher_trial import enter
    from daily_auto import _dungeon_rec
    from main_farm import _create,_finish
    cfg=json.loads(Path(__file__).with_name('rabbit_activity.json').read_text(encoding='utf-8-sig'))
    limit=int(cfg['dailyMax'])
    used=int((info.get('everyDaySetting') or {}).get('dungeonActivityCnt') or 0)
    if used>=limit:
        print('[魔玉兔] 今日活动次数%s/%s，已完成，跳过'%(used,limit));return
    level=max(int((info.get(p) or {}).get('level') or 0) for p in ('p1','p2'))
    stages=[s for s in cfg['stages'] if int((_dungeon_rec(info,s['mid']) or {}).get('passNum') or 0)>0 and level>=int(s['rolelevel'])]
    if not stages:
        print('[魔玉兔] 没有已通关的适用主线，跳过');return
    from game_version import config_table_path
    from activity_stage_selection import choose_normal_stage
    from teacher_trial import checked
    dungeon_table=json.loads(config_table_path('Dungeon').read_text(encoding='utf-8-sig'))
    stage=choose_normal_stage(stages,info,dungeon_table)
    if stage is None:
        print('[魔玉兔] 没有可免费进入的已通关普通主线，跳过')
        return
    print('[魔玉兔] %s（%s），今日%s/%s；只捡活动怪奖励'%(stage['name'],stage['mid'],used,limit))
    for _ in range(limit-used):
        fresh=enter(flow,slot)
        info.clear();info.update(fresh)
        if int((info.get('everyDaySetting') or {}).get('dungeonActivityCnt',0))>=limit:
            return
        stage=choose_normal_stage(stages,info,dungeon_table)
        if stage is None:
            print('[魔玉兔] 没有可免费进入的普通主线，停止')
            return
        user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'余额')['user']
        points={key:user[key] for key in ('ticket','yuanbao')}
        if points is None:raise RuntimeError('无法核对点券')
        active=None
        try:
            rnd,created=_create(flow,stage['mid']);active=(created,rnd)
            if created.get('consume'):
                raise RuntimeError('主线开局出现非预期消耗，停止核查')
            drops=created.get('drops') or []
            targets=[(i,d) for i,d in enumerate(drops) if str(d.get('monsterId'))==str(stage['monsterId'])]
            if not targets:
                _finish(flow,*active,win=False);active=None
                print('[魔玉兔] 本次未下发活动怪掉落，停止');return
            for i,d in targets:
                salt=random.randint(1,10000)
                reply=flow.request('scene.copyHandler.syncDropInfo',{
                    'index':(int(d.get('dropIndex',i))+salt)^(created['rnd']^rnd),
                    'key':salt^rnd})
                if reply.get('code')!=200 or reply.get('error'):
                    raise RuntimeError('魔玉兔领取失败：%s'%(reply.get('error') or reply.get('code')))
                print('[魔玉兔] 实际领取：%s'%json.dumps(reply.get('give') or [],ensure_ascii=False))
            time.sleep(25)
            _finish(flow,*active,win=True);active=None
        finally:
            # 超时或异常时不重发结算请求。
            after=enter(flow,slot)
            user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'余额')['user']
            end={key:user[key] for key in ('ticket','yuanbao')}
            info.clear();info.update(after)
            if end!=points:raise RuntimeError('魔玉兔执行后点券变化，停止')
        current=int((info.get('everyDaySetting') or {}).get('dungeonActivityCnt') or 0)
        print('[魔玉兔] 活动次数%s→%s，点券不变'%(used,current))
        if current<=used or current>=limit:return
        used=current
        time.sleep(5)
