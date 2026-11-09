"""永久时装、八部天龙：仅签到和领取已完成奖励。"""
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta

def config(name):
    if name in ('Activity','HolidayWelfare','HolidayWelfareHelper','HolidayWelfareTask'):
        from game_version import latest_config_folder
        folder=latest_config_folder()
        if folder is None:raise RuntimeError('未找到完整cg1配置，请先更新配置')
        return json.loads((folder/(name+'.json')).read_text(encoding='utf-8-sig'))
    return json.loads((Path(__file__).parent/'feature_config'/(name+'.json')).read_text(encoding='utf-8-sig'))

def run(flow,info,slot,kind,only_claim_ids=None):
    from teacher_trial import enter
    label='永久时装（玉珠）' if kind=='fashion' else '八部天龙等（仙晶）'
    points=(flow.request('connector.roleHandler.getUserInfo',{}).get('user') or {}).get('ticket')
    if points is None:raise RuntimeError('无法核对点券')
    def claim(route,p):
        r=flow.request(route,p)
        if r.get('code')!=200 or r.get('error'):
            print('[%s] %s'%(label,r.get('error') or r.get('code')));return False
        if r.get('consume'):raise RuntimeError('新手活动出现非预期消耗')
        print('[%s] 领取：%s'%(label,json.dumps(r.get('give') or [],ensure_ascii=False)))
        return True
    try:
        if kind=='fashion':
            state=info.get('dailyTaskSpecial') or {}
            if not state.get('startTime'):
                print('[%s] 当前存档无活动，跳过'%label);return
            tz=timezone(timedelta(hours=8));last=int(state.get('lastSignInTime') or 0)
            if not last or datetime.fromtimestamp(last/1000,tz).date()<datetime.now(tz).date():
                claim('scene.dailyTaskHandler.dailyTaskSignIn',{})
            ids=set(config('DailyTask'))
        else:
            if not (info.get('whiteDragon') or {}).get('enable'):
                print('[%s] 当前存档未开放，跳过'%label);return
            ids=set(config('WhiteDragonTask'))
        if only_claim_ids is not None:
            ids &= {str(x) for x in only_claim_ids}
        reply=flow.request('scene.questHandler.getQuestList',{})
        if reply.get('code')!=200:raise RuntimeError('活动任务读取失败')
        count=0
        for q in reply.get('quest') or []:
            ready=int(q.get('state',q.get('status',0)) or 0)==2
            if kind=='fashion' and str(q.get('id'))=='970002' and str(q.get('id')) in ids:
                from fashion_online import claim_online
                result=claim_online(flow,info,slot)
                count+=int(result['status']=='claimed')
                continue
            if str(q.get('id')) in ids and ready:
                count+=bool(claim('scene.questHandler.commitQuest',{'qId':q['id']}))
        print('[%s] 领取%s个已完成任务'%(label,count))
        if kind=='fashion':
            state=enter(flow,slot).get('dailyTaskSpecial') or {}
            for key in sorted(config('DailyTaskReward'),key=int):
                if int(state.get('dailyTaskExp') or 0)>=int(key) and key not in (state.get('reward') or {}):
                    claim('scene.dailyTaskHandler.getReward',{'dailyTaskExp':int(key),'i':0})
    finally:
        fresh=enter(flow,slot);info.clear();info.update(fresh)
        end=(flow.request('connector.roleHandler.getUserInfo',{}).get('user') or {}).get('ticket')
        if end!=points:raise RuntimeError('新手活动执行后点券变化')
        print('[%s] 点券%s→%s'%(label,points,end))
