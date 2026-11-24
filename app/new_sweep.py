# 新增扫荡：共享免费次数与万兽秘境次数核对
import json,time
from pathlib import Path
from datetime import datetime
from teacher_trial import enter,checked
from game_version import config_table_path
ROOT=Path(__file__).resolve().parent

def run(flow,slot,mid,*,report_dir=None,sleep=time.sleep):
    mid=int(mid)
    if mid not in (300113,40270,2200106):raise ValueError('不支持的新增扫荡关卡')
    def table(n):return json.loads(config_table_path(n).read_text(encoding='utf-8-sig'))
    cfg=table('Sweep')[str(mid)];cost=int(table('ConsumeConfig')[str(cfg['consumeId'])]['consume_count']);pve=mid==2200106
    maximum=int(table('PetBattleHelperPve')['1']['dayNumMax']) if pve else 2
    share=str(cfg['dungeonTreasureShareId'])
    folder=Path(report_dir or ROOT/'new_sweep_reports');folder.mkdir(parents=True,exist_ok=True)
    for p in folder.glob('*.private.json'):
        old=json.loads(p.read_text(encoding='utf-8'))
        if old.get('uid')==str(flow.uid) and old.get('slot')==slot and any(r.get('phase') in ('pending','uncertain') for r in old.get('requests',[])):raise RuntimeError('存在结果未确认的扫荡，请核对记录')
    report={'uid':str(flow.uid),'slot':slot,'mid':mid,'requests':[],'rounds':[],'status':'running'}
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.private.json')
    def save():
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    def snapshot():
        info=enter(flow,slot)
        if str(info['_id']).split('_r')[0]!=str(flow.uid):raise RuntimeError('存档身份变化')
        u=checked(flow.request('connector.roleHandler.getUserInfo',{}),'余额')['user'];money={k:u[k] for k in ('ticket','yuanbao')}
        data=checked(flow.request('scene.petPvpHandler.getPetPVPInfo',{'type':2}),'万兽状态') if pve else {}
        if pve:
            pet=data.get('petPve') or {};passed=int((pet.get('copy') or {}).get(str(mid),0));remain=maximum-int(pet.get('count',0))
        else:
            rec=(info.get('dungeon') or {}).get(str(mid)) or {};passed=int(rec.get('passNum',0));remain=int(((info.get('dungeonTreasure') or {}).get(share) or {}).get('remainCnt',0))
        return info,money,data,passed,remain
    try:
        before=snapshot();report['before']=before;save();money=before[1]
        for _ in range(maximum):
            info,current,data,passed,remain=snapshot()
            if current!=money:raise RuntimeError('余额变化，停止')
            if passed<1 or remain<1:
                print('[扫荡] 未通关或免费次数已用完，跳过',flush=True);break
            if info.get('sweepEnergy') is None:raise RuntimeError('无法确认速通能量')
            energy=int(info['sweepEnergy'])
            if energy<cost:print('[扫荡] 能量不足，停止，不购买',flush=True);break
            if not pve:
                rec=info['dungeon'][str(mid)]
                if int(rec.get('star',0))<int(cfg.get('star',0)) or int(info.get('power',0))<int(cfg.get('powerMin',0)):
                    print('[扫荡] 星级或战力不符，停止',flush=True);break
            route='scene.petPvpHandler.sweepPetPve' if pve else 'scene.copyHandler.sweep'
            params={'mid':mid} if pve else {'mid':mid,'type':0,'passNum':passed}
            row={'route':route,'params':params,'phase':'pending'};report['requests'].append(row);save()
            try:reply=flow.request(route,params)
            except Exception:row['phase']='uncertain';save();raise RuntimeError('扫荡结果不明，停止且不重发') from None
            row.update(phase='returned',reply=reply);save();checked(reply,'扫荡')
            if any(x.get('subType') in ('ticket','yuanbao') for x in reply.get('consume',[]) if isinstance(x,dict)):raise RuntimeError('出现付费消耗，停止')
            after=snapshot()
            if after[1]!=money or after[4]!=remain-1 or int(after[0].get('sweepEnergy',-1))!=energy-cost:raise RuntimeError('扫荡余额、能量或次数核对不符')
            report['rounds'].append({'give':reply.get('give',[]),'after':after});save()
            print('[扫荡] %s完成；免费剩余%s，能量%s；奖励%s'%(cfg['name'],after[4],after[0]['sweepEnergy'],reply.get('give',[])),flush=True);sleep(2)
        report['status']='complete';save();return report
    except Exception:
        report['status']='stopped';save();raise
