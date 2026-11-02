"""木矿布及三组BOSS进阶材料高换低，按实际背包核对1:1到账。"""
import argparse,json
from pathlib import Path
from datetime import datetime
from bag_warehouse import quantity,state,is_consume
ROOT=Path(__file__).resolve().parent
CFG=ROOT/'cg_config_out_cg1_20261019_1'
KINDS={2:'防具',3:'头盔',4:'武器',5:'木',6:'矿',7:'布'}
def catalog():
    return {str(k):v for k,v in json.loads((CFG/'PropExchange.json').read_text(encoding='utf8')).items() if v.get('type') in KINDS}
def targets(source,config=None):
    config=config if config is not None else catalog();s=config.get(str(source))
    return sorted([v for v in config.values() if s and v['type']==s['type'] and int(v['level'])<int(s['level'])],key=lambda v:int(v['level']))
def view(info,user):
    c=catalog();rows=[]
    for k,v in c.items():
        n=quantity(info,'bag',k)
        if n>0 and targets(k,c):rows.append({'id':k,'name':v['name'],'count':n,'kind':KINDS[v['type']],'level':v['level']})
    return {'sources':sorted(rows,key=lambda r:(r['kind'],int(r['level']))),'ticket':user.get('ticket'),'spirit':info.get('spirit')}
def exchange(flow,info,user,source,target,count,refresh):
    if type(count) is not int or count<=0:raise ValueError('数量须为正整数')
    c=catalog();s,t=c.get(str(source)),c.get(str(target))
    if not s or not t or str(target) not in {str(v['id']) for v in targets(source,c)}:raise ValueError('只允许木矿布或BOSS进阶材料同组高阶换低阶')
    bs,bt=quantity(info,'bag',source),quantity(info,'bag',target)
    if bs<count:raise ValueError('背包原材料数量不足')
    if user.get('ticket') is None or info.get('spirit') is None:raise ValueError('未读取完整货币余额')
    props=json.loads((CFG/'Prop.json').read_text(encoding='utf8'));kind='消耗品' if is_consume({},props.get(str(target),{})) else '材料'
    cap=state(info,user,props)['capacity']['bag'][kind]
    if bt==0 and (cap['max'] is None or cap['used']>=cap['max']):raise ValueError('目标材料需要新格子，背包空间不足')
    params={'sId':int(source),'tId':int(target),'num':count}
    folder=ROOT/'material_exchange_reports';folder.mkdir(exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    report={'status':'pending','route':'scene.itemHandler.propExchange','params':params,'source':s['name'],'target':t['name'],'source_before':bs,'target_before':bt,'ticket_before':user['ticket'],'spirit_before':info['spirit']}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    save();print('[材料置换] %s×%s → %s×%s'%(s['name'],count,t['name'],count),flush=True)
    reply=flow.request(report['route'],params);report.update(reply=reply,status='checking');save()
    after=refresh();r=flow.request('connector.roleHandler.getUserInfo',{})
    if r.get('code')!=200 or r.get('error') or (r.get('user') or {}).get('ticket') is None:raise RuntimeError('请求已发送，货币未确认；未重试。记录：'+str(path))
    latest=r['user'];sa,ta=quantity(after,'bag',source),quantity(after,'bag',target)
    verified=reply.get('code')==200 and not reply.get('error') and sa==bs-count and ta==bt+count and latest['ticket']==user['ticket'] and after.get('spirit')==info['spirit']
    report.update(source_after=sa,target_after=ta,ticket_after=latest['ticket'],spirit_after=after.get('spirit'),verified=verified,status='verified' if verified else 'unverified');save()
    print('[材料置换] %s；%s %s→%s；%s %s→%s；灵魂%s→%s；点券%s→%s；回复%s；报告%s'%('核对通过' if verified else '核对未通过，未重试',s['name'],bs,sa,t['name'],bt,ta,info['spirit'],after.get('spirit'),user['ticket'],latest['ticket'],reply.get('error') or reply.get('code'),path),flush=True)
    return report,after,latest
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=int);p.add_argument('--target',type=int);p.add_argument('--count',type=int,default=1);args=p.parse_args()
    from teacher_trial import connect,enter,checked
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account.get('record_index',0));f=None
    try:
        f,info=connect(account,slot);user=checked(f.request('connector.roleHandler.getUserInfo',{}),'货币')['user']
        if args.source is not None or args.target is not None:
            if args.source is None or args.target is None:raise ValueError('请选择左右两种材料')
            _,info,user=exchange(f,info,user,args.source,args.target,args.count,lambda:enter(f,slot))
        data=view(info,user);data.update(account=str(account.get('username','')),slot=slot)
        print('__MATERIAL_EXCHANGE_STATE__'+json.dumps(data,ensure_ascii=False),flush=True)
    finally:
        if f:f.disconnect()
if __name__=='__main__':main()
