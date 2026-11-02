"""时光水晶使用：逐个请求、逐个核对，失败不重试。"""
import argparse,json,os,time
from pathlib import Path
from datetime import datetime
from arena_reward import checked
from bag_warehouse import quantity
ROOT=Path(__file__).resolve().parent
ITEM='101027001'
def read(flow,slot):
    info=checked(flow.request('connector.entryHandler.entry',{'index':slot,'userAgent':flow.user_agent})).get('info')
    if not isinstance(info,dict) or info.get('energy') is None:raise RuntimeError('时光能量缺失')
    user=checked(flow.request('connector.roleHandler.getUserInfo',{})).get('user') or {}
    if any(user.get(k) is None for k in ('ticket','yuanbao')):raise RuntimeError('货币余额缺失')
    return {'crystals':quantity(info,'bag',ITEM),'energy':int(info['energy']),'sweepEnergy':info.get('sweepEnergy'),'spirit':info.get('spirit'),'ticket':user['ticket'],'yuanbao':user['yuanbao']}

def use(flow,slot,count=1,password='',report_dir=None):
    if type(count)!=int or not 1<=count<=9999:raise ValueError('数量须为1～9999')
    before=read(flow,slot)
    if before['crystals']<count:raise ValueError('背包时光水晶不足，未使用')
    folder=Path(report_dir) if report_dir else ROOT/'time_crystal_reports';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    report={'slot':slot,'requested':count,'password_supplied':bool(password),'before':before,'actions':[],'phase':'running'}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    current=before;save()
    try:
        for i in range(count):
            row={'route':'scene.itemHandler.useItem','params':{'index':0,'id':ITEM,'count':1},'phase':'pending'};report['actions'].append(row);save()
            args=dict(row['params'])
            if password:args['password']=password
            reply=flow.request(row['route'],args);row.update(reply={k:reply[k] for k in ('code','error','give','consume') if k in reply},phase='returned');save()
            after=read(flow,slot);row['after']=after;report['after']=after;save()
            if reply.get('code')!=200 or reply.get('error'):
                if current!=after:raise RuntimeError('请求失败但资源变化，停止')
                row['phase']='rejected';report['phase']='rejected';save()
                return False,'时光水晶使用被拒绝：%s；已停止，未重发'%(reply.get('error') or reply.get('code')),report
            if current['crystals']-after['crystals']!=1 or after['energy']-current['energy']!=1 or any(current[k]!=after[k] for k in ('ticket','yuanbao','spirit','sweepEnergy')):raise RuntimeError('道具或时光能量增量未通过核对，停止且不重发')
            row['phase']='verified';save();current=after
            print('[时光水晶] 已使用%s/%s，时光能量%s'%(i+1,count,after['energy']),flush=True)
            if i+1<count:time.sleep(1)
        report['phase']='verified';save()
        return True,'时光水晶已使用%s个，时光能量%s→%s；其他货币未变化。记录：%s'%(count,before['energy'],current['energy'],path),report
    except Exception as exc:report.update(phase='stopped',error_type=type(exc).__name__);save();raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--slot',type=int,required=True);p.add_argument('--uid',required=True);p.add_argument('--use',action='store_true');p.add_argument('--count',type=int,default=1);a=p.parse_args()
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
    if str(account['uid'])!=a.uid or not 0<=a.slot<=7:raise ValueError('账号或存档无效')
    from teacher_trial import connect
    flow=None
    try:
        flow,_=connect(account,a.slot)
        if a.use:
            ok,message,_=use(flow,a.slot,a.count,os.environ.get('ZM5_TIME_CRYSTAL_PASSWORD',''));print(('[OK] ' if ok else '[--] ')+message,flush=True)
        state=read(flow,a.slot);state.update(uid=a.uid,slot=a.slot)
        print('__TIME_CRYSTAL_STATE__'+json.dumps(state,ensure_ascii=False),flush=True)
    finally:
        if flow:flow.disconnect()
if __name__=='__main__':main()
