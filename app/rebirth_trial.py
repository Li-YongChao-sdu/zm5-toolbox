"""轮回试炼，最高仅支持第13层。"""
import argparse,json,random,time,math
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parent
MAX_LAYER=13
REWARDS=(3,6,9,11,13)

def required_power(layer):
    # 已核对Dungeon.powerMin2；本入口不开放第14层及以上。
    if not 1<=layer<=MAX_LAYER:raise ValueError('仅支持前13层')
    return 140000 if layer<=10 else 560000

def combat_power(flow,info):
    index=int((info.get('rebirthTower') or {}).get('index',-1))
    if index==-1:index=0  # 客户端未选隐藏角色时默认1P。
    if index not in (0,1):raise ValueError('轮回试炼出战角色索引未知')
    q=checked(flow.request('scene.characterHandler.getPower',{}))
    value=q.get('p1' if index==0 else 'p2')
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
        raise ValueError('无法确认出战角色战力，未发起挑战')
    return {'value':value,'index':index}

def total_score(data,source='query'):
    # entry/getReward: score为未通关层附加分；endChallenge: score已是总分。
    value=float(data.get('score',0))
    return round(value if source=='settlement' else int(data['cur'])*10000+value,6)

def checked(q):
    if not isinstance(q,dict) or q.get('code')!=200 or q.get('error'):
        raise RuntimeError(str(q.get('error') or q.get('code')) if isinstance(q,dict) else '无效回包')
    return q

def state(info):
    s=info.get('rebirthTower')
    if not isinstance(s,dict) or 'cur' not in s:raise ValueError('服务器未返回轮回试炼进度')
    return {'cur':int(s['cur']),'score':s.get('score',0),'actId':s.get('actId'),'reward':s.get('reward',{})}

def wallet(flow):
    u=checked(flow.request('connector.roleHandler.getUserInfo',{}))['user']
    w={k:u.get(k) for k in ('ticket','yuanbao')}
    if any(v is None for v in w.values()):raise ValueError('无法核对点券及元宝')
    return w

def merge_state(current,reply):
    patch=reply.get('rebirthTower')
    if not isinstance(patch,dict) or 'cur' not in patch or 'score' not in patch:
        raise RuntimeError('结算缺少层数或分数，停止')
    result=state({'rebirthTower':dict(current,**patch)})
    result['score_source']='settlement'
    return result

def run(flow,initial,refresh,request,wait=10,sleep=time.sleep,log=print):
    from activity_availability import require_open
    require_open('RUN_REBIRTH_TRIAL')
    if not 10<=wait<=3600:raise ValueError('间隔须为10～3600秒')
    current=state(initial);current['score_source']='query';period=current['actId'];before=wallet(flow)
    actor=combat_power(flow,initial) if current['cur']<MAX_LAYER else None
    while current['cur']<MAX_LAYER:
        require_open('RUN_REBIRTH_TRIAL')
        expected=current['cur']+1
        need=required_power(expected)
        if actor['value']<need:
            log('[轮回试炼] 出战%sP战力%g不足第%s层要求%g，已停在%s层，未创建下一关。'%(actor['index']+1,actor['value'],expected,need,current['cur']))
            return current
        q=request('scene.rebirthTowerHandler.openChallenge',{'rnd':random.random()})
        did=int(q.get('dungeonId',0))
        if q.get('needReport',True) or q.get('isOnline',False):
            log('[轮回试炼] 本关要求录像或服务器战斗，已停止，未结算。');return current
        if did!=1800100+expected or not 1800101<=did<=1800113:
            raise RuntimeError('开局层数与进度不符，未结算')
        sleep(wait)
        q=request('scene.rebirthTowerHandler.endChallenge',{'bossHp':0})
        if q.get('consume'):raise RuntimeError('返回包含消耗，停止')
        after=merge_state(current,q)
        if wallet(flow)!=before:raise RuntimeError('点券或元宝变化，停止')
        if after['actId']!=period or after['cur']!=expected:raise RuntimeError('期次或通关进度异常，停止')
        current=after;log('[轮回试炼] 已通关第%s层，结算总分%g'%(current['cur'],total_score(current,'settlement')))
    log('[轮回试炼] 已达到第13层，停止挑战。')
    return current

def main():
    from teacher_trial import connect,enter
    p=argparse.ArgumentParser();p.add_argument('--action',choices=['query','run','reward'],default='query');p.add_argument('--account');p.add_argument('--slot',type=int);p.add_argument('--act-id',type=int);p.add_argument('--wait',type=float,default=10);args=p.parse_args()
    from activity_availability import require_open
    if args.action!='query':require_open('RUN_REBIRTH_TRIAL' if args.action=='run' else 'RUN_REBIRTH_REWARD')
    a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(a['record_index']);name=str(a.get('username',''));f=None
    try:
        if args.action!='query' and (args.account!=name or args.slot!=slot):raise ValueError('账号或槽位变化，请重新查询')
        f,info=connect(a,slot);s=state(info)
        actor=None
        if args.action in ('query','run'):
            try:actor=combat_power(f,info)
            except (ValueError,RuntimeError):
                if args.action=='run':raise
        def emit(source='query'):
            data=state(info);data.update(account=name,slot=slot,score_source=source,total_score=total_score(data,source),combat_power=actor)
            print('__REBIRTH_STATE__'+json.dumps(data,ensure_ascii=False),flush=True)
        emit()
        if args.action=='query':return
        if args.act_id!=s['actId']:raise ValueError('活动期次变化，请重新查询')
        folder=ROOT/'rebirth_trial_reports';folder.mkdir(exist_ok=True)
        for old in folder.glob('*.json'):
            d=json.loads(old.read_text(encoding='utf-8'))
            if d.get('account')==name and d.get('slot')==slot and any(x.get('phase') in ('pending','uncertain') for x in d.get('requests',[])):
                raise ValueError('存在结果未确认的请求，请先人工核查记录：'+str(old))
        report={'account':name,'slot':slot,'before':s,'requests':[]};path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
        def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        def request(route,params):
            row={'route':route,'params':params,'phase':'pending'};report['requests'].append(row);save()
            try:q=f.request(route,params)
            except Exception as e:
                row.update(phase='uncertain',error=type(e).__name__);save();raise RuntimeError('请求结果未确认，不自动重发：'+str(path)) from None
            row.update(phase='returned',reply=q);save();return checked(q)
        def refresh():return enter(f,slot)
        if args.action=='run':
            result=run(f,info,refresh,request,args.wait,log=lambda text:print(text,flush=True))
            info['rebirthTower']=result
            report['challenge_result']=result;report['total_score']=total_score(result,result['score_source']);save()
            emit(result['score_source'])
        else:
            before=wallet(f)
            for layer in REWARDS:
                require_open('RUN_REBIRTH_REWARD')
                info=refresh();s=state(info);rid=str(1800100+layer)
                if s['actId']!=args.act_id:raise ValueError('活动期次变化，停止')
                if s['cur']<layer or s['reward'].get(rid)!=1:continue
                q=request('scene.rebirthTowerHandler.getReward',{'id':int(rid)})
                after=state(refresh())
                if after['reward'].get(rid)==1:raise RuntimeError('领取标志未变化，停止')
                if q.get('consume') or wallet(f)!=before:raise RuntimeError('领奖出现消耗或货币变化，停止')
                print('[轮回试炼] 已领取第%s层奖励'%layer,flush=True)
        if args.action!='run':
            info=refresh();report['after']=state(info);save();emit()
        print('[轮回试炼] 记录：'+str(path),flush=True)
    finally:
        if f:f.disconnect()

if __name__=='__main__':main()
