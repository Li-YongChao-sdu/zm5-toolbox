"""竞技场上届领奖；每次至多发送一次领取请求。"""
import json
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def checked(reply):
    if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):
        raise RuntimeError(str(reply.get('error') or reply.get('code')) if isinstance(reply,dict) else '无效回包')
    return reply

def read_state(flow,slot):
    info=checked(flow.request('connector.entryHandler.entry',{'index':slot,'userAgent':flow.user_agent})).get('info')
    if not isinstance(info,dict):raise RuntimeError('存档状态缺失')
    user=checked(flow.request('connector.roleHandler.getUserInfo',{})).get('user') or {}
    if any(user.get(k) is None for k in ('ticket','yuanbao')) or info.get('arenaMoney') is None:
        raise RuntimeError('竞技币或货币余额缺失')
    return {'arenaMoney':info['arenaMoney'],'ticket':user['ticket'],'yuanbao':user['yuanbao'],
            'setting':(info.get('everyWeekSetting') or {}).get('arenaSetting') or {}}

def do_claim(flow,info,*,slot=None,report_dir=None):
    if slot is None:
        import daily_auto as da
        slot=da.RECORD_INDEX
    home=checked(flow.request('scene.arenaHandler.getArenaInfo',{}))
    before=read_state(flow,slot)
    setting=(home.get('everyWeekSetting') or {}).get('arenaSetting')
    if not isinstance(setting,dict):setting=before['setting']
    if float(setting.get('rewardTime') or 0)>0:
        return True,'竞技场上届奖励本届已领取，跳过（竞技币%s）'%before['arenaMoney'],{'status':'already_claimed','before':before}
    folder=Path(report_dir) if report_dir is not None else ROOT/'arena_reward_reports';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    report={'slot':slot,'index':home.get('index'),'route':'scene.arenaHandler.getReward','params':{},'phase':'pending','before':before}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:reply=flow.request(report['route'],{});report.update(reply=reply,phase='returned');save()
    except Exception as e:
        report.update(phase='uncertain',error=type(e).__name__);save()
        return False,'竞技场领奖结果未确认，未重发；请查询状态。记录：'+str(path),report
    try:
        after=read_state(flow,slot);report['after']=after
        checked(reply)
        if reply.get('consume'):raise RuntimeError('领奖出现非预期消耗')
        if any(before[k]!=after[k] for k in ('ticket','yuanbao')):raise RuntimeError('点券或元宝发生变化')
        give=reply.get('give')
        if not isinstance(give,list):raise RuntimeError('奖励列表缺失')
        coins=sum(int(g.get('count',0)) for g in give if g.get('type')=='coin' and g.get('subType')=='arenaMoney')
        delta=after['arenaMoney']-before['arenaMoney']
        if delta!=coins:raise RuntimeError('竞技币到账与奖励回包不一致')
        if reply.get('arenaMoney') is not None and int(reply['arenaMoney'])!=delta:raise RuntimeError('竞技币奖励字段与实际增量不一致')
        report.update(phase='verified',arenaMoney_delta=delta);save()
        message=('竞技场上届没有奖励' if not give else '竞技场上届领奖成功：'+json.dumps(give,ensure_ascii=False))
        return True,message+'；竞技币%s→%s；点券、元宝未变化；记录：%s'%(before['arenaMoney'],after['arenaMoney'],path),report
    except Exception as e:
        report.update(phase='unverified',error=str(e));save()
        return False,'竞技场领奖核查未通过：%s；未重发。记录：%s'%(e,path),report
