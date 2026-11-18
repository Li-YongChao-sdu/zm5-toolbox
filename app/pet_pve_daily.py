"""万兽秘境：补首通与第六关免费重复挑战，共用单连接结算流程。"""
import json,time
from pathlib import Path
from datetime import datetime
from teacher_trial import enter,checked
from game_version import latest_config_folder
ROOT=Path(__file__).resolve().parent

def run(flow,slot,mode='daily',*,report_dir=None,sleep=time.sleep):
    if mode not in ('first','daily'):raise ValueError('未知万兽秘境模式')
    config=latest_config_folder()
    if config is None:raise ValueError('请先更新配置')
    tables=json.loads((config/'PetBattleDungeonPve.json').read_text(encoding='utf-8-sig'))
    helper=json.loads((config/'PetBattleHelperPve.json').read_text(encoding='utf-8-sig'))['1']
    stages=sorted((int(k),v) for k,v in tables.items() if int(v['layerId'])==1)
    if len(stages)!=6:raise ValueError('关卡配置已变化，请核对后更新程序')
    last=stages[-1][0];limit=int(helper['dayNumMax'])
    folder=Path(report_dir or ROOT/'pet_pve_reports');folder.mkdir(parents=True,exist_ok=True)
    uid=str(flow.uid)
    for old in folder.glob('*.private.json'):
        r=json.loads(old.read_text(encoding='utf-8'))
        if r.get('uid')==uid and r.get('slot')==slot and any(x.get('phase') in ('pending','uncertain') for x in r.get('requests',[])):
            raise RuntimeError('万兽秘境有结果未确认的请求，请先核查私有记录')
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.private.json')
    report={'uid':uid,'slot':slot,'mode':mode,'requests':[],'completed':[],'status':'running','settlement_mode':'tested_result_parameters'}
    def save():
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    def query():return checked(flow.request('scene.petPvpHandler.getPetPVPInfo',{'type':2}),'万兽秘境状态')
    def wallet():
        u=checked(flow.request('connector.roleHandler.getUserInfo',{}),'余额')['user']
        return {k:u[k] for k in ('ticket','yuanbao')}
    def write(route,params):
        row={'route':route,'params':params,'phase':'pending'};report['requests'].append(row);save()
        try:reply=flow.request(route,params)
        except Exception:row['phase']='uncertain';save();raise RuntimeError('万兽秘境请求结果不明，停止且不重发') from None
        row.update(phase='returned',reply=reply);save()
        checked(reply,'万兽秘境操作')
        if reply.get('consume'):raise RuntimeError('出现非预期消耗，停止核查')
        return reply
    try:
        info=enter(flow,slot)
        if str(info['_id']).split('_r')[0]!=uid:raise RuntimeError('实际存档身份不符')
        before=query();money=wallet();report.update(before=before,before_wallet=money);save()
        if mode=='first':targets=[mid for mid,row in stages if int(((before.get('petPve') or {}).get('copy') or {}).get(str(mid),0))<1]
        else:
            pve=before.get('petPve') or {}
            if int((pve.get('copy') or {}).get(str(last),0))<1:
                print('[万兽秘境] 第6关尚未首通，请先执行首通至第6关；本项跳过',flush=True)
                targets=[]
            else:targets=[last]*max(0,limit-int(pve.get('count',0)))
        for mid in targets:
            state=query();pve=state.get('petPve') or {};history=pve.get('copy') or {};used=int(pve.get('count',0));is_first=int(history.get(str(mid),0))<1
            if wallet()!=money:raise RuntimeError('余额变化，停止')
            if mode=='first' and not is_first:continue
            if mode=='daily' and (is_first or used>=limit):break
            prev=int(tables[str(mid)]['prevId'])
            if prev!=1 and int(history.get(str(prev),0))<1:raise RuntimeError('前置关卡未通关')
            write('scene.petPvpHandler.enterPveWait',{'copyId':mid})
            finished=False
            for round_index in range(5):
                started=write('scene.petPvpHandler.startPveBattle',{})
                session=int(started['session']);sleep(3)
                # 沿用已实测的结果参数；不将测试血量宣称为真实战斗模拟。
                result=write('scene.petPvpHandler.endPveBattle',{'roomId':None,'btlResult':5,'hps':[1,0] if session%2 else [0,1]})
                if result.get('finish'):
                    if result.get('winType') not in (1,3):raise RuntimeError('本场未获胜，停止')
                    finished=True;break
                sleep(2)
            if not finished:raise RuntimeError('五局后未结束，停止核查')
            after=query();current=after.get('petPve') or {}
            if wallet()!=money:raise RuntimeError('点券或元宝变化，停止')
            if int(current.get('count',0))!=used+(0 if is_first else 1):raise RuntimeError('免费次数变化不符')
            if int((current.get('copy') or {}).get(str(mid),0))!=int(history.get(str(mid),0))+1:raise RuntimeError('通关进度未核对通过')
            report['completed'].append({'copyId':mid,'first':is_first,'give':result.get('give',[]),'after':after});save()
            print('[万兽秘境] %s完成；奖励%s；今日已用%s/%s'%(tables[str(mid)]['name'],result.get('give',[]),current.get('count',0),limit),flush=True)
            sleep(3)
        report.update(status='complete',after=query(),after_wallet=wallet());save()
        print('[万兽秘境] 本项结束，完成%s场；记录%s'%(len(report['completed']),path),flush=True)
        return report
    except Exception:
        report['status']='stopped';save();raise
