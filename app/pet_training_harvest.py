"""本批天马遗忘高等级潜能，核对去灵花及益灵花；不购买遗忘材料。"""
import json
from datetime import datetime
from pathlib import Path
from bag_warehouse import quantity
from pet_training_capture import snapshot
from pet_training_level import load_manifest,passive
from pet_training_storage import atomic_json

def return_count(info,level):
    from pet_utilities import table
    vip=int((info.get('vip') or {}).get('level',0))
    cfg=table('VIP').get(str(vip))
    if not cfg:raise RuntimeError('缺少当前VIP返还配置')
    values=[int(x) for x in str(cfg['petPerksReturnCount']).split(';')]
    return values[min(int(level),len(values)-1)]

class Harvest:
    def __init__(self,flow,info,account,path,password=''):
        self.flow=flow;self.info=info;self.account=account;self.path=Path(path);self.password=password
        self.data=load_manifest(path,account)
        if self.data.get('pending') or self.data.get('leveling',{}).get('pending'):raise RuntimeError('有未确认请求，禁止遗忘')
        if self.data.get('leveling',{}).get('status')!='complete':raise RuntimeError('升级未完成，禁止遗忘')
        if self.data.get('finalize',{}).get('status')=='complete':raise RuntimeError('本批已处理完成，不再遗忘')
        self.state=self.data.setdefault('harvest',{'status':'pending','records':[],'pending':None,'flowers':0})
        if self.state.get('pending'):raise RuntimeError('上次遗忘未确认，禁止重发；请先核对记录')
    def save(self):
        atomic_json(self.path,self.data)
    def checked(self,r):
        if not isinstance(r,dict) or r.get('code')!=200 or r.get('error'):raise RuntimeError('遗忘失败：'+str(r))
        return r
    def wallet(self):return self.checked(self.flow.request('connector.roleHandler.getUserInfo',{}))['user']
    def read(self):
        from feature_account import entry
        self.info=entry(self.flow,self.account)
    def log(self,event,data):
        row={'time':datetime.now().isoformat(),'event':event,**data}
        with (self.path.parent/'harvest_events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        print(json.dumps(row,ensure_ascii=False),flush=True)
    def run(self):
        from pet_training_log import Feedback
        with Feedback('遗忘取花','正在读取本批潜能及VIP返还配置') as feedback:
            self.feedback=feedback
            return self._run()
    def _run(self):
        from pet_training_log import say
        if self.state['status']=='complete':return self.state
        protected=set(self.data.get('initial_ids') or [])
        protected.update(e for e in self.data['leveling'].get('original',{}).values() if e)
        for key in ('p1','p2'):
            p=((self.info.get(key) or {}).get('equipments') or {}).get('pet') or {}
            if p.get('entityId'):protected.add(p['entityId'])
        plan=[]
        bag=(self.info.get('bag') or {}).get('pet') or {}
        for initial in self.data['kept']:
            eid=initial['entityId'];pet=bag.get(eid)
            if not pet or str(pet.get('id'))!=str(initial.get('id')):raise RuntimeError('本批宠物缺失或身份不符')
            for skill,level in passive(pet).items():
                if int(level)<3:continue
                count=return_count(self.info,level)
                if count<=0:
                    say('遗忘取花','跳过%s的%s级潜能%s：当前VIP遗忘不返益灵花'%(eid,level,skill));continue
                if eid in protected or pet.get('nickName') or pet.get('equipments'):raise RuntimeError('待遗忘宠物受保护、有昵称或装备')
                plan.append((eid,str(skill),int(level),count))
        if quantity(self.info,'bag',101704002)<len(plan):raise RuntimeError('去灵花不足本批遗忘需求；未购买、未开始遗忘')
        say('遗忘取花','计划遗忘%d个潜能，需去灵花%d朵，现有%d朵；预计返还益灵花%d朵'%(len(plan),len(plan),quantity(self.info,'bag',101704002),sum(r[3] for r in plan)))
        self.state['status']='running';self.save()
        for eid,skill,level,expected in plan:
            if (self.path.parent/'STOP').exists():raise RuntimeError('收到停止标记')
            before=bag[eid];before_skills=dict(passive(before));ticket=self.wallet().get('ticket')
            if ticket is None:raise RuntimeError('未读取到点券')
            q=quantity(self.info,'bag',101704002);y=quantity(self.info,'bag',101704003)
            params={'entityId':eid,'skillId':int(skill),'skLev':level,'totalNum':0,'consume_subType':0}
            self.feedback.set('%s：正在遗忘%s级潜能%s，预计益灵花+%d；已确认取花%d朵'%(eid,level,skill,expected,self.state['flowers']))
            self.state['pending']={'params':params,'pet_before':snapshot(before),'qulinghua':q,'yilinghua':y,'ticket':ticket};self.save()
            reply=self.flow.request('scene.petHandler.removePassivitySkill',{**params,**({'password':self.password} if self.password else {})})
            self.log('forget_reply',{'entityId':eid,'skillId':skill,'reply':reply});self.checked(reply)
            self.read();bag=(self.info.get('bag') or {}).get('pet') or {};after=bag.get(eid)
            if not after:raise RuntimeError('遗忘后宠物缺失')
            q_after=quantity(self.info,'bag',101704002);y_after=quantity(self.info,'bag',101704003);t_after=self.wallet().get('ticket')
            wanted={k:v for k,v in before_skills.items() if str(k)!=skill}
            if passive(after)!=wanted or q-q_after!=1 or y_after-y!=expected or t_after!=ticket:
                self.state['verification_failed']={'pet_after':snapshot(after),'qulinghua':q_after,'yilinghua':y_after,'ticket':t_after};self.save()
                raise RuntimeError('遗忘或材料到账核对异常；停止，不重发')
            record={'entityId':eid,'skillId':skill,'level':level,'qulinghua_used':1,'flowers':y_after-y,'ticket_before':ticket,'ticket_after':t_after,'pet_after':snapshot(after)}
            self.state['records'].append(record);self.state['flowers']+=record['flowers'];self.state['pending']=None;self.save();self.log('flower_verified',record)
            say('取花核对','%s：去灵花%d→%d，益灵花%d→%d（+%d），点券%s→%s；其余潜能未变'%(eid,q,q_after,y,y_after,y_after-y,ticket,t_after))
        self.state['status']='complete';self.save();self.log('harvest_completed',{'flowers':self.state['flowers'],'forgotten':len(self.state['records'])})
        return self.state
