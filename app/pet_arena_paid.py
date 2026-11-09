"""独立点券斗宠任务：固定预算、十局核对、按服务器账务恢复断点。"""
import argparse,hashlib,json,time,re
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parent
PRESETS={'默认对手':'3922097053_r3','备用对手':'1417112202_r11','备用对手2':'2459485755_r29'}
COST=20
COINS=180
BEGIN='scene.petArenaHandler.beginArenaBattleWithTicket'
END='scene.petArenaHandler.endArenaBattle'

def parse_rid(value):
    value=str(value).strip()
    if len(value)>64 or not re.fullmatch(r'[1-9][0-9]*_r[0-9]+',value):
        raise ValueError('请输入完整实际RID，格式：游戏UID_r编号')
    return value

def checked(q):
    if not isinstance(q,dict) or q.get('code')!=200 or q.get('error'):
        raise RuntimeError(str(q.get('error') or q.get('code')) if isinstance(q,dict) else '无效回包')
    return q

def rounds_for(mode,value):
    text=str(value).strip()
    if not text.isdecimal() or int(text)<=0:raise ValueError('局数或预算须为正整数')
    n=int(text)
    if mode=='budget':
        if n%COST:raise ValueError('点券预算必须是20的整数倍')
        n//=COST
    elif mode!='rounds':raise ValueError('未知执行方式')
    return n

def fingerprint(data):
    identity={k:data.get(k) for k in ('rid','name','charId')}
    identity['pets']=[{k:p.get(k) for k in ('entityId','id','level','sex')} for p in data.get('pets',[])]
    return hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def reconcile(initial,current,limit,coins=COINS):
    spent=initial['ticket']-current['ticket'];gain=current['money']-initial['money']
    wins=current['wins']-initial['wins']
    if spent<0 or spent%COST or gain<0 or wins<0:raise ValueError('存在外部余额变化，无法自动核对断点')
    if coins is not None and gain!=wins*coins:raise ValueError('竞技币变化与胜场不符')
    if coins is None and ((wins==0 and gain!=0) or (wins>0 and (gain<=0 or gain%wins))):raise ValueError('无法核对竞技币奖励')
    paid=spent//COST
    if not 0<=wins<=paid<=min(limit,wins+1):raise ValueError('扣费和奖励不一致，需人工核查')
    if current['yuanbao']!=initial['yuanbao'] or current['used']!=initial['used'] or current['index']!=initial['index']:
        raise ValueError('元宝、免费次数或榜单期次变化，请核查后再继续')
    if current['wins']-initial['wins']!=wins:raise ValueError('胜场计数与奖励变化不符')
    return paid,wins

def read_state(flow,slot,handler='petArena'):
    from arena_targets import snapshot
    s,h=snapshot(flow,handler,slot)
    u=checked(flow.request('connector.roleHandler.getUserInfo',{}))['user']
    weekly=h.get('everyWeekSetting') or {}
    s.update(yuanbao=u.get('yuanbao'),wins=weekly.get(handler+'WinNumCurr'),index=h.get('index'),rid=(h.get('self') or {}).get('rid'))
    if any(s[k] is None for k in ('yuanbao','wins','index','rid')):raise ValueError('服务器缺少余额、胜场或身份字段')
    return s

def newest(folder,account,slot,target,handler='petArena'):
    for p in sorted(folder.glob('*.json'),reverse=True):
        r=json.loads(p.read_text(encoding='utf-8'))
        if r.get('handler','petArena')==handler and r.get('account')==account and r.get('slot')==slot and r.get('target')==target and r.get('status')!='complete':return p,r
    return None,None

class Job:
    def __init__(self,report,path,flow,read,sleep=time.sleep,log=print):
        self.r,self.path,self.flow,self.read,self.sleep,self.log=report,Path(path),flow,read,sleep,log
    def save(self):
        tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.r,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.path)
    def request(self,route,params):
        row={'route':route,'params':params,'phase':'pending'};self.r['requests'].append(row);self.save()
        try:q=self.flow.request(route,params)
        except Exception as e:
            row.update(phase='uncertain',error=type(e).__name__);self.save();raise
        row.update(phase='returned',reply={k:q[k] for k in ('code','error','consume','give','rid') if k in q});self.save()
        return checked(q)
    def execute(self,current):
        r=self.r;handler=r.get('handler','petArena');currency=handler+'Money'
        coins=r.get('coin_per_win',COINS if handler=='petArena' else None)
        paid,wins=reconcile(r['initial'],current,r['rounds'],coins)
        if coins is None and wins:coins=(current['money']-r['initial']['money'])//wins;r['coin_per_win']=coins
        r.update(status='running',paid=paid,completed=wins);self.save()
        while True:
            # 先核对已完成的整组，再开下一局。恢复恰好落在组边界也不会重复开局。
            done=sum(g['size'] for g in r['groups'])
            boundary=min(done+10,r['rounds'])
            if wins>=boundary and done<r['rounds']:
                after=self.read();ap,aw=reconcile(r['initial'],after,r['rounds'],coins)
                if (ap,aw)!=(paid,wins):raise ValueError('组末余额与请求记录不一致')
                r['groups'].append({'size':boundary-done,'completed':wins,'state':after});r['latest']=after;self.save()
                self.log('[点券挑战] 第%s组完成｜累计%s/%s局｜已用%s点券｜当前币%s｜剩余预算%s点券'%(len(r['groups']),wins,r['rounds'],paid*COST,after['money'],(r['rounds']-paid)*COST))
            if paid==wins==r['rounds']:
                r['status']='complete';self.save();return
            if paid==wins:
                if paid>=r['rounds']:raise ValueError('达到预算，停止开局')
                q=self.request('scene.'+handler+'Handler.beginArenaBattleWithTicket',{'targetId':r['target']})
                charged=sum(int(v.get('count',0)) for v in q.get('consume',[]) if v.get('subType')=='ticket')
                if charged!=COST:raise ValueError('实际扣费不是20点券，停止')
                paid+=1;r['paid']=paid;self.save()
                actual=(q.get('data') or {}).get('rid') or (q.get('userData') or {}).get('rid') or q.get('rid')
                if actual and actual!=r['target']:raise ValueError('服务器返回的对手不符')
            self.sleep(r['battle_wait'])
            q=self.request('scene.'+handler+'Handler.endArenaBattle',{'targetId':r['target'],'win':1})
            gain=sum(int(v.get('count',0)) for v in q.get('give',[]) if v.get('subType')==currency)
            if coins is None and gain>0:coins=gain;r['coin_per_win']=coins
            if q.get('consume') or gain<=0 or gain!=coins:raise ValueError('结算消耗或奖励异常')
            wins+=1;r['completed']=wins;self.save()
            if wins<r['rounds']:self.sleep(r['round_wait'])

def main():
    from teacher_trial import connect
    from arena_targets import detail
    from category_spend_guard import context,matched
    p=argparse.ArgumentParser();p.add_argument('--handler',choices=('arena','petArena'),default='petArena');p.add_argument('--action',choices=('query','run','resume'),default='query');p.add_argument('--target',type=parse_rid,default=PRESETS['默认对手']);p.add_argument('--mode',choices=('rounds','budget'),default='rounds');p.add_argument('--value',default='10');p.add_argument('--account');p.add_argument('--slot',type=int);p.add_argument('--fingerprint');p.add_argument('--battle-wait',type=float,default=2);p.add_argument('--round-wait',type=float,default=8);args=p.parse_args()
    a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));account=str(a.get('username',''));slot=int(a['record_index']);f=None;job=None
    folder=ROOT/('pet_arena_paid_reports' if args.handler=='petArena' else 'arena_paid_reports')
    try:
        if args.action!='query' and (args.account!=account or args.slot!=slot):raise ValueError('账号或槽位变化，请重新查询')
        if not 2<=args.battle_wait<=3600 or not 8<=args.round_wait<=3600:raise ValueError('局内最低2秒，局间最低8秒')
        f,_=connect(a,slot);s=read_state(f,slot,args.handler)
        if s['rid']==args.target:raise ValueError('不能选择当前出战存档自身，请切换另一个默认对手')
        target=detail(f,args.handler,args.target);fp=fingerprint(target)
        old_path,old=newest(folder,account,slot,args.target,args.handler)
        label=next((k for k,v in PRESETS.items() if v==args.target),'自定义对手')
        data={'handler':args.handler,'account':account,'slot':slot,'target':args.target,'target_label':label,'fingerprint':fp,'state':s,'resume':{'rounds':old['rounds'],'completed':old.get('completed',0),'paid':old.get('paid',0)} if old else None}
        print('__PET_ARENA_PAID_STATE__'+json.dumps(data,ensure_ascii=False),flush=True)
        if args.action=='query':return
        if args.fingerprint!=fp:raise ValueError('对手身份或阵容变化，请重新查询确认')
        if s['used']<s['limit']:raise ValueError('请先完成所选项目当天的免费次数，本入口仅执行点券挑战')
        if args.action=='resume':
            if not old:raise ValueError('没有可继续的任务')
            if old['actor_uid']!=str(a['uid']):raise ValueError('断点不属于当前账号')
            paid,wins=reconcile(old['initial'],s,old['rounds'],old.get('coin_per_win',COINS if args.handler=='petArena' else None));need=(old['rounds']-paid)*COST;report=old;path=old_path
        else:
            if old:raise ValueError('存在未完成任务，请先继续该任务，避免重复付费')
            rounds=rounds_for(args.mode,args.value);need=rounds*COST
            report={'handler':args.handler,'account':account,'actor_uid':str(a['uid']),'slot':slot,'target':args.target,'fingerprint':fp,'rounds':rounds,'budget':need,'battle_wait':args.battle_wait,'round_wait':args.round_wait,'initial':s,'paid':0,'completed':0,'groups':[],'requests':[],'status':'prepared'}
            folder.mkdir(exist_ok=True);path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
        ctx=context();permission=((ctx or {}).get('permissions') or {}).get('daily') or {}
        if not ctx or not matched('daily',permission.get('bits')) or int(permission.get('budget',0))<need:raise ValueError('请开启日常任务1的独立点券权限，并设置至少%s点券预算'%need)
        if s['ticket']<need:raise ValueError('点券余额不足本次剩余预算')
        job=Job(report,path,f,lambda:read_state(f,slot,args.handler),log=lambda s:print(s,flush=True));job.save()
        try:job.execute(s)
        except Exception as e:
            report.update(status='paused',error=str(e) if isinstance(e,(ValueError,RuntimeError)) else type(e).__name__);job.save()
            print('[点券挑战] 已保存断点，未盲目重发。重新查询后点击继续，可核对已扣费/已结算情况：'+report['error'],flush=True)
        print('[点券挑战] 任务记录：'+str(path),flush=True)
    except (ValueError,RuntimeError) as e:print('[点券挑战] 未执行或已停止：'+str(e),flush=True)
    finally:
        if f:f.disconnect()

if __name__=='__main__':main()
