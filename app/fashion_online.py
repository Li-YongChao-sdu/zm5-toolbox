"""永久时装在线任务：保存进度与当前有效连接计时，领取以服务器核验为准。"""
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
TASK_ID=970002
BEIJING=timezone(timedelta(hours=8))

def _stored(quest):
    return max(0,int(((quest or {}).get('progress') or {}).get('0',0) or 0))

class OnlineClock:
    def __init__(self,tick=None,now=None):
        self.tick=tick or time.monotonic
        self.now=now or (lambda:datetime.now(BEIJING))
        self.record=None;self.started=None;self.day=None;self.login=None
        self.base=None;self.base_at=None;self.closed=None

    def enter(self,info):
        record=info.get('_id')
        if not record:return
        today=self.now().date()
        login=info.get('lastLoginTime')
        if (record!=self.record or self.day!=today or self.closed is not None
                or (login is not None and self.login is not None and login!=self.login)):
            self.record=record;self.started=self.tick();self.day=today
            self.base=None;self.base_at=None;self.closed=None
        self.login=login

    def sample(self,quest):
        if self.record is not None and self.base is None:
            self.base=_stored(quest);self.base_at=self.tick()

    def elapsed(self):
        if self.started is None or self.day!=self.now().date():return 0
        return max(0,int((self.closed if self.closed is not None else self.tick())-self.started))

    def total(self,quest):
        stored=_stored(quest)
        if self.day!=self.now().date():return stored
        elapsed=self.elapsed()
        # 首次查询前的时间用当前连接下限；之后只累加首次采样后的时间。
        # 新查询若已保存了同一段在线时间，取max，不能再次相加。
        since_sample=max(0,int((self.closed if self.closed is not None else self.tick())-self.base_at)) if self.base_at is not None else 0
        return max(stored,elapsed,(self.base or 0)+since_sample)

    def close(self):
        if self.closed is None:self.closed=self.tick()

def clock_for(flow):
    clock=getattr(flow,'_fashion_online_clock',None)
    if clock is None:
        clock=OnlineClock();flow._fashion_online_clock=clock
    return clock

def observe_reply(flow,route,reply):
    if not isinstance(reply,dict) or reply.get('code',200)!=200 or reply.get('error'):return
    if route=='connector.entryHandler.entry' and isinstance(reply.get('info'),dict):
        clock_for(flow).enter(reply['info'])
    elif route=='scene.questHandler.getQuestList':
        quest=next((q for q in reply.get('quest') or [] if str(q.get('id'))==str(TASK_ID)),None)
        if quest:clock_for(flow).sample(quest)

def target_seconds():
    from game_version import latest_config_folder
    folder=latest_config_folder() or ROOT/'feature_config'
    row=json.loads((folder/'DailyTask.json').read_text(encoding='utf-8-sig'))[str(TASK_ID)]
    target=int(str(row['targetNum']).split(';')[0])
    if target<=0:raise ValueError('在线任务目标时长无效')
    return target

def checked(reply,label):
    if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):
        raise RuntimeError(label+'失败：'+str(reply.get('error') if isinstance(reply,dict) else reply))
    return reply

def snapshot(flow,info,slot,quest,target=None):
    clock=clock_for(flow)
    if clock.record is None:clock.enter(info)
    elif clock.record!=info.get('_id'):
        raise RuntimeError('连接中的存档已变化，停止使用旧存档在线进度')
    if quest is not None:clock.sample(quest)
    target=target or target_seconds()
    status=int((quest or {}).get('status',(quest or {}).get('state',0)) or 0)
    total=clock.total(quest)
    return {'uid':str(info.get('uid','')),'record':info.get('_id'),'slot':slot,
            'day':datetime.now(BEIJING).date().isoformat(),'target_seconds':target,
            'stored_seconds':_stored(quest),'session_seconds':clock.elapsed(),
            'estimated_seconds':min(target,total),'remaining_seconds':max(0,target-total),
            'quest_status':status,'present':quest is not None,'claimed':status==3,
            'ready':status==2 or (status==1 and total>=target),
            'live':clock.closed is None}

def emit(state):
    print('__FASHION_ONLINE_STATE__'+json.dumps(state,ensure_ascii=False),flush=True)

def read_status(flow,info,slot):
    reply=checked(flow.request('scene.questHandler.getQuestList',{}),'在线任务查询')
    quest=next((q for q in reply.get('quest') or [] if str(q.get('id'))==str(TASK_ID)),None)
    return snapshot(flow,info,slot,quest),quest

def claim_online(flow,info,slot,*,wait=False,sleep=None,output=emit,log=print):
    sleep=sleep or time.sleep
    state,quest=read_status(flow,info,slot);output(state)
    if state['claimed']:
        log('[永久时装] 在线任务今日已领取，跳过')
        return {'status':'already_claimed','state':state}
    if not state['present']:
        log('[永久时装] 未找到在线任务，未提交领奖')
        return {'status':'unavailable','state':state}
    if not state['ready'] and not wait:
        log('[永久时装] 已存%s秒，本连接%s秒，估算%s/%s秒；未满不等待' %
            (state['stored_seconds'],state['session_seconds'],state['estimated_seconds'],state['target_seconds']))
        return {'status':'not_ready','state':state}
    day=state['day']
    while not state['ready']:
        if datetime.now(BEIJING).date().isoformat()!=day:
            raise RuntimeError('在线等待跨日，已停止，请重新查询当天任务')
        if not getattr(getattr(flow,'game',None),'_running',False):
            raise RuntimeError('在线连接已断开，停止计时及领奖')
        sleep(min(30,max(1,state['remaining_seconds'])))
        if not getattr(getattr(flow,'game',None),'_running',False):
            clock_for(flow).close()
            raise RuntimeError('在线连接已断开，停止计时及领奖')
        state=snapshot(flow,info,slot,quest,state['target_seconds']);output(state)
    # 不重入存档，不把本地估算写成服务器进度；只提交一次正常领奖。
    if wait:
        state,quest=read_status(flow,info,slot);output(state)
        if state['claimed']:return {'status':'already_claimed','state':state}
        if not state['present'] or not state['ready']:return {'status':'not_ready','state':state}
    def wallet():
        user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'读取余额')['user']
        if any(user.get(k) is None for k in ('ticket','yuanbao')):raise RuntimeError('货币余额缺失')
        return {k:user[k] for k in ('ticket','yuanbao')}
    before=wallet()
    reply=checked(flow.request('scene.questHandler.commitQuest',{'qId':TASK_ID}),'在线任务领奖')
    if reply.get('consume'):raise RuntimeError('在线领奖出现非预期消耗，停止且不重发')
    after,quest=read_status(flow,info,slot);output(after)
    if wallet()!=before:raise RuntimeError('在线领奖点券或元宝变化')
    if not after['claimed']:raise RuntimeError('在线领奖成功回包但领取标志未确认，未重发')
    log('[永久时装] 在线任务领奖成功：'+json.dumps(reply.get('give') or [],ensure_ascii=False))
    return {'status':'claimed','state':after,'give':reply.get('give') or []}

def main():
    from teacher_trial import connect
    parser=argparse.ArgumentParser()
    parser.add_argument('--action',choices=('query','claim','wait'),default='query')
    args=parser.parse_args()
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
    slot=int(account['record_index']);flow=None;state=None
    try:
        flow,info=connect(account,slot)
        if args.action=='query':state,_=read_status(flow,info,slot);emit(state)
        else:state=claim_online(flow,info,slot,wait=args.action=='wait')['state']
    finally:
        if flow:flow.disconnect()
        if state is not None:emit(dict(state,live=False))

if __name__=='__main__':main()
