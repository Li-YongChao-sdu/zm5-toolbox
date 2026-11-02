"""三船共享五次免费刷新：按图示方案分配，不购买次数。"""
import json,time
from pathlib import Path
from tongtian_rob import _active_escort,SHIP_NAMES

ROOT=Path(__file__).resolve().parent
STRATEGIES={
 'direct':'直接发船（不刷新）',
 'spirit_buyer':'点券买灵气玩家：宝船／赌银帆／余次',
 'free':'零氪微氪玩家：宝船／宝船／3次冲海舰',
}

def state(info):
    daily=info.get('everyDaySetting');ship=info.get('tongtianRiver')
    if not isinstance(daily,dict) or not isinstance(ship,dict) or not daily.get('resetTime') or not info.get('uid'):
        raise ValueError('通天河每日计数或船档未读取，未提交')
    count=int(daily.get('tongtianRiverEscortNum',0));used=int(daily.get('tongtianRiverEscortRefreshNum',0));tier=int(ship.get('goodId',0))
    if not 0<=count<=3 or not 0<=used<=5 or tier not in SHIP_NAMES:raise ValueError('通天河计数或船档异常')
    return {'uid':str(info['uid']),'day':int(daily['resetTime']),'count':count,'used':used,'tier':tier,'active':bool(_active_escort(info))}

def decision(strategy,trip,tier,left,phase):
    """返回是否刷新及刷新成功后的阶段；不在本地模拟随机结果。"""
    if strategy=='direct' or left<=0 or tier==4:return False,phase
    if trip==3:return True,'spend'
    if strategy=='free' or trip==1:return tier<2,'ensure'
    # 第二船先保宝船；赌银帆失败后只回宝船，不再重复赌。
    if phase=='recover':return tier<2,'recover'
    if tier<2:return True,'ensure'
    if tier>=3:return False,phase
    if left<2:return False,phase  # 次数被手动使用后，不冒无法回宝船的风险。
    return True,'recover'

def run(flow,info,slot,strategy,refresh,folder=None,sleep=time.sleep,log=print):
    if strategy not in STRATEGIES:raise ValueError('未知发船策略')
    folder=Path(folder) if folder else ROOT/'tongtian_escort_state';folder.mkdir(exist_ok=True)
    s=state(info);path=folder/(s['uid']+'.json')
    old=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if old.get('pending'):raise RuntimeError('上次通天河请求结果未确认，请先核查记录：'+str(path))
    previous=old.get('binding') or {}
    same_day=previous.get('uid')==s['uid'] and previous.get('day')==s['day']
    if same_day:
        expected_count=int(previous['count'])+(1 if old.get('phase')=='sent' else 0)
        expected_refresh=old.get('used')
        if expected_count!=s['count'] or (expected_refresh is not None and expected_refresh!=s['used']):
            raise ValueError('检测到策略记录以外的发船或刷新操作，已中止自动策略。记录已发%s船／刷新%s次，服务器已发%s船／刷新%s次；请先核查，不自动套用后续分支。'%(expected_count,expected_refresh,s['count'],s['used']))
    elif s['count'] or s['used']:
        raise ValueError('今日已发%s船／刷新%s次，但没有对应策略记录，无法确认此前是否按本方案操作；已中止自动策略。'%(s['count'],s['used']))
    binding={k:s[k] for k in ('uid','day','count')}
    same=old.get('binding')==binding
    if same and old.get('phase') and old.get('strategy')!=strategy:
        raise ValueError('本条船已开始按另一策略刷新，请保持原方案完成后再切换')
    phase=old.get('phase','ensure') if same else 'ensure'
    expected_used=old.get('used') if same else None
    if expected_used is not None and expected_used!=s['used']:
        raise ValueError('免费刷新次数已被其他操作改变，请核对本条船记录后再执行')
    record=old if same else {'binding':binding,'strategy':strategy,'requests':[],'start_used':s['used']}
    def save():path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    if s['count']>=3 or s['active']:
        log('[发船策略] 今日已发满，或已有正在护送／待领奖的船，跳过');return info
    def request(route,next_phase):
        nonlocal info,s,phase
        before=dict(s);row={'route':route,'params':{},'phase':'pending'}
        record['requests'].append(row);record['pending']=True;save()
        try:q=flow.request(route,{})
        except Exception:
            row['phase']='uncertain';save();raise RuntimeError('通天河请求结果未知，不自动重发：'+str(path)) from None
        row.update(phase='returned',reply=q);save()
        if not isinstance(q,dict) or q.get('code')!=200 or q.get('error'):
            record['pending']=False;save();raise RuntimeError('通天河操作失败：'+str(q.get('error') if isinstance(q,dict) else '无效回包'))
        # 任何异常消耗或查询失败，保留 pending 阻止盲目重发。
        if q.get('consume'):raise RuntimeError('免费发船策略出现非预期消耗，停止并核查记录')
        info=refresh();s=state(info)
        if s['uid']!=before['uid'] or s['day']!=before['day']:raise RuntimeError('账号或每日重置时间变化，停止')
        if route.endswith('freshEscortGood'):
            if s['used']!=before['used']+1 or s['count']!=before['count']:raise RuntimeError('刷新计数核对失败，停止')
        elif s['count']!=before['count']+1 or not s['active']:raise RuntimeError('发船次数或护送状态核对失败，停止')
        phase=next_phase;record.update(pending=False,phase=phase,used=s['used']);row['phase']='verified';save()
    log('[发船策略] %s｜今日第%s条船｜剩余免费刷新%s次'%(STRATEGIES[strategy],s['count']+1,5-s['used']))
    while True:
        if strategy=='free' and s['count']==2 and s['used']-record['start_used']>=3:break
        again,next_phase=decision(strategy,s['count']+1,s['tier'],5-s['used'],phase)
        if not again:break
        request('scene.tongtianHandler.freshEscortGood',next_phase)
        log('[发船策略] 刷新后%s｜剩余免费%s次'%(SHIP_NAMES[s['tier']],5-s['used']))
        sleep(1)
    request('scene.tongtianHandler.escort','sent')
    log('[发船策略] 已发船；到达后按原领奖存档领取。本次不等待、不自动发下一船。')
    return info
