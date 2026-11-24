"""火鸡悬赏：主线追加活动怪，只领取服务器下发的目标怪掉落。"""
import json,random,time
from pathlib import Path

def run(flow,info,slot):
    from activity_availability import require_open
    require_open('RUN_TURKEY_BOUNTY')
    from teacher_trial import enter
    from daily_auto import _dungeon_rec
    from main_farm import _create,_finish
    from game_version import config_table_path
    from teacher_trial import checked
    def table(name):return json.loads(config_table_path(name).read_text(encoding='utf-8-sig'))
    common=table('Common')['1'];ac=table('ActivityCommon')['1']
    monsters=set(str(common['dungeonActivityMonsterIDs']).split(';'))
    if ac['catchChickId']!=ac['xiongShouId']:raise RuntimeError('火鸡活动关联不一致')
    cfg={'dailyMax':int(common['dungeonActivityMax']),'stages':[dict(row,mid=int(k),monsterId=row['monsterID']) for k,row in table('DungeonActivity').items() if str(row.get('monsterID')) in monsters and int(row.get('isDungeonActivity',0))==1]}

    limit=int(cfg['dailyMax'])
    used=int((info.get('everyDaySetting') or {}).get('dungeonActivityCnt') or 0)
    if used>=limit:
        print('[火鸡悬赏] 今日活动次数%s/%s，已完成，跳过'%(used,limit));return
    level=max(int((info.get(p) or {}).get('level') or 0) for p in ('p1','p2'))
    stages=[s for s in cfg['stages'] if int((_dungeon_rec(info,s['mid']) or {}).get('passNum') or 0)>0 and level>=int(s['rolelevel'])]
    if not stages:
        print('[火鸡悬赏] 没有已通关的适用主线，跳过');return
    dungeon_table=table('Dungeon')
    from activity_stage_selection import choose_normal_stage
    def choose_free_stage():
        return choose_normal_stage(stages, info, dungeon_table)
    stage=choose_free_stage()
    if stage is None:
        print('[火鸡悬赏] 适用主线免费次数已用完，跳过')
        return
    print('[火鸡悬赏] %s（%s），今日%s/%s；只捡活动怪奖励'%(stage['name'],stage['mid'],used,limit))
    checked(flow.request('scene.activityHandler.setActivityClose',{'id':int(ac['catchChickId']),'state':0}),'开启火鸡活动怪')
    for _ in range(limit-used):
        fresh=enter(flow,slot)
        info.clear();info.update(fresh)
        if int((info.get('everyDaySetting') or {}).get('dungeonActivityCnt',0))>=limit:
            return
        stage=choose_free_stage()
        if stage is None:
            print('[火鸡悬赏] 已无适用主线免费次数，停止')
            return
        start_user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'查询余额')['user']
        points={k:start_user[k] for k in ('ticket','yuanbao')}
        if points is None:raise RuntimeError('无法核对点券')
        active=None
        try:
            rnd,created=_create(flow,stage['mid']);active=(created,rnd)
            if created.get('consume'):raise RuntimeError('开局出现非预期消耗，停止核查')
            drops=created.get('drops') or []
            targets=[(i,d) for i,d in enumerate(drops) if str(d.get('monsterId'))==str(stage['monsterId']) and d.get('type')!='exp']
            if not targets:
                _finish(flow,*active,win=False);active=None
                print('[火鸡悬赏] 本次未下发活动怪掉落，停止');return
            for i,d in targets:
                salt=random.randint(1,10000)
                reply=flow.request('scene.copyHandler.syncDropInfo',{
                    'index':(int(d.get('dropIndex',i))+salt)^(created['rnd']^rnd),
                    'key':salt^rnd})
                if reply.get('code')!=200 or reply.get('error'):
                    raise RuntimeError('火鸡悬赏领取失败：%s'%(reply.get('error') or reply.get('code')))
                print('[火鸡悬赏] 实际领取：%s'%json.dumps(reply.get('give') or [],ensure_ascii=False))
            time.sleep(25)
            _finish(flow,*active,win=True);active=None
        finally:
            # 结果不明时不追加失败结算，避免重复提交。
            after=enter(flow,slot)
            end_user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'查询余额')['user']
            end={k:end_user[k] for k in ('ticket','yuanbao')}
            info.clear();info.update(after)
            if end!=points:raise RuntimeError('火鸡悬赏执行后点券变化，停止')
        current=int((info.get('everyDaySetting') or {}).get('dungeonActivityCnt') or 0)
        print('[火鸡悬赏] 活动次数%s→%s，点券不变'%(used,current))
        if current<=used or current>=limit:return
        used=current
        time.sleep(5)
