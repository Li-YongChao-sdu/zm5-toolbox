"""多账号世界BOSS同房：仅本地账号文件，主动停止可完整退出。"""
import argparse
import concurrent.futures
import hashlib
import json
import math
import time
from pathlib import Path
from teacher_trial import connect, enter, checked
from world_boss_damage import sample_expected_hurt, sample_hurt

MODES=('达标后零伤害挂机','持续伤害','直接零伤害挂机','达标后小伤害挂机')
ROLES=('拿阵法号','挂机号')

def validate(job):
    rows=job.get('members',[])
    if not 8<=len(rows)<=10:raise ValueError('参与账号数量须为8～10')
    if int(job.get('boss_id',0)) not in {960101+i*100 for i in range(15)}:raise ValueError('世界BOSS选择无效')
    seen=set()
    for row in rows:
        account=json.loads(Path(row['account_file']).read_text(encoding='utf-8-sig'))
        uid=str(account.get('uid',''))
        if not uid or not account.get('cookies'):raise ValueError('请使用已登录的本地账号文件')
        if uid in seen:raise ValueError('同一账号不能同时使用多个槽位')
        seen.add(uid)
        if not 0<=int(row['slot'])<=7:raise ValueError('存档槽位须为0～7')
        if row['role'] not in ROLES or row['mode'] not in MODES:raise ValueError('账号类型或挂机方式无效')
        for key in ('dps','target'):
            if not math.isfinite(float(row[key])):raise ValueError('伤害和占比须为有限数值')
        if float(row['dps'])<=0 or not 0<float(row['target'])<=100:raise ValueError('伤害须大于0，目标占比须在0～100%')
    return rows

def fingerprint(job):return hashlib.sha256(json.dumps(job,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def next_hurt(row,hit,hp_max):
    mode=row['mode']
    if mode=='直接零伤害挂机':return None
    reached=float(hit)>=float(hp_max)*float(row['target'])/100
    if reached and mode=='达标后零伤害挂机':return None
    if reached and mode=='达标后小伤害挂机':return sample_hurt(0,10000)
    return sample_expected_hurt(float(row['dps']))

def reward_items(reward):
    if not isinstance(reward,dict):return []
    types=str(reward.get('type','')).split(';');ids=str(reward.get('subType','')).split(';');counts=str(reward.get('count','')).split(';')
    items=[]
    for kind,group,amounts in zip(types,ids,counts):
        for item,amount in zip(group.split(','),amounts.split(',')):
            if item and amount:items.append({'type':kind,'id':item,'count':amount})
    return items

def settlement_summary(state):
    result=state.get('finished')
    if not isinstance(result,dict):return {'received':False}
    return {'received':True,'success':result.get('success'),'rank':result.get('rank'),'hit':result.get('hit',state.get('hit')),'rewards':reward_items(result.get('rankReward')),'before_count':state.get('before_count'),'after_count':state.get('after_count')}

def log_settlements(report,log):
    names={}
    config=Path(__file__).resolve().parent/'cg_config_out_cg1_20261019_1'
    for table in ('Prop','FormationFlag'):
        try:
            data=json.loads((config/(table+'.json')).read_text(encoding='utf-8-sig'))
            if isinstance(data,dict):names.update({str(key):str(value.get('name',key)) for key,value in data.items() if isinstance(value,dict)})
        except (OSError,ValueError):pass
    for state in report['accounts']:
        summary=settlement_summary(state);state['settlement_summary']=summary
        if not summary['received']:continue
        rewards='、'.join('%s×%s'%(names.get(item['id'],item['id']),item['count']) for item in summary['rewards']) or '无排行奖励字段'
        log('[包房结算] %s｜%s｜槽%s｜排名%s｜伤害%s｜次数%s→%s｜%s'%(state['role'],state['label'],state['slot'],summary['rank'],summary['hit'],summary['before_count'],summary['after_count'] if summary['after_count'] is not None else '未核实',rewards),flush=True)

def run(job_path,action='query',log=print,connector=connect,entry=enter,sleep=time.sleep):
    job_path=Path(job_path);job=json.loads(job_path.read_text(encoding='utf-8'));rows=validate(job)
    report_path=job_path.with_suffix('.report.json');stop=job_path.with_suffix('.stop');token=fingerprint(job)
    if action=='run':
        prior=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
        if prior.get('status')!='queried' or prior.get('fingerprint')!=token or not 0<=time.time()-prior.get('queried_at',0)<=300:
            raise ValueError('请先查询当前配置，查询有效期5分钟')
    report={'fingerprint':token,'boss_id':int(job['boss_id']),'status':'connecting','accounts':[]};members=[]
    def save():
        temp=report_path.with_suffix('.tmp');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8');temp.replace(report_path)
    def login(row):
        account=json.loads(Path(row['account_file']).read_text(encoding='utf-8-sig'))
        flow,info=connector(account,int(row['slot']))
        return {'flow':flow,'row':row,'state':{'label':Path(row['account_file']).stem,'role':row['role'],'slot':int(row['slot']),'before_count':(info.get('worldBoss') or {}).get('count'),'hit':0,'joined':False,'finished':None,'sent':0}}
    try:
        # Collect every successful connection even when another member fails.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(login,row) for row in rows]
            errors=[]
            for future in futures:
                try:members.append(future.result())
                except Exception as exc:errors.append(type(exc).__name__)
        report['accounts']=[m['state'] for m in members];save()
        if errors:raise RuntimeError('部分账号登录失败：'+','.join(errors))
        for member in members:
            state=member['state'];count=state['before_count']
            if not isinstance(count,(int,float)) or count<=0:raise RuntimeError(state['label']+'没有可用世界BOSS次数')
            log('[包房] %s｜%s｜槽%s｜剩余%s次'%(state['role'],state['label'],state['slot'],count),flush=True)
        lead=members[0]['flow'];boss=int(job['boss_id'])
        listed=checked(lead.request('scene.worldBossHandler.getWorldBossRoomList',{'bossId':boss,'type':0}),'查询房间')
        needed=len(members)
        rooms=[room for room in listed.get('rooms',[]) if isinstance(room.get('userCnt'),int) and 0<=room['userCnt']<=10-needed and float((room.get('boss') or {}).get('hp') or 0)>0]
        requested=job.get('room_id','').strip()
        if requested:rooms=[room for room in rooms if room.get('roomId')==requested]
        report['rooms']=listed.get('rooms',[]);report['eligible_rooms']=[room['roomId'] for room in rooms]
        if action=='query':
            report.update(status='queried',queried_at=time.time());save()
            log('[包房] 查询完成：拿阵法号%s＋挂机号%s；可容纳全组的房间：%s。尚未进房。'%(sum(r['role']=='拿阵法号' for r in rows),sum(r['role']=='挂机号' for r in rows),'、'.join(report['eligible_rooms']) or '暂无'),flush=True)
            return report
        if not rooms:raise RuntimeError('没有可容纳全部账号的存活房间，未进房')
        room=min(rooms,key=lambda x:(x['userCnt'],-float(x['boss']['hp'])))
        rid=room['roomId'];hp_max=float(room['boss']['hpMax']);report['room_id']=rid;report['status']='joining';save()
        for member in members:
            flow,state=member['flow'],member['state']
            flow.on('onWorldBossSelfHit',lambda data,s=state:s.update(hit=float(data['hit'])) if isinstance(data,dict) and data.get('hit') is not None else None)
            flow.on('onWorldBossHpChange',lambda data:report.update(boss_hp=data['hp']) if isinstance(data,dict) and data.get('hp') is not None else None)
            flow.on('onFinishWorldBossCopy',lambda data,s=state:s.update(finished=data))
        for member in members:
            if stop.exists():raise RuntimeError('用户停止')
            state=member['state'];report['pending']={'action':'join','label':state['label']};state['join_pending']=True;save()
            reply=checked(member['flow'].request('scene.worldBossHandler.joinWorldBossCopy',{'bossId':boss,'roomId':rid,'type':0}),'加入房间')
            if reply.get('roomId')!=rid:raise RuntimeError('服务器分配的房间不符')
            state.update(joined=True,join_pending=False,join_reply=reply);report['pending']=None;save()
        report['status']='running';save();log('[包房] %s个号已进入同一房间%s。'%(needed,rid),flush=True)
        deadline=min(float(m['state']['join_reply']['endTime'])/1000 for m in members)+60
        started=time.monotonic();last_log=0
        while time.time()<deadline:
            if stop.exists():report['status']='user_stopped';break
            if any(m['state']['finished'] is not None for m in members):
                sleep(2);report['status']='server_finished';break
            if not all(m['flow'].game._running for m in members):raise RuntimeError('有账号连接断开，停止全组，不自动重进房')
            for member in members:
                state,row=member['state'],member['row']
                if report.get('boss_hp') is not None and float(report['boss_hp'])<=0:continue
                hurt=next_hurt(row,state['hit'],hp_max)
                state['idle']=hurt is None
                if hurt is None:continue
                report['pending']={'action':'attack','label':state['label'],'hurt':hurt};save()
                checked(member['flow'].request('scene.worldBossHandler.attack',{'roomId':rid,'bossId':boss,'hurt':hurt}),'提交伤害')
                state['sent']+=1;report['pending']=None;save()
            if time.monotonic()-last_log>=30:
                log('[包房] 已运行%s秒｜%s'%(int(time.monotonic()-started),'；'.join('%s 槽%s：伤害%.0f%s'%(m['state']['role'],m['state']['slot'],m['state']['hit'],'（零伤害挂机）' if m['state'].get('idle') else '') for m in members)),flush=True)
                last_log=time.monotonic();save()
            sleep(1)
        else:report['status']='server_end_timeout'
    except Exception as exc:
        report.update(status='stopped',error_type=type(exc).__name__);save();raise
    finally:
        for member in members:
            flow,state=member['flow'],member['state']
            try:
                if state.get('joined') or state.get('join_pending'):
                    state['exit_reply']=flow.request('scene.worldBossHandler.exitWorldBossCopy',{})
                    info=entry(flow,state['slot']);state['after_count']=(info.get('worldBoss') or {}).get('count')
            except Exception as exc:state['cleanup_error_type']=type(exc).__name__
            finally:flow.disconnect()
        log_settlements(report,log)
        save()
    log('[包房] 已结束：'+report['status']+'；报告 '+str(report_path),flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);parser.add_argument('--action',choices=('query','run'),default='query');args=parser.parse_args()
    try:run(args.job,args.action)
    except Exception as exc:print('[包房] 已停止：'+str(exc),flush=True);raise SystemExit(1)
