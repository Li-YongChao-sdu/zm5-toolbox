"""第三步筛选及三步循环：只按本批清单放生，保留最高潜能>=3的宠物。"""
import argparse,hashlib,json,os,time
from pathlib import Path
from datetime import datetime
from pet_training_capture import Capture,ROOT,snapshot
from pet_training_level import Leveling,load_manifest,latest_manifest,binding,passive
from pet_training_storage import atomic_json

def keep_pet(pet,minimum=3):return max([int(v) for v in passive(pet).values()] or [0])>=minimum
def atomic(path,data):
    atomic_json(path,data)

class Finalize:
    def __init__(self,flow,info,account,path,password=''):
        self.password=password
        self.flow=flow;self.info=info;self.account=account;self.path=Path(path)
        self.data=load_manifest(path,account)
        self.minimum=int(self.data.get('retain_min_potential',3))
        if self.minimum not in (2,3):raise ValueError('保留潜能等级须为2或3')
        if self.data.get('pending') or self.data.get('leveling',{}).get('pending'):raise RuntimeError('本批有未确认请求，禁止放生')
        if self.data.get('harvest',{}).get('pending'):raise RuntimeError('本批遗忘结果未确认，禁止放生')
        if self.data.get('leveling',{}).get('status')!='complete':raise ValueError('第二步尚未完成，禁止放生')
        self.state=self.data.setdefault('finalize',{'status':'pending','retained':[],'released':[],'pending':None})
        if self.state.get('pending'):raise RuntimeError('上次放生结果未确认，禁止自动重发')
        self.save()
    def save(self):atomic(self.path,self.data)
    def log(self,event,data):
        row={'time':datetime.now().isoformat(),'event':event,**data}
        with (self.path.parent/'finalize_events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps(row,ensure_ascii=False),flush=True)
    def checked(self,reply):
        if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):raise RuntimeError('服务器拒绝：'+str(reply))
        return reply
    def user(self):return self.checked(self.flow.request('connector.roleHandler.getUserInfo',{}))['user']
    def read(self):
        from feature_account import entry
        self.info=entry(self.flow,self.account)
    def retain(self,pet):
        record=snapshot(pet);eid=record['entityId']
        self.state['retained']=[p for p in self.state['retained'] if p['entityId']!=eid]+[record];self.save()
        key=hashlib.sha256((str(self.account['uid'])+':'+str(self.account['record_index'])).encode()).hexdigest()[:20]
        path=ROOT/'pet_training_retained'/(key+'.json')
        index=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'account':binding(self.account),'pets':{}}
        if index.get('account')!=binding(self.account):raise RuntimeError('累计保留清单绑定异常')
        index['pets'][eid]={'pet':record,'manifest':str(self.path),'retained_at':datetime.now().isoformat()};atomic(path,index)
        self.log('retained',{'pet':record,'index':str(path)})
    def run(self):
        from pet_training_log import Feedback
        with Feedback('保留／放生','正在检查本批宠物身份及保留标准') as feedback:
            self.feedback=feedback
            return self._run()
    def _run(self):
        from pet_training_log import say,potentials
        if self.state['status']=='complete':self.log('already_finalized',{});return self.state
        self.read()
        bag=((self.info.get('bag') or {}).get('pet') or {})
        batch={item['entityId'] for item in self.data['kept']}
        for index in (0,1):
            eid=(((self.info.get('p%d'%(index+1)) or {}).get('equipments') or {}).get('pet') or {}).get('entityId')
            if eid and eid in batch and not keep_pet(bag.get(eid) or {},self.minimum):
                self.checked(self.flow.request('scene.characterHandler.takeOffEquip',{'part':'pet','type':'pet','index':index}))
                self.read();bag=((self.info.get('bag') or {}).get('pet') or {})
        protected=set(self.data.get('initial_ids') or [])
        protected.update(eid for eid in self.data['leveling'].get('original',{}).values() if eid)
        for key in ('p1','p2'):
            p=(((self.info.get(key) or {}).get('equipments') or {}).get('pet') or {})
            if p.get('entityId'):protected.add(p['entityId'])
        released={p['entityId'] for p in self.state['released']};plan=[]
        for initial in self.data['kept']:
            eid=initial['entityId']
            if eid in released:continue
            pet=bag.get(eid)
            if not pet:raise RuntimeError('清单宠物不在背包：'+eid+'；停止，不猜测处理')
            if str(pet.get('id'))!=str(initial.get('id')):raise RuntimeError('宠物身份不符')
            if not keep_pet(pet,self.minimum) and (eid in protected or pet.get('nickName') or pet.get('equipments')):
                raise RuntimeError('待放生宠物受保护、有昵称或装备：'+eid)
            plan.append((eid,pet,keep_pet(pet,self.minimum)))
        ticket=self.user().get('ticket')
        if ticket is None:raise RuntimeError('未读取到点券余额')
        self.state.update(status='running',ticket_before=ticket);self.save()
        for eid,pet,keep in plan:
            if (self.path.parent/'STOP').exists():raise RuntimeError('收到停止标记')
            self.feedback.set('正在%s本批宠物%s，当前保留%d只／放生%d只'%('保留' if keep else '放生',eid,len(self.state['retained']),len(self.state['released'])))
            if keep:
                say('保留','%s：%s，达到≥%d级标准'%(eid,potentials(pet),self.minimum));self.retain(pet);continue
            say('放生','%s：%s，未达≥%d级标准；只处理本批新宠'%(eid,potentials(pet),self.minimum))
            self.state['pending']={'entityId':eid,'before':snapshot(pet)};self.save()
            reply=self.flow.request('scene.petHandler.free',{'entityId':eid,**({'password':self.password} if self.password else {})});self.log('release_reply',{'entityId':eid,'reply':reply})
            self.checked(reply);self.read()
            if eid in ((self.info.get('bag') or {}).get('pet') or {}):raise RuntimeError('放生后仍存在，未重试')
            self.state['released'].append(snapshot(pet));self.state['pending']=None;self.save()
        after=self.user().get('ticket');self.state['ticket_after']=after;self.save()
        if after!=ticket:raise RuntimeError('点券变化，停止循环')
        self.state['status']='complete';self.save()
        self.log('finalized',{'retained':len(self.state['retained']),'released':len(self.state['released']),'manifest':str(self.path)})
        return self.state

def run_cycle(flow,info,account,count,mode,cycles,manifest,password,table,prepare_bonus=True,prepare_space=None,retain_min=3,harvest=False,seconds=8,early_stop=False,passive_target=3,map_id=None):
    from pet_training_log import say,duration,Feedback
    if retain_min not in (2,3):raise ValueError('保留潜能等级须为2或3')
    runfolder=ROOT/'pet_training_cycles'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    runfolder.mkdir(parents=True,exist_ok=False)
    state={'account':binding(account),'status':'running','count_per_batch':count,'mode':mode,'cycles_limit':cycles,'retain_min_potential':retain_min,'harvest_enabled':harvest,'early_stop':early_stop,'target_passive':passive_target if early_stop else None,'batches':[],'started_at':datetime.now().isoformat()}
    statepath=runfolder/'cycle.json';atomic(statepath,state)
    print('循环记录：'+str(statepath),flush=True)
    try:
        current=manifest
        if not current:
            try:
                candidate=latest_manifest(account);data=load_manifest(candidate,account)
                if data.get('finalize',{}).get('status')!='complete':current=candidate
            except ValueError:pass
        while not cycles or len(state['batches'])<cycles:
            try:
                cycle_started=time.monotonic();timing={'started_at':datetime.now().isoformat()}
                say('刷益灵花','开始第%d/%s轮：每批%d只，出战模式%s，%s，剩余潜能≥%d级保留%s'%(len(state['batches'])+1,cycles or '不限',count,mode,'遗忘取花' if harvest else '仅培养保留',retain_min,('，早停判定%d级潜能'%passive_target) if early_stop else ''))
                if (runfolder/'STOP').exists():raise RuntimeError('收到循环停止标记')
                from feature_account import entry
                with Feedback('读取存档','正在确认本轮存档及背包状态'):info=entry(flow,account)
                if current is None:
                    if prepare_space:info=prepare_space(info,count)
                    folder=ROOT/'pet_training_batches'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                    capture=Capture(flow,info,account,count,folder,password)
                    state['active_manifest']=str(capture.path);atomic(statepath,state)
                    capture_started=time.monotonic()
                    try:capture.run()
                    except Exception as exc:
                        capture.data.update(status='failed',error=str(exc));capture.save();raise
                    finally:
                        if capture.active and not capture.data.get('pending'):capture.close_copy()
                    current=capture.path;info=capture.info
                    timing['capture_seconds']=round(time.monotonic()-capture_started,3)
                state['active_manifest']=str(current);atomic(statepath,state)
                level=Leveling(flow,info,account,current,mode,table,prepare_bonus=prepare_bonus,seconds=seconds,early_stop=early_stop,passive_target=passive_target,mid=map_id)
                level.data['retain_min_potential']=retain_min;level.save()
                level_started=time.monotonic()
                try:level.run()
                except Exception as exc:
                    level.state.update(status='failed',error=str(exc));level.save();raise
                finally:level.restore()
                if any('error' in r for r in level.state.get('restore',[])):raise RuntimeError('恢复原出战宠物失败，停止循环')
                timing['level_seconds']=round(time.monotonic()-level_started,3)
                info=entry(flow,account)
                flower_count=0
                if harvest:
                    from pet_training_harvest import Harvest
                    harvest_started=time.monotonic();gather=Harvest(flow,info,account,current,password)
                    flower_count=gather.run()['flowers'];info=gather.info
                    timing['harvest_seconds']=round(time.monotonic()-harvest_started,3)
                finalize_started=time.monotonic();finalize=Finalize(flow,info,account,current,password);result=finalize.run();info=finalize.info
                timing.update(finalize_seconds=round(time.monotonic()-finalize_started,3),total_seconds=round(time.monotonic()-cycle_started,3),finished_at=datetime.now().isoformat())
                state['batches'].append({'manifest':str(current),'map':level.mid,'retained':len(result['retained']),'released':len(result['released']),'flowers':flower_count,'early':{eid:v.get('reason') for eid,v in (level.state.get('early') or {}).items()},'timing':timing})
                atomic(statepath,state);current=None
                print('本轮完成：益灵花%d朵，保留%d只，放生%d只；累计完成%d轮、益灵花%d朵'%(flower_count,len(result['retained']),len(result['released']),len(state['batches']),sum(b.get('flowers',0) for b in state['batches'])),flush=True)
                say('耗时汇总','第%d轮：抓宠%s，升级%s，遗忘%s，筛选%s，总耗时%s；记录%s'%(len(state['batches']),duration(timing.get('capture_seconds',0)),duration(timing['level_seconds']),duration(timing.get('harvest_seconds',0)),duration(timing['finalize_seconds']),duration(timing['total_seconds']),statepath))
            except Exception as exc:
                from pet_training_log import is_connection_error
                if not is_connection_error(exc):raise
                # 只恢复已持久化且可核对的阶段；不重放未确认的资源操作。
                active=state.get('active_manifest')
                if active:
                    data=json.loads(Path(active).read_text(encoding='utf-8-sig'))
                    if data.get('pending') or (data.get('harvest') or {}).get('pending') or (data.get('finalize') or {}).get('pending'):
                        say('自动重连','存在未确认的抓宠/购买/遗忘/放生操作，无法仅凭宠物经验核对；已保留记录，停止自动续跑。')
                        raise
                    current=Path(active)
                try:flow.disconnect()
                except Exception:pass
                attempt=0
                while True:
                    if (runfolder/'STOP').exists():raise RuntimeError('收到循环停止标记')
                    attempt+=1;delay=min(60,10*attempt)
                    say('自动重连','连接异常：%s；%d秒后第%d次重连，同一批次继续，不重新抓宠。'%(exc,delay,attempt))
                    for _ in range(delay):
                        if (runfolder/'STOP').exists():raise RuntimeError('收到循环停止标记')
                        time.sleep(1)
                    fresh=None
                    try:
                        import feature_account as ta
                        with Feedback('自动重连','正在重新登录并读取服务器实际进度'):
                            fresh=ta.connect(account);actual=ta.entry(fresh,account)
                        if current:
                            data=json.loads(Path(current).read_text(encoding='utf-8-sig'))
                            if data.get('status')!='complete':
                                raise RuntimeError('断线批次抓宠尚未完成，需要核对抓宠清单，停止自动续跑')
                            from pet_training_level import recover_pending
                            recover_pending(current,account,actual)
                        flow=fresh;info=actual
                        state.setdefault('reconnections',[]).append({'time':datetime.now().isoformat(),'attempt':attempt,'manifest':str(current) if current else None})
                        atomic(statepath,state)
                        say('自动重连','已恢复连接并核对宠物实际经验；继续原批次，不补发上次未确认战斗。')
                        break
                    except Exception as retry_error:
                        if fresh:
                            try:fresh.disconnect()
                            except Exception:pass
                        if not is_connection_error(retry_error):raise
                        say('自动重连','第%d次未成功：%s；将继续等待重连。'%(attempt,retry_error))
                continue
        state.update(status='complete',finished_at=datetime.now().isoformat());atomic(statepath,state)
    except Exception as exc:
        from pet_training_log import connection_notice
        connection_notice(exc,state.get('active_manifest'))
        say('异常停止','%s；已保留现场记录%s，未自动重发未确认请求'%(exc,statepath))
        state.update(status='stopped',error=str(exc));atomic(statepath,state);raise
    finally:
        try:flow.disconnect()
        except Exception:pass

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--action',choices=['finalize','cycle'],default='finalize');ap.add_argument('--manifest',type=Path);ap.add_argument('--mode',choices=['auto','p1','both'],default='auto');ap.add_argument('--count',type=int,default=10);ap.add_argument('--cycles',type=int,default=0);ap.add_argument('--no-exp-buffs',action='store_true');ap.add_argument('--retain-min',type=int,choices=[2,3],default=3);ap.add_argument('--harvest',action='store_true');ap.add_argument('--early-stop',action='store_true');ap.add_argument('--target-passive',type=int,choices=[2,3],default=3);ap.add_argument('--apply',action='store_true');ap.add_argument('--seconds',type=float,default=8);ap.add_argument('--account',default='');ap.add_argument('--slot',type=int);ap.add_argument('--map',type=int,default=0);args=ap.parse_args()
    if args.count<1 or args.cycles<0:ap.error('数量须大于0；轮数0表示持续循环')
    if not args.apply:
        print('预演：每批%d只，%s出战，循环%s轮；抓宠→%s→%s→按剩余潜能≥%d级保留，其余本批放生。只处理本批ID，不处理原有宠物。'%(args.count,args.mode,args.cycles or '持续','早停判定%d级潜能（达标／潜能格满／101级即停）'%args.target_passive if args.early_stop else '75级→已有≥2级潜能者101级','按VIP返还遗忘≥3级潜能换益灵花，消耗去灵花且不补购' if args.harvest else '不遗忘潜能',args.retain_min));return
    import feature_account as ta
    if args.account:
        source=json.loads((ROOT/'accounts'/(args.account+'.json')).read_text(encoding='utf-8-sig'))
        ta.ACCT=dict(uid=source['uid'],username=source['username'],cookies=source['cookies'],record_index=int(source.get('record_index') or 0))
        if args.slot is not None:ta.ACCT['record_index']=args.slot
        print('指定账号：%s（槽%s）'%(source['username'],ta.ACCT['record_index']),flush=True)
    from pet_utilities import table
    flow=None
    try:
        from pet_training_log import Feedback
        with Feedback('连接','正在登录当前账号和所选存档，等待服务器响应'):
            flow=ta.connect(ta.ACCT);info=ta.entry(flow,ta.ACCT)
        if args.action=='finalize':
            path=args.manifest or latest_manifest(ta.ACCT)
            data=load_manifest(path,ta.ACCT)
            if data.get('finalize',{}).get('status')!='complete':
                data['retain_min_potential']=args.retain_min;atomic(path,data)
                if args.harvest:
                    from pet_training_harvest import Harvest
                    gather=Harvest(flow,info,ta.ACCT,path,os.environ.get('ZM5_PET_CAPTURE_PASSWORD',''));gather.run();info=gather.info
            job=Finalize(flow,info,ta.ACCT,path,os.environ.get('ZM5_PET_CAPTURE_PASSWORD',''))
            try:job.run()
            except Exception as exc:job.state.update(status='failed',error=str(exc));job.save();raise
        else:run_cycle(flow,info,ta.ACCT,args.count,args.mode,args.cycles,args.manifest,os.environ.get('ZM5_PET_CAPTURE_PASSWORD',''),table('PetEXP'),prepare_bonus=not args.no_exp_buffs,retain_min=args.retain_min,harvest=args.harvest,seconds=args.seconds,early_stop=args.early_stop,passive_target=args.target_passive,map_id=args.map or None)
    except Exception as exc:
        if args.action!='cycle' or flow is None:
            from pet_training_log import connection_notice
            connection_notice(exc,args.manifest)
        raise
    finally:
        if flow:flow.disconnect()

if __name__=='__main__':main()
