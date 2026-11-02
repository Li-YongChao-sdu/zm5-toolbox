"""神兽森林扫荡前按缺口最多使用1个速通水晶。"""
import json
from pathlib import Path
from datetime import datetime
from bag_warehouse import quantity
from arena_reward import checked
ROOT=Path(__file__).resolve().parent
ITEM='101037001'
def prepare(flow,info,slot,remaining,password='',report_dir=None):
    def read():
        latest=checked(flow.request('connector.entryHandler.entry',{'index':slot,'userAgent':flow.user_agent})).get('info')
        if not isinstance(latest,dict) or latest.get('sweepEnergy') is None:raise RuntimeError('速通水晶：无法读取最新存档或能量')
        user=checked(flow.request('connector.roleHandler.getUserInfo',{})).get('user') or {}
        if any(user.get(k) is None for k in ('ticket','yuanbao')):raise RuntimeError('速通水晶：货币余额缺失')
        state={'sweepEnergy':int(latest['sweepEnergy']),'crystals':quantity(latest,'bag',ITEM),'ticket':user['ticket'],'yuanbao':user['yuanbao'],'spirit':latest.get('spirit'),'energy':latest.get('energy')}
        return latest,state
    latest,before=read();info.clear();info.update(latest)
    vip=(latest.get('vip') or {}).get('level')
    if vip is None or isinstance(vip,bool) or int(vip) not in (0,1,2):return
    left=int(remaining(info))
    if left<=0 or before['sweepEnergy']>=left*10:return
    if before['crystals']<1:
        print('[神兽森林] 速通能量不足以扫完剩余%s次，背包没有水晶；按已有能量扫荡，不购买'%left,flush=True);return
    folder=Path(report_dir) if report_dir else ROOT/'forest_crystal_reports';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    report={'slot':slot,'route':'scene.itemHandler.useItem','params':{'index':0,'id':ITEM,'count':1},'password_supplied':bool(password),'before':before,'remaining_free':left,'phase':'pending'}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        args=dict(report['params'])
        if password:args['password']=password
        reply=flow.request(report['route'],args);report.update(phase='returned',reply={k:reply[k] for k in ('code','error','consume','give') if k in reply});save()
        latest,after=read();report['after']=after;save();info.clear();info.update(latest)
        if any(before[k]!=after[k] for k in ('ticket','yuanbao','spirit','energy')):raise RuntimeError('使用速通水晶出现非预期货币变化，停止')
        if reply.get('code')!=200 or reply.get('error'):
            if before!=after:raise RuntimeError('使用失败但资源变化，停止')
            report['phase']='rejected';save();print('[神兽森林] 水晶未使用：%s；未重发，按已有能量扫荡。需要密码的账号请填写二级密码。'%(reply.get('error') or reply.get('code')),flush=True);return
        if before['crystals']-after['crystals']!=1 or after['sweepEnergy']-before['sweepEnergy']!=10:raise RuntimeError('速通水晶数量或能量增量未通过核对，停止且不重发')
        report['phase']='verified';save();print('[神兽森林] 扫荡前使用1个速通水晶：能量%s→%s；点券、元宝未变化'%(before['sweepEnergy'],after['sweepEnergy']),flush=True)
    except Exception as exc:report.update(phase='stopped',error_type=type(exc).__name__);save();raise
