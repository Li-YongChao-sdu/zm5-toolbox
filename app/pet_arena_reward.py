"""斗宠大会上届领奖；每次至多发送一次领取请求，不报名、不挑战。"""
import json
from pathlib import Path
from datetime import datetime
from arena_reward import checked
from bag_warehouse import quantity
ROOT=Path(__file__).resolve().parent

def read_state(flow,slot):
    info=checked(flow.request('connector.entryHandler.entry',{'index':slot,'userAgent':flow.user_agent})).get('info')
    if not isinstance(info,dict):raise RuntimeError('存档数据缺失')
    user=checked(flow.request('connector.roleHandler.getUserInfo',{})).get('user') or {}
    home=checked(flow.request('scene.petArenaHandler.getArenaInfo',{}))
    weekly=dict(info.get('everyWeekSetting') or {});weekly.update(home.get('everyWeekSetting') or {})
    state={'petArenaMoney':info.get('petArenaMoney'),'ticket':user.get('ticket'),'yuanbao':user.get('yuanbao'),'setting':weekly.get('petArenaSetting') or {}}
    if any(state[k] is None for k in ('petArenaMoney','ticket','yuanbao')):raise RuntimeError('斗宠币或货币余额缺失')
    return state,info

def do_claim(flow,info,*,slot=None,report_dir=None):
    if slot is None:
        import daily_auto as da
        slot=da.RECORD_INDEX
    before,old=read_state(flow,slot)
    if float(before['setting'].get('rewardTime') or 0)>0:return True,'斗宠大会上届奖励已领取，跳过',{'status':'already_claimed','before':before}
    folder=Path(report_dir) if report_dir else ROOT/'pet_arena_reward_reports';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    report={'slot':slot,'route':'scene.petArenaHandler.getReward','params':{},'before':before,'phase':'pending'}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:reply=flow.request(report['route'],{});report.update(reply=reply,phase='returned');save()
    except Exception as exc:
        report.update(phase='uncertain',error_type=type(exc).__name__);save()
        return False,'斗宠大会领奖结果未确认，未重发；记录：'+str(path),report
    try:
        after,new=read_state(flow,slot);report['after']=after;checked(reply)
        if reply.get('consume'):raise RuntimeError('领奖出现非预期消耗')
        if any(before[k]!=after[k] for k in ('ticket','yuanbao')):raise RuntimeError('点券或元宝变化')
        give=reply.get('give')
        if not isinstance(give,list):raise RuntimeError('奖励列表缺失')
        coins=sum(int(g.get('count',0)) for g in give if g.get('type')=='coin' and g.get('subType')=='petArenaMoney')
        if after['petArenaMoney']-before['petArenaMoney']!=coins:raise RuntimeError('斗宠币到账不符')
        expected={}
        for g in give:
            if g.get('type')=='item':
                key=str(g['subType']);expected[key]=expected.get(key,0)+int(g['count'])
        changes=[]
        for key,count in expected.items():
            delta=quantity(new,'bag',key)-quantity(old,'bag',key);changes.append({'item':key,'expected':count,'delta':delta})
            if delta!=count:raise RuntimeError('道具入包数量不符')
        if give and float(after['setting'].get('rewardTime') or 0)<=0:raise RuntimeError('领取标志未更新')
        report.update(phase='verified',coin_delta=coins,item_changes=changes);save()
        return True,('斗宠大会上届领奖成功：'+json.dumps(give,ensure_ascii=False) if give else '斗宠大会上届没有奖励')+'；斗宠币%s→%s，点券、元宝未变化；记录：%s'%(before['petArenaMoney'],after['petArenaMoney'],path),report
    except Exception as exc:
        report.update(phase='unverified',error=str(exc));save()
        return False,'斗宠大会领奖核对未通过：%s；未重发。记录：%s'%(exc,path),report
