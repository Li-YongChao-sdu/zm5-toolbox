"""潜能培养第二步：清单宠物先75级，潜能>=2者再101级；自动单/双宠。"""
import argparse,json,random,threading,time
from collections import Counter,deque
from pathlib import Path
from pet_training_capture import ROOT,snapshot
from pet_training_storage import atomic_json

def passive(p):return (p.get('skill') or {}).get('passivity') or {}
def eligible101(p):return any(int(v)>=2 for v in passive(p).values())
def latest_stage(info):
    """已开放主线关卡取最高，排除七星殿80和蓬丘61。"""
    exclude={61,80};dungeon=info.get('dungeon') or {}
    ids=[int(k) for k,v in dungeon.items() if str(k).isdigit() and 1<=int(k)<=100 and int(k) not in exclude and isinstance(v,dict) and v.get('id')]
    if not ids:raise RuntimeError('未读取到已开放主线关卡')
    return max(ids)
def indices(info,mode):
    dual=bool(info.get('p2'))
    if mode=='both' and not dual:raise ValueError('当前是单人档，无法使用1P和2P')
    return [0,1] if mode!='p1' and dual else [0]
def advance(level,exp,gain,table):
    exp+=int(gain)
    while str(level) in table and exp>=int(table[str(level)]['upgradeEXP']):
        exp-=int(table[str(level)]['upgradeEXP']);level+=1
    return level,exp
def binding(account):return {'uid':str(account['uid']),'username':account['username'],'slot':account['record_index']}
def load_manifest(path,account):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if data.get('account')!=binding(account):raise ValueError('清单账号或存档与当前选择不一致')
    if data.get('status')!='complete' or not data.get('kept'):raise ValueError('第一步尚未完成或没有保留宠物')
    ids=[p.get('entityId') for p in data['kept']]
    if not all(ids) or len(ids)!=len(set(ids)):raise ValueError('清单宠物ID缺失或重复')
    return data
def latest_manifest(account):
    paths=sorted((ROOT/'pet_training_batches').glob('*/manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for p in paths:
        try:data=load_manifest(p,account)
        except (ValueError,KeyError):continue
        if data.get('pending') or (data.get('harvest') or {}).get('pending') or (data.get('finalize') or {}).get('pending'):continue
        if (data.get('leveling') or {}).get('pending') or (data.get('leveling') or {}).get('status')=='failed':continue
        if data.get('status')!='complete' or not data.get('kept'):continue
        if (data.get('finalize') or {}).get('status')=='complete':continue
        return p
    raise ValueError('当前账号/存档没有可续跑的已完成第一步清单')

def recover_pending(path,account,info):
    """After an explicitly chosen reconnect, use persisted server state; never replay a request."""
    path=Path(path);data=load_manifest(path,account);state=data.get('leveling') or {}
    pending=state.get('pending')
    if not pending:return
    pets=dict((info.get('bag') or {}).get('pet') or {})
    for key in ('p1','p2'):
        p=(((info.get(key) or {}).get('equipments') or {}).get('pet') or {})
        if p.get('entityId'):pets[p['entityId']]=p
    ids=list((pending.get('pets') or {}).values())
    if not ids:return
    missing=[eid for eid in ids if eid not in pets]
    kept={p.get('entityId') for p in data.get('kept') or []}
    if missing:
        if set(ids)<=set(missing) and not (set(ids)&kept):
            state.setdefault('recoveries',[]).append({'uncertain':pending,'actual':[],'note':'待确认宠物均不在背包/出战栏且不在保留清单，按已离开处理；未重发'})
            state['pending']=None
            if state.get('error'):state.setdefault('resolved_errors',[]).append(state.pop('error'))
            atomic_json(path,data)
            return
        raise RuntimeError('无法确认超时宠物的实际状态，未恢复')
    state.setdefault('recoveries',[]).append({'uncertain':pending,'actual':[snapshot(pets[eid]) for eid in ids],'note':'未重发；从服务器实际经验续跑，超时局不计为确认完整结算局'})
    state['pending']=None
    if state.get('error'):state.setdefault('resolved_errors',[]).append(state.pop('error'))
    atomic_json(path,data)

class Leveling:
    def __init__(self,flow,info,account,path,mode,table,prepare_bonus=True,seconds=8,early_stop=False,passive_target=3,max_level=45,push_wait=0.25,mid=None):
        if passive_target not in (2,3):raise ValueError('早停目标潜能须为2或3级')
        self.flow=flow;self.info=info;self.account=account;self.path=Path(path);self.folder=self.path.parent
        self.data=load_manifest(path,account);self.slots=indices(info,mode);self.table=table
        self.prepare_bonus=prepare_bonus;self.seconds=seconds;self.known={};self.update_known()
        self.early_stop=early_stop;self.passive_target=passive_target;self.max_level=max_level;self.ceiling=self.ceiling_level();self.push_wait=push_wait
        self.current={i:self.equipped(i).get('entityId') for i in (0,1) if info.get('p'+str(i+1))}
        if not self.ceiling:raise ValueError('未读取到角色等级，无法确定早停上限')
        self.state=self.data.setdefault('leveling',{'status':'pending','mode':mode,'original':{str(i):eid for i,eid in self.current.items()},'75':{},'101':{},'rounds':{},'pending':None})
        self.mid=int(mid or self.state.get('map') or latest_stage(info))
        self.state['map']=self.mid
        if self.state.get('pending'):raise RuntimeError('上次有未确认战斗，需恢复核对后再运行，未自动重发')
        if early_stop:
            self.state.setdefault('early',{})
            key=str(self.ceiling)
            if key not in self.state:self.state[key]=dict(self.state.get('101') or {})
        self.save()
        self.push_enabled=True;self.push_skills={eid:dict(passive(self.known[eid])) for eid in (p['entityId'] for p in self.data['kept']) if eid in self.known}
        def on_upgrade(body):
            if not self.push_enabled or not isinstance(body,dict):return
            pet=body.get('data') or {};eid=pet.get('entityId')
            if eid not in self.push_skills:return
            from datetime import datetime
            previous=self.push_skills[eid];current=dict(passive(pet))
            row={'time':datetime.now().isoformat(),'route':'onPetUpgrade','body':body,'potential_changes':{k:{'before':previous.get(k,0),'after':v} for k,v in current.items() if previous.get(k,0)!=v}}
            self.push_skills[eid]=current
            with (self.folder/'leveling_pushes.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            if row['potential_changes']:
                from pet_training_log import say,potentials
                say('潜能变化','%s，服务器等级%s→%s：%s；已记录升级推送'%(eid,body.get('oldLevel','?'),body.get('newLevel','?'),potentials(pet)))
        self.upgrade_callback=on_upgrade
        if callable(getattr(flow,'on',None)):flow.on('onPetUpgrade',on_upgrade)
    def save(self):
        atomic_json(self.path,self.data)
    def log(self,event,data):
        from datetime import datetime
        row={'time':datetime.now().isoformat(),'event':event,**data}
        with (self.folder/'leveling_events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps(row,ensure_ascii=False),flush=True)
    def equipped(self,i):return (((self.info.get('p'+str(i+1)) or {}).get('equipments') or {}).get('pet') or {})
    def update_known(self):
        self.known.update((p['entityId'],p) for p in ((self.info.get('bag') or {}).get('pet') or {}).values())
        for i in (0,1):
            p=self.equipped(i)
            if p.get('entityId'):self.known[p['entityId']]=p
    def checked(self,r):
        if not isinstance(r,dict) or r.get('code')!=200 or r.get('error'):raise RuntimeError('服务器拒绝：'+str(r))
        return r
    def wallet(self):return self.checked(self.flow.request('connector.roleHandler.getUserInfo',{}))['user']
    def checkpoint(self):
        from feature_account import entry
        self.info=entry(self.flow,self.account);self.update_known()
        if self.wallet().get('ticket')!=self.state['ticket_initial']:raise RuntimeError('点券变化，停止')
    def equip(self,i,eid):
        if self.current.get(i)==eid:return
        if eid:
            r=self.checked(self.flow.request('scene.characterHandler.putOnEquip',{'entityId':eid,'type':'pet','index':i}))
            if r.get('equipEntityId')!=eid or r.get('index')!=i:raise RuntimeError('出战回包身份不符')
        elif self.current.get(i):
            self.checked(self.flow.request('scene.characterHandler.takeOffEquip',{'part':'pet','type':'pet','index':i}))
        self.current[i]=eid
    def round(self):
        from main_farm import _create,_finish
        client,created=_create(self.flow,self.mid)
        self.state['last_created']={'mid':self.mid,'rnd':created.get('rnd'),'client_rnd':client,'pet_drop_count':sum(d.get('type')=='petAttr' for d in created.get('drops') or [])};self.save()
        if created.get('consume'):raise RuntimeError('副本%d出现额外入场消耗，停止'%self.mid)
        jobs=[]
        for ordinal,drop in enumerate(created.get('drops') or []):
            if drop.get('type')!='petAttr' or drop.get('subType')!='petEXP':continue
            salt=random.randint(1,10000)
            jobs.append({'index':(int(drop.get('dropIndex',ordinal))+salt)^(int(created['rnd'])^client),'key':salt^client})
        replies={};lock=threading.Lock()
        for start in range(0,len(jobs),50):
            chunk=jobs[start:start+50];waiting={'left':len(chunk)};ready=threading.Event()
            def cb(reply,key,waiting=waiting,ready=ready):
                replies[key]=reply
                with lock:
                    waiting['left']-=1
                    if waiting['left']==0:ready.set()
            for offset,data in enumerate(chunk):
                self.flow.game.request('scene.copyHandler.syncDropInfo',data,
                                       lambda body,key=start+offset:cb(body,key))
            if not ready.wait(15):
                self.state['pickup_timeout']={'expected':len(jobs),'received':len(replies)};self.save()
                raise RuntimeError('经验拾取超时，未重发')
        gains=Counter()
        for key in range(len(jobs)):
            r=self.checked(replies.get(key))
            for g in r.get('give') or []:
                if g.get('type')=='petAttr' and g.get('subType')=='petEXP':gains[int(g.get('index',0))]+=int(g.get('count',0))
        _finish(self.flow,created,client,True)
        return gains
    def potential_now(self,eid):
        p=self.push_skills.get(eid)
        if p is None:p=dict(passive(self.known.get(eid) or {}))
        return (max([int(v) for v in p.values()] or [0]),len(p))
    def ceiling_level(self):
        levels=[int((self.info.get('p%d'%(i+1)) or {}).get('level') or 0) for i in self.slots]
        levels=[v for v in levels if v>0]
        return min(levels+[self.max_level]) if levels else self.max_level
    def early_verdict(self,eid,level):
        """达标／潜能满槽／到等级上限即停；只在早停模式使用，依据服务器升级推送。"""
        top,slots=self.potential_now(eid);cap=int((self.known.get(eid) or {}).get('capacity') or 0)
        if top>=self.passive_target:reason='target'
        elif cap and slots>=cap:reason='full'
        elif level>=self.ceiling:reason='levelcap'
        else:return None
        return {'reason':reason,'level':level,'push_max':top,'push_slots':slots,'capacity':cap}
    def stage(self,ids,target,decide=None):
        from pet_training_log import say,potentials
        key=str(target);done=self.state[key];queue=deque();active={};last_gain=''
        for eid in ids:
            if eid in done:continue
            verdict=decide(eid,int(self.known[eid]['level'])) if decide else None
            if not verdict:queue.append(eid);continue
            record=dict(verdict);record.update(potential=potentials(self.known[eid]),rounds=dict(self.state['rounds'].get(eid,{'75':0,'101':0})))
            self.state.setdefault('early',{})[eid]=record;done[eid]=snapshot(self.known[eid]);self.save()
            self.log('early_stop',{'stage':'queue','pet':snapshot(self.known[eid]),'result':record})
            say('早停','%s 起步即判定%s，不再训练；%s'%(eid,record['reason'],record['potential']))
        while queue or active:
            if (self.folder/'STOP').exists():raise RuntimeError('收到停止标记')
            for i in self.slots:
                if i not in active and queue:
                    eid=queue.popleft();p=self.known[eid]
                    if int(p['level'])>=target:
                        done[eid]=snapshot(p);self.save();continue
                    self.equip(i,eid);active[i]={'id':eid,'level':int(p['level']),'exp':int(p['petEXP'])}
                    from pet_training_log import say,potentials
                    say('出战','%dP：%s，%s级→目标%d级，%s；ID=%s'%(i+1,p.get('name','天马'),p['level'],target,potentials(p),eid))
                elif i not in active:self.equip(i,None)
            if not active:continue
            if self.prepare_bonus:
                from pet_training_bonus import ensure
                ensure(self.flow,self.info,self.state,self.log)
            started=time.monotonic();self.state['pending']={'target':target,'pets':{str(i):v['id'] for i,v in active.items()}};self.save()
            prefix=('早停：目标%d级潜能，'%self.passive_target) if decide else ('目标%d级，'%target)
            self.feedback.set('%s已确认%d局；%s；%s正在等待本局经验／结算'%(prefix,sum(sum(s.values()) for s in self.state['rounds'].values()),'；'.join('%dP %s 估算%d级'%(i+1,v['id'],v['level']) for i,v in active.items()),last_gain))
            gains=self.round()
            last_gain='上局%.2f秒，%s；'%(time.monotonic()-started,'、'.join('%dP经验+%d'%(i+1,gains[i]) for i in active))
            for i,v in active.items():
                if gains[i]<=0:raise RuntimeError('出战宠物未获得经验，停止')
                v['level'],v['exp']=advance(v['level'],v['exp'],gains[i],self.table)
                stats=self.state['rounds'].setdefault(v['id'],{});stats[key]=stats.get(key,0)+1
            self.state['pending']=None;self.save()
            if decide:time.sleep(self.push_wait)
            finished={}
            for i,v in active.items():
                if decide:
                    verdict=decide(v['id'],v['level'])
                    if verdict:finished[i]=verdict
                elif v['level']>=target:finished[i]={'reason':'level','level':v['level']}
            if finished:
                self.checkpoint()
                for i,v in list(active.items()):
                    p=self.known[v['id']]
                    if (int(p['level']),int(p['petEXP']))!=(v['level'],v['exp']):raise RuntimeError('目标节点经验核对不一致')
                    if i in finished:
                        actual=dict(passive(p));top=max([int(x) for x in actual.values()] or [0]);slots=len(actual);cap=int(p.get('capacity') or 0)
                        reason=finished[i]['reason']
                        if top>=self.passive_target:reason='target'
                        elif cap and slots>=cap:reason='full'
                        elif int(p['level'])>=target:reason='levelcap'
                        self.push_skills[v['id']]=actual
                        done[v['id']]=snapshot(p);self.save()
                        if decide:
                            record={'reason':reason,'decision':finished[i]['reason'],'level':int(p['level']),'max':top,'slots':slots,'capacity':cap,'potential':potentials(p),'rounds':dict(self.state['rounds'][v['id']])}
                            self.state.setdefault('early',{})[v['id']]=record
                            self.log('early_stop',{'stage':'round','pet':snapshot(p),'result':record})
                            say('早停','%dP %s 已确认%d级：%s，潜能%s；累计%s局；潜能格%d/%d'%(i+1,v['id'],p['level'],reason,potentials(p),sum(self.state['rounds'][v['id']].values()),slots,cap))
                        else:
                            self.log('checkpoint',{'target':target,'pet':snapshot(p),'rounds':self.state['rounds'][v['id']]})
                            from pet_training_log import say,potentials
                            say('节点核对','%dP %s 已确认%d级；累计%s局；%s；75级进度%d/%d，101级进度%d/%d'%(i+1,v['id'],p['level'],sum(self.state['rounds'][v['id']].values()),potentials(p),len(self.state['75']),len(self.data['kept']),len(self.state['101']),len(self.state.get('selected101',[]))))
                        self.equip(i,None);del active[i]
            time.sleep(max(0,self.seconds-(time.monotonic()-started)))
    def run(self):
        from pet_training_log import Feedback,say,duration
        started=time.monotonic()
        with Feedback('升级','正在准备%s宠物升级，等待服务器回复时每10秒反馈一次'%('双人双宠' if len(self.slots)==2 else '1P')) as feedback:
            self.feedback=feedback
            result=self._run()
        if self.early_stop:
            reasons=Counter(v.get('reason') for v in self.state.get('early',{}).values())
            say('升级','早停模式完成，耗时%s；达标%d只，潜能格满%d只，到%d级%d只，起步已达%d只；推送记录%s'%(duration(time.monotonic()-started),reasons['target'],reasons['full'],self.ceiling,reasons['levelcap'],reasons['preexisting'],self.folder/'leveling_pushes.jsonl'))
        else:
            say('升级','完成，耗时%s；75级%d只，101级%d只；潜能推送记录%s'%(duration(time.monotonic()-started),len(self.state['75']),len(self.state['101']),self.folder/'leveling_pushes.jsonl'))
        return result
    def _run(self):
        if self.state['status']=='complete':self.log('already_complete',{});return
        ids=[p['entityId'] for p in self.data['kept']]
        if any(eid not in self.known for eid in ids):raise RuntimeError('清单宠物有缺失，停止')
        self.state.setdefault('ticket_initial',self.wallet().get('ticket'))
        if self.state['ticket_initial'] is None:raise RuntimeError('未读取到点券余额')
        self.state.update(status='running',mode='both' if len(self.slots)==2 else 'p1');self.save()
        # Clear both slots once so an unselected pet cannot receive farm EXP.
        for i in self.current:self.equip(i,None)
        if self.early_stop:
            self.state['selected101']=[];self.save()
            from pet_training_log import say
            self.log('early_start',{'target':self.passive_target,'pets':ids,'map':self.mid,'ceiling':self.ceiling})
            say('早停','目标%d级潜能：每局按服务器升级推送判定，达标／潜能格满／到%d级（角色上限）即停；不先跑75级；副本%d'%(self.passive_target,self.ceiling,self.mid))
            self.stage(ids,self.ceiling,decide=self.early_verdict)
        else:
            self.stage(ids,75)
            selected=[eid for eid in ids if eligible101(self.state['75'][eid])]
            self.state['selected101']=selected;self.save();self.log('selected101',{'entityIds':selected})
            from pet_training_log import say
            say('筛选','75级阶段完成：%d只符合≥2级潜能，继续101级；%d只不继续'%(len(selected),len(ids)-len(selected)))
            self.stage(selected,101)
        self.state['status']='complete';self.save();self.log('completed',{'trained75':len(self.state['75']),'trained101':len(self.state['101']),'early':{eid:v.get('reason') for eid,v in self.state.get('early',{}).items()},'manifest':str(self.path)})
    def restore(self):
        self.push_enabled=False
        handlers=getattr(getattr(self.flow,'game',None),'_push_handlers',{}).get('onPetUpgrade',[])
        if self.upgrade_callback in handlers:handlers.remove(self.upgrade_callback)
        receipts=[]
        for i in self.current:
            try:self.equip(i,None)
            except Exception as exc:receipts.append({'index':i,'error':str(exc)})
        for index,eid in self.state['original'].items():
            try:self.equip(int(index),eid);receipts.append({'index':int(index),'restored':True})
            except Exception as exc:receipts.append({'index':int(index),'error':str(exc)})
        self.state['restore']=receipts;self.save()

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--manifest',type=Path);ap.add_argument('--mode',choices=['auto','p1','both'],default='auto');ap.add_argument('--no-exp-buffs',action='store_true');ap.add_argument('--early-stop',action='store_true');ap.add_argument('--target-passive',type=int,choices=[2,3],default=3);ap.add_argument('--max-level',type=int,default=45);ap.add_argument('--apply',action='store_true');ap.add_argument('--seconds',type=float,default=8);ap.add_argument('--map',type=int,default=0);args=ap.parse_args()
    if not args.apply:
        print('预演：自动识别单/双人档，或仅1P；清单宠物先到75级，潜能≥2者再101级。根据每只实际获得的经验计算节点，不套用其他账号固定局数；仅目标节点核对。' if not args.early_stop else '预演：早停模式，直接训练到%d级潜能达标、潜能格满或到角色等级／%d级封顶即停，不先跑75级。'%(args.target_passive,args.max_level));return
    import feature_account as ta
    from pet_utilities import table
    path=args.manifest or latest_manifest(ta.ACCT);load_manifest(path,ta.ACCT)
    flow=None;job=None
    try:
        from pet_training_log import Feedback
        with Feedback('连接','正在登录当前账号和所选存档，等待服务器响应'):
            flow=ta.connect(ta.ACCT);info=ta.entry(flow,ta.ACCT)
        job=Leveling(flow,info,ta.ACCT,path,args.mode,table('PetEXP'),prepare_bonus=not args.no_exp_buffs,seconds=args.seconds,early_stop=args.early_stop,passive_target=args.target_passive,max_level=args.max_level,mid=args.map or None);job.run()
    except Exception as exc:
        from pet_training_log import connection_notice
        connection_notice(exc,path)
        if job:job.state.update(status='failed',error=str(exc));job.save();job.log('stopped_error',{'error':str(exc)})
        raise
    finally:
        if job:job.restore()
        if flow:flow.disconnect()

if __name__=='__main__':main()
