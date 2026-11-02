"""幻兽派遣日常：先领取已完成奖励，再派遣空闲档位；按分档和档内顺序使用免费刷新，不召回、不使用点券。"""
import argparse,json,time,copy
from datetime import datetime
from pathlib import Path
import fairy_api as api
import fairy_data as fd
from teacher_trial import connect,enter,checked
from bag_warehouse import quantity
from fairy_preferences import normalize,choose
ROOT=Path(__file__).resolve().parent

def positions_value(values):
    if not isinstance(values,(list,tuple)) or not values or any(type(p) is not int or not 0<=p<=2 for p in values):raise ValueError('派遣档位须为0～2的非空列表')
    return list(dict.fromkeys(values))

def run(flow,slot,positions=(0,1,2),*,apply=True,preferences=None,report_dir=None,log=print):
    positions=positions_value(positions);preferences=normalize(preferences);help_=fd.load_help();tasks=fd.load_tasks()
    folder=Path(report_dir) if report_dir else ROOT/'fairy_daily_reports';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json');report={'slot':slot,'positions':positions,'claims':[],'dispatches':[],'refreshes':[],'preferences':preferences,'skipped':[],'status':'reading'}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    def snapshot():
        info=enter(flow,slot);user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'读取余额')['user']
        daily=info.get('everyDaySetting')
        if not isinstance(daily,dict):raise RuntimeError('每日状态缺失')
        wallet={k:user.get(k,info.get(k)) for k in ('ticket','yuanbao')}
        if any(v is None for v in wallet.values()):raise RuntimeError('点券或元宝余额未知')
        return info,{'wallet':wallet,'reset':daily.get('resetTime'),'quota':api.quota(info,help_)}
    def check_free(pre,post,reply):
        checked(reply,'幻兽日常操作')
        if reply.get('consume') or pre['wallet']!=post['wallet'] or pre['reset']!=post['reset']:raise RuntimeError('出现消耗、余额变化或跨日，停止且不重发')
    def request(route,params,pre):
        report['pending']={'route':route,'params':params,'before':pre};save()
        reply=flow.request(route,params);report['last_reply']=reply;save();checked(reply,'幻兽日常操作');return reply
    try:
        info,current=snapshot();report['before']=current;save()
        if not apply:
            claimable=[p for p,v in api.slots(info).items() if api.slot_state(v)['claimable']]
            action={'action':'claim_first'} if claimable else choose(info,tasks,preferences,positions,help_)
            report.update(status='preview',claimable=claimable,next_action=action);save()
            log('[幻兽日常预览] 待领奖档位%s；下一步%s；领奖后会重新核对任务及幻兽。'%([p+1 for p in claimable],action),flush=True)
            return report
        # Claim all completed jobs first, not just jobs completed on the previous calendar day.
        for pos in sorted(api.slots(info)):
            raw=api.slots(info).get(pos)
            if not api.slot_state(raw)['claimable']:continue
            pre_info,pre=info,current;reply=request(api.ROUTE_REWARD,{'pos':pos},pre)
            info,current=snapshot();check_free(pre,current,reply)
            if api.slot_state(api.slots(info).get(pos))['claimable']:raise RuntimeError('领奖后档位仍显示可领取，停止核查')
            if pre['quota']['sendUsed']!=current['quota']['sendUsed']:raise RuntimeError('领奖时派遣次数意外变化')
            for gift in reply.get('give') or []:
                if gift.get('type')=='item' and quantity(info,'bag',str(gift['subType']))-quantity(pre_info,'bag',str(gift['subType']))!=int(gift['count']):raise RuntimeError('奖励入包数量不符，停止')
            report['claims'].append({'pos':pos,'give':reply.get('give',[])});report['pending']=None;save()
            log('[幻兽日常] 已领取档位%s奖励'%(pos+1),flush=True)
        for _ in range(20):
            info,current=snapshot()
            if current['wallet']!=report['before']['wallet'] or current['reset']!=report['before']['reset']:
                raise RuntimeError('余额变化或跨日，停止')
            decision=choose(info,tasks,preferences,positions,help_)
            report['decision']=decision;save()
            if decision['action']=='stop':
                report['stop_reason']=decision['reason'];report['skipped']=decision.get('blocked',[])
                log('[幻兽日常] '+decision['reason'],flush=True);break
            if decision['action']=='refresh':
                frozen={pos:copy.deepcopy(row) for pos,row in api.slots(info).items() if api.slot_state(row)['dispatched']}
                pre=current;reply=request(api.ROUTE_REFRESH,{'type':0},pre)
                after_info,after=snapshot();check_free(pre,after,reply)
                if after['quota']['refreshFreeUsed']!=pre['quota']['refreshFreeUsed']+1 or after['quota']['refreshTicketUsed']!=pre['quota']['refreshTicketUsed'] or after['quota']['sendUsed']!=pre['quota']['sendUsed']:
                    raise RuntimeError('免费刷新次数核对不符，停止且不重发')
                for pos,old in frozen.items():
                    new=api.slots(after_info).get(pos) or {}
                    if any(old.get(key)!=new.get(key) for key in ('id','fairy','expiredTime','reward')):raise RuntimeError('刷新影响了已派遣档位，停止')
                report['refreshes'].append({'before':pre['quota']['refreshFreeUsed'],'after':after['quota']['refreshFreeUsed'],'preserved':list(frozen)})
                report['pending']=None;info,current=after_info,after;save()
                log('[幻兽日常] 免费刷新%s/%s，已派遣档位保持不变'%(after['quota']['refreshFreeUsed'],after['quota']['refreshFreeTotal']),flush=True)
                continue
            pos=decision['pos'];ids=decision['ids'];pre=current
            if len(set(ids))!=2:raise RuntimeError('幻兽组合重复，未派遣')
            reply=request(api.ROUTE_COLLECT,{'pos':pos,'ids':ids},pre)
            info,current=snapshot();check_free(pre,current,reply);after=api.slots(info).get(pos) or {}
            if not api.slot_state(after)['dispatched'] or set(after.get('fairy',[]))!=set(ids) or current['quota']['sendUsed']!=pre['quota']['sendUsed']+1:raise RuntimeError('派遣状态或次数核对不符，停止且不重发')
            report['dispatches'].append({'pos':pos,'ids':ids,'rank':decision['rank'],'fallback':decision['fallback'],'reward':decision['reward']});report['pending']=None;save()
            rank=decision['rank']
            detail=('第%s档／档内第%s项'%(rank[0]+1,rank[1]+1)) if rank is not None else ('补位' if decision['fallback'] else '原任务顺序')
            log('[幻兽日常] 档位%s已派遣（%s），今日剩余%s次'%(pos+1,detail,current['quota']['sendLeft']),flush=True)
        else:raise RuntimeError('本轮决策次数达到上限，停止核查')
        report.update(status='complete',after=current);save()
        log('[幻兽日常] 结束：领取%s档，派遣%s档；未完成和条件不足的档位保留。'%(len(report['claims']),len(report['dispatches'])),flush=True)
        return report
    except Exception as exc:report.update(status='stopped',error_type=type(exc).__name__);save();raise
    finally:log('[幻兽日常] 报告：'+str(path),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--positions',default='[0,1,2]');p.add_argument('--apply',action='store_true');p.add_argument('--preferences',default='null');args=p.parse_args();positions=positions_value(json.loads(args.positions));preferences=normalize(json.loads(args.preferences))
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account.get('record_index',0));flow=None
    try:flow,_=connect(account,slot);run(flow,slot,positions,apply=args.apply,preferences=preferences)
    finally:
        if flow:flow.disconnect()
