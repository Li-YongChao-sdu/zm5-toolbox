"""潜能培养第一步：仅按capacity>=4抓天马，保存账号/存档绑定的宠物清单。"""
import argparse,json,os,random,time
from datetime import datetime
from pathlib import Path
from bag_warehouse import quantity
from pet_training_storage import atomic_json

ROOT=Path(__file__).resolve().parent
GOURD=101017001
PURCHASE_COUNT=10000
PET_IDS={'170111101','170121101'}

def qualifies(pet):
    return str(pet.get('id')) in PET_IDS and int(pet.get('capacity',0))>=4

def snapshot(pet):
    return {k:pet.get(k) for k in ('entityId','id','name','nickName','level','petEXP','quality','sex','capacity','physical','bone','hpQualification','atkQualification','defQualification','reHpQualification','skill')}

def capture_ok(reply):
    return isinstance(reply,dict) and reply.get('code')==200 and type(reply.get('success')) is int and reply['success'] in (0,1)

def occupied_pets(info):
    ids=set(((info.get('bag') or {}).get('pet') or {}))
    for key in ('p1','p2'):
        pet=(((info.get(key) or {}).get('equipments') or {}).get('pet') or {})
        if pet.get('entityId'):ids.add(pet['entityId'])
    return len(ids)

class Capture:
    @classmethod
    def resume(cls,flow,info,account,path,password=''):
        self=cls.__new__(cls);self.flow=flow;self.info=info;self.account=account;self.password=password
        self.path=Path(path);self.folder=self.path.parent;self.active=None
        self.data=json.loads(self.path.read_text(encoding='utf-8-sig'))
        expected={'uid':str(account['uid']),'username':account['username'],'slot':account['record_index']}
        if self.data.get('account')!=expected:raise ValueError('续抓清单账号或存档不一致')
        if self.data.get('pending'):self.require_password(self.user())
        self.resolve_pending()
        pets=((info.get('bag') or {}).get('pet') or {})
        if any(p['entityId'] not in pets or not qualifies(pets[p['entityId']]) for p in self.data['kept']):raise RuntimeError('已保留宠物缺失或条件变化，停止续抓')
        if self.data.get('error'):self.data.setdefault('resolved_errors',[]).append(self.data.pop('error'))
        self.data['status']='running';self.save();return self
    def __init__(self,flow,info,account,count,folder,password=''):
        self.flow=flow;self.info=info;self.account=account;self.password=password
        self.folder=folder;folder.mkdir(parents=True,exist_ok=False)
        self.path=folder/'manifest.json';self.active=None
        self.data={'version':1,'stage':'capture','status':'running',
            'account':{'uid':str(account['uid']),'username':account['username'],'slot':account['record_index']},
            'target_count':count,'filter':{'pet':'天马','capacity_min':4},
            'initial_ids':list((info.get('bag') or {}).get('pet') or {}),
            'kept':[],'released':[],'attempts':0,'purchases':[],'pending':None}
        self.save()
    def save(self):
        atomic_json(self.path,self.data)
    def resolve_pending(self):
        """断线后核对未确认的捕捉请求：只按背包实际结果判定，不重发捕捉。"""
        pending=self.data.get('pending') or {}
        if not pending:return ''
        if pending.get('route')!='scene.petHandler.capture':
            raise RuntimeError('未确认请求（%s）无法只凭背包核对，停止自动续跑'%pending.get('route'))
        pets=((self.info.get('bag') or {}).get('pet') or {})
        known=set(self.data.get('initial_ids') or [])
        known.update(p['entityId'] for p in (self.data.get('kept') or []))
        known.update(p['entityId'] for p in (self.data.get('released') or []))
        newcomers=[pet for eid,pet in pets.items() if eid not in known]
        if len(newcomers)>1:
            raise RuntimeError('断线后出现%d只身份未知的新宠，需人工核对：%s'%(len(newcomers),','.join(str(p.get('entityId')) for p in newcomers)))
        result='none';pet=None
        if newcomers:
            pet=newcomers[0];eid=pet.get('entityId');record=snapshot(pet)
            if str(pet.get('id')) not in PET_IDS or int(pet.get('level') or 0)!=1:
                raise RuntimeError('断线后发现非本批捕捉的新宠，需人工核对：'+str(eid))
            if qualifies(pet):
                self.data['kept'].append(record);result='kept'
            else:
                if pet.get('nickName') or pet.get('equipments'):raise RuntimeError('断线新宠有昵称或装备，不放生：'+str(eid))
                self.release(eid)
                pets.pop(eid,None);self.data['released'].append(record);result='released'
            self.log('recovered_pet',{'result':result,'pet':record,'note':'断线后按背包实际结果核对，未重发捕捉'})
        else:
            self.log('recovered_capture',{'result':'none','note':'背包无身份未知新宠，按本次捕捉未成功处理（葫芦可能已消耗），不重发'})
        self.data['pending']=None
        self.data.setdefault('recoveries',[]).append({'pending':pending,'result':result,'pet':snapshot(pet) if pet else None,'note':'按服务器背包核对，未重发捕捉'})
        self.save()
        return result
    def log(self,event,data):
        row={'time':datetime.now().isoformat(),'event':event,**data}
        with (self.folder/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps(row,ensure_ascii=False),flush=True)
    def read(self):
        from feature_account import entry
        self.info=entry(self.flow,self.account);return self.info
    def checked(self,reply):
        if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):raise RuntimeError('服务器拒绝：'+str(reply))
        return reply
    def require_password(self,wallet):
        if ((wallet.get('secondPassword') or {}).get('havePwd')) and not self.password:
            raise RuntimeError('该存档已设置二级密码，但本次密码为空：未抓宠、未消耗葫芦；请填写正确二级密码后重跑')
    def release(self,eid):
        reply=self.request('scene.petHandler.free',{'entityId':eid,**({'password':self.password} if self.password else {})})
        if isinstance(reply,dict) and reply.get('code')==502:
            raise RuntimeError('放生被拒绝（二级密码错误）：%s 仍在背包；请填写正确二级密码后重跑本批，未重试该请求'%eid)
        return self.checked(reply)
    def request(self,route,params):
        self.data['pending']={'route':route,'params':{k:v for k,v in params.items() if k!='password'}};self.save()
        reply=self.flow.request(route,params)
        self.data['pending']=None;self.save();self.log('reply',{'route':route,'reply':reply})
        return reply
    def user(self):return self.checked(self.flow.request('connector.roleHandler.getUserInfo',{}))['user']
    def spirit(self):
        for obj in (self.info,self.info.get('p1') or {}):
            if isinstance(obj.get('spirit'),(int,float)):return int(obj['spirit'])
        raise RuntimeError('未读取到灵魂余额，不购买')
    def close_copy(self):
        if self.active:
            created,client=self.active;self.active=None
            self.checked(self.request('scene.copyHandler.finishSingleCopy',{'win':0,'rnd':int(created['rnd'])^client,'star':0}))
    def buy(self):
        from pet_utilities import table
        self.close_copy();self.read()
        cfg=table('Shop')['1']
        if cfg.get('consume_type')!='coin' or cfg.get('consume_subType')!='spirit' or cfg.get('extTicket') or str(cfg.get('sell_subType'))!=str(GOURD) or int(cfg.get('sell_count',1))!=1:
            raise RuntimeError('木灵葫芦灵魂商品配置不符，停止')
        cost=int(cfg['consume_count'])*PURCHASE_COUNT
        before=self.spirit();before_num=quantity(self.info,'bag',GOURD)
        if before<cost:raise RuntimeError('灵魂不足购买10000个木灵葫芦，停止')
        wallet=self.user();ticket=wallet.get('ticket')
        if ticket is None:raise RuntimeError('未读取到点券余额，停止')
        self.checked(self.request('scene.shopHandler.buy',{'shopId':1,'count':PURCHASE_COUNT,'password':self.password}))
        self.read();latest=self.user();after=self.spirit();after_num=quantity(self.info,'bag',GOURD)
        receipt={'count':PURCHASE_COUNT,'gourds_before':before_num,'gourds_after':after_num,'spirit_before':before,'spirit_after':after,'ticket_before':ticket,'ticket_after':latest.get('ticket')}
        self.data['purchases'].append(receipt);self.save();self.log('gourd_purchase',receipt)
        if after_num-before_num!=PURCHASE_COUNT or before-after!=cost or latest.get('ticket')!=ticket:raise RuntimeError('购买到账或货币核对异常，停止')
    def run(self):
        from pet_training_log import Feedback
        with Feedback('抓天马','正在检查背包空格、葫芦和点券；只处理本批新宠') as feedback:
            self.feedback=feedback
            return self._run()
    def _run(self):
        from pet_training_log import say,duration,potentials
        started=time.monotonic()
        bag=self.info.get('bag') or {};limit=int(bag.get('petMaxNum') or 0)
        occupied=occupied_pets(self.info);gourds=quantity(self.info,'bag',GOURD)
        available=limit-occupied
        required=self.data['target_count']-len(self.data['kept'])
        if not limit or available<required:raise RuntimeError('宠物空格不足目标数量，请先清理；不会放生已有宠物')
        wallet=self.user();self.require_password(wallet)
        self.data.setdefault('ticket_before',wallet.get('ticket'));self.save()
        if self.data['ticket_before'] is None:raise RuntimeError('未读取到点券余额')
        say('抓天马','目标%d只；已有%d只；空格%d；木灵葫芦%d；点券%d'%(self.data['target_count'],len(self.data['kept']),available,gourds,self.data['ticket_before']))
        while len(self.data['kept'])<self.data['target_count']:
            self.feedback.set('已保留%d/%d只，已尝试%d次；正在捕捉／核对／清理新宠'%(len(self.data['kept']),self.data['target_count'],self.data['attempts']))
            if (self.folder/'STOP').exists():raise RuntimeError('收到停止标记')
            if gourds<=0:
                self.buy();bag=self.info.get('bag') or {};limit=int(bag.get('petMaxNum') or 0)
                occupied=occupied_pets(self.info);gourds=quantity(self.info,'bag',GOURD)
            if occupied>=limit:raise RuntimeError('宠物背包已满，停止')
            if self.active is None:
                from main_farm import _create
                client,created=_create(self.flow,10001);self.active=(created,client)
                if created.get('consume'):raise RuntimeError('御马监出现额外入场消耗，停止')
            reply=self.request('scene.petHandler.capture',{'itemId':GOURD,'petId':170111101})
            self.data['attempts']+=1
            if reply.get('code')==500 and '灵宠仓库已满' in str(reply.get('error') or ''):
                if not self.data['kept']:raise RuntimeError('灵宠仓库已满且本批未保留宠物，请先放生再抓')
                self.data['limit']='warehouse_full';self.log('capture_limited',{'kept':len(self.data['kept']),'error':reply.get('error')})
                say('抓天马','灵宠仓库已满：停止本批抓捕；先训练并放生已保留%d只，腾出空间后再抓'%len(self.data['kept']))
                break
            if not capture_ok(reply):raise RuntimeError('捕捉异常，未重试：'+str(reply))
            consumed=sum(int(c.get('count') or 0) for c in reply.get('consume') or [] if c.get('type')=='item' and str(c.get('subType'))==str(GOURD))
            if consumed!=1:raise RuntimeError('捕捉葫芦扣除数量异常，停止')
            gourds-=1
            if reply['success']==1:
                caught=next((g.get('data') or {} for g in reply.get('give') or [] if g.get('type')=='pet'),{})
                eid=caught.get('entityId')
                if not eid or eid in self.data['initial_ids']:raise RuntimeError('新增宠物身份核对异常，停止')
                record=snapshot(caught)
                if qualifies(caught):
                    self.data['kept'].append(record);occupied+=1;self.save()
                    self.log('kept',{'pet':record,'kept_count':len(self.data['kept']),'target':self.data['target_count']})
                    say('抓天马','保留%d/%d：%s，%s星，潜力%s，%s；ID=%s'%(len(self.data['kept']),self.data['target_count'],caught.get('name','天马'),caught.get('quality','?'),caught.get('capacity','?'),potentials(caught),eid))
                else:
                    if caught.get('nickName') or caught.get('equipments'):raise RuntimeError('新宠有昵称或装备，不放生')
                    self.release(eid)
                    occupied-=1
                    self.data['released'].append(record);self.save();self.log('released',{'pet':record,'reason':'仅放生本轮新抓、潜力不足4的宠物'})
            self.save();time.sleep(.05)
        self.close_copy();self.read();after=self.user()
        pets=((self.info.get('bag') or {}).get('pet') or {})
        for record in self.data['kept']:
            if record['entityId'] not in pets:raise RuntimeError('保留宠物未在背包中，停止：'+record['entityId'])
        for record in self.data['released']:
            if record['entityId'] in pets:raise RuntimeError('放生后仍存在，停止：'+record['entityId'])
        if quantity(self.info,'bag',GOURD)!=gourds:raise RuntimeError('捕捉葫芦数量核对异常，停止')
        self.data.update(status='complete',ticket_after=after.get('ticket'));self.save()
        if after.get('ticket')!=self.data['ticket_before']:raise RuntimeError('点券核对异常')
        self.log('completed',{'kept':len(self.data['kept']),'attempts':self.data['attempts'],'manifest':str(self.path),'entityIds':[p['entityId'] for p in self.data['kept']]})
        say('抓天马','完成：保留%d只，尝试%d次，清理不合格新宠%d只，耗时%s；点券%s→%s；清单%s'%(len(self.data['kept']),self.data['attempts'],len(self.data['released']),duration(time.monotonic()-started),self.data['ticket_before'],self.data['ticket_after'],self.path))

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--count',type=int,default=10);ap.add_argument('--account',default='');ap.add_argument('--slot',type=int);ap.add_argument('--resume',type=Path);ap.add_argument('--auto-reconnect',action='store_true');ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    if args.count<1:ap.error('目标数量必须大于0')
    if not args.apply:
        print(f'预演：抓天马{args.count}只，仅要求潜力≥4；木灵葫芦耗尽时用灵魂购买10000个。不处理已有宠物；新抓不合格宠物放生；保留宠物ID写入独立清单。--resume 续抓时先核对背包，不重发上次未确认捕捉。');return
    import feature_account as ta
    if args.account:
        source=json.loads((ROOT/'accounts'/(args.account+'.json')).read_text(encoding='utf-8-sig'))
        ta.ACCT=dict(uid=source['uid'],username=source['username'],cookies=source['cookies'],record_index=int(source.get('record_index') or 0))
        if args.slot is not None:ta.ACCT['record_index']=args.slot
        print('指定账号：%s（槽%s）'%(source['username'],ta.ACCT['record_index']),flush=True)
    from pet_training_log import Feedback,say,is_connection_error
    flow=None;job=None;path=args.resume;attempt=0
    folder=(path.parent if path else ROOT/'pet_training_batches'/datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    try:
        while True:
            fresh=None
            try:
                with Feedback('连接','正在登录当前账号和所选存档，等待服务器响应'):
                    fresh=ta.connect(ta.ACCT);actual=ta.entry(fresh,ta.ACCT)
                if flow:
                    try:flow.disconnect()
                    except Exception:pass
                flow=fresh;fresh=None
                password=os.environ.get('ZM5_PET_CAPTURE_PASSWORD','').strip()
                if path:
                    job=Capture.resume(flow,actual,ta.ACCT,path,password);print('续抓清单：'+str(path),flush=True)
                else:
                    job=Capture(flow,actual,ta.ACCT,args.count,folder,password);path=job.path;print('宠物清单：'+str(path),flush=True)
                job.run();break
            except Exception as exc:
                if fresh:
                    try:fresh.disconnect()
                    except Exception:pass
                if job:
                    job.data.update(status='failed',error=str(exc));job.save();job.log('stopped_error',{'error':str(exc)})
                if not (args.auto_reconnect and is_connection_error(exc)):raise
                attempt+=1;delay=min(60,10*attempt)
                say('自动重连','连接异常：%s；%d秒后第%d次重连，继续本批抓宠，不重发上次未确认的捕捉。'%(exc,delay,attempt))
                for _ in range(delay):
                    if job and (job.folder/'STOP').exists():raise RuntimeError('收到停止标记')
                    time.sleep(1)
                if flow:
                    try:flow.disconnect()
                    except Exception:pass
                flow=None
    except Exception as exc:
        if job:job.data.update(status='failed',error=str(exc));job.save();job.log('stopped_error',{'error':str(exc)})
        raise
    finally:
        if job and job.active and not job.data.get('pending'):
            try:job.close_copy()
            except Exception as exc:job.log('copy_close_error',{'error':str(exc)})
        if flow:flow.disconnect()

if __name__=='__main__':main()
