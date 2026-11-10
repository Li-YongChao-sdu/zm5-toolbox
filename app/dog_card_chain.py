"""通用狗卡有限接力；当前筛选名单，逐号串行，失败留痕不重发。"""
import json,os,copy
from pathlib import Path
from datetime import datetime
from game_version import beijing_now
from teacher_trial import connect,checked
from union_boss_batch import dog_inventory,DOG_NAMES
from dog_card_tool import execute
ROOT=Path(__file__).resolve().parent

def eligible(cards,daily,card):
    return cards[card-1]['active'] and int(daily.get('addDouble11LotteryCnt',0))==0

def run_chain(jobs,card,seed_mode,code='',folder=None,connect_fn=connect,executor=execute):
    if not 1<=card<=11 or seed_mode not in ('code','inventory'):raise ValueError('无效接力设置')
    if seed_mode=='code' and not code:raise ValueError('缺少起始兑换码')
    folder=Path(folder or ROOT/'dog_chain_reports');folder.mkdir(exist_ok=True)
    members={(str(a['uid']),slot) for a,slot in jobs}
    for path in folder.glob('*.private.json'):
        old=json.loads(path.read_text(encoding='utf8'))
        if old.get('status')!='complete' and old.get('started_mutation') and members.intersection({(x['uid'],x['slot']) for x in old.get('members',[])}):raise ValueError('名单存在未完成接力，请先核对私有记录，不能重复提交')
    lock=folder/'active.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.private.json')
    report={'status':'preflight','date':beijing_now().date().isoformat(),'card':card,'members':[{'uid':str(a['uid']),'slot':s} for a,s in jobs],'completed':[],'steps':[],'started_mutation':False,'current_code':code}
    flow=None
    def save():
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
    def publish(account,slot,state,status='ok',message=''):
        print('__UNION_DOG_OVERVIEW__'+json.dumps({'uid':str(account['uid']),'slot':slot,'status':'ok','cards':state['cards'],'daily':state['daily']},ensure_ascii=False),flush=True)
    def step(account,slot,action,seed):
        node={'uid':str(account['uid']),'slot':slot,'action':action};report['steps'].append(node)
        def store(data):
            node['report']=copy.deepcopy(data)
            if data.get('requests'):report['started_mutation']=True
            save()
        return executor(flow,slot,action,[card],seed,store,publish_callback=lambda state,status,message:publish(account,slot,state,status,message))
    try:
        save();candidates=[]
        for account,slot in jobs:
            if beijing_now().date().isoformat()!=report['date']:raise ValueError('日期改变，停止接力')
            flow,info=connect_fn(account,slot)
            if str(info['uid'])!=str(account['uid']):raise ValueError('实际账号不符')
            cards=dog_inventory(checked(flow.request('scene.activityHandler.getDouble11Data',{}),'查询库存'));daily=info.get('everyDaySetting') or {}
            publish(account,slot,{'cards':cards,'daily':{k:v for k,v in daily.items() if 'double11' in k.lower()}})
            if eligible(cards,daily,card):candidates.append((account,slot,cards[card-1]['count']))
            else:print('[接力] 跳过：未激活所选品种或今日额外机会已获得',flush=True)
            flow.disconnect();flow=None
        if seed_mode=='inventory' and candidates:
            source=next((x for x in candidates if x[2]>0),None)
            if source is None:raise ValueError('当前筛选名单没有可用余卡，请输入起始兑换码')
            candidates.remove(source);candidates.insert(0,source)
        report['plan']=[{'uid':str(a['uid']),'slot':s} for a,s,_ in candidates];report['status']='running';save()
        for index,(account,slot,_) in enumerate(candidates):
            if beijing_now().date().isoformat()!=report['date']:raise ValueError('日期改变，停止接力')
            flow,info=connect_fn(account,slot)
            if str(info['uid'])!=str(account['uid']):raise ValueError('实际账号不符')
            current=dog_inventory(checked(flow.request('scene.activityHandler.getDouble11Data',{}),'查询库存'))
            if not eligible(current,info.get('everyDaySetting') or {},card):raise ValueError('执行前资格变化，停止，不消耗接力码')
            if seed_mode=='code' or index>0:step(account,slot,'redeem',code)
            result=step(account,slot,'gift_draw','')
            code=result.get('generated_code')
            if not code:raise ValueError('未确认下一棒兑换码')
            report['current_code']=code;report['completed'].append({'uid':str(account['uid']),'slot':slot});save()
            print('[接力] %s：完成%s/%s个账号'%(DOG_NAMES[card-1],index+1,len(candidates)),flush=True)
            flow.disconnect();flow=None
        report['status']='complete';save();print('[接力] 完成%s个账号；末码私有保存：%s'%(len(candidates),path),flush=True);return report
    except Exception as exc:
        report.update(status='stopped',error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__);save()
        print('[接力] 已暂停：%s；勿重复运行，请核对：%s'%(report['reason'],path),flush=True);raise
    finally:
        if flow:flow.disconnect()
        lock.unlink(missing_ok=True)
