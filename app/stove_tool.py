"""炼丹炉：先查等级，再列配方；每次仅提交一个 composeId。"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from bag_warehouse import quantity

ROOT=Path(__file__).resolve().parent

def table(name):
    return json.loads((ROOT/'cg_config_out_cg1_20261019_1'/(name+'.json')).read_text(encoding='utf-8-sig'))

def checked(reply):
    if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):
        raise RuntimeError(str(reply.get('error') or reply.get('code')) if isinstance(reply,dict) else '无效回包')
    return reply

def materials(recipe):
    ids=str(recipe['consume_subType']).split(',');counts=str(recipe['consume_count']).split(',')
    if len(ids)!=len(counts):raise ValueError('配方材料配置不完整')
    return [(int(i),int(n)) for i,n in zip(ids,counts)]

def view(info):
    compose=info.get('compose')
    if not isinstance(compose,dict) or compose.get('level') is None:raise ValueError('服务器未返回炼丹炉等级')
    level=int(compose['level']);props=table('Prop');rows=[]
    for recipe in sorted(table('Compose').values(),key=lambda x:(int(x['composeLevel']),int(x.get('order',0)),int(x['id']))):
        if int(recipe['composeLevel'])>level:continue
        needs=[{'id':i,'name':props.get(str(i),{}).get('name',str(i)),'need':n,'have':quantity(info,'bag',i)} for i,n in materials(recipe)]
        rows.append({'id':int(recipe['id']),'name':recipe['name'],'level':int(recipe['composeLevel']),
                     'category':recipe.get('labelName',''),'materials':needs,
                     'enough':all(x['have']>=x['need'] for x in needs),'exp':recipe.get('composeEXP',0)})
    return {'level':level,'exp':compose.get('exp'),'recipes':rows}

def validate(info,recipe):
    if int((info.get('compose') or {}).get('level',0))<int(recipe['composeLevel']):raise ValueError('炼丹炉等级不足')
    for i,n in materials(recipe):
        if n<=0 or quantity(info,'bag',i)<n:raise ValueError('背包材料不足：%s'%i)

def main():
    p=argparse.ArgumentParser();p.add_argument('--compose-id',type=int);p.add_argument('--account');p.add_argument('--slot',type=int);args=p.parse_args()
    from teacher_trial import connect,enter
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account['record_index']);flow=None
    try:
        if args.compose_id is not None and (args.account!=str(account.get('username')) or args.slot!=slot):raise ValueError('账号或槽位已变化，请重新查询配方')
        flow,_=connect(account,slot);info=enter(flow,slot)
        if args.compose_id is not None:
            recipe=table('Compose').get(str(args.compose_id))
            if not recipe:raise ValueError('配方不存在')
            validate(info,recipe)
            before=checked(flow.request('connector.roleHandler.getUserInfo',{}))['user']
            if before.get('ticket') is None:raise ValueError('无法确认点券余额')
            folder=ROOT/'stove_reports';folder.mkdir(exist_ok=True);path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
            report={'route':'scene.itemHandler.compose','params':{'composeId':args.compose_id},'recipe':recipe['name'],
                    'account':str(account.get('username')),'slot':slot,'phase':'pending','compose_before':info.get('compose'),
                    'materials_before':{str(i):quantity(info,'bag',i) for i,n in materials(recipe)},
                    'wallet_before':{k:before.get(k) for k in ('ticket','yuanbao')}}
            def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            save();print('[炼丹炉] %s：仅提交一次；结果不明时请刷新，勿重复点击。'%recipe['name'],flush=True)
            try:report['reply']=flow.request(report['route'],report['params']);report['phase']='returned';save()
            except Exception as e:
                report.update(phase='uncertain',error=type(e).__name__);save();raise RuntimeError('请求结果未确认，未重发；记录：'+str(path)) from None
            info=enter(flow,slot);after=checked(flow.request('connector.roleHandler.getUserInfo',{}))['user']
            report.update(compose_after=info.get('compose'),materials_after={str(i):quantity(info,'bag',i) for i,n in materials(recipe)},wallet_after={k:after.get(k) for k in ('ticket','yuanbao')});save()
            reply=report['reply'];print('[炼丹炉] 返回：'+json.dumps(reply,ensure_ascii=False),flush=True)
            print('[炼丹炉] 炉状态 %s → %s；记录：%s'%(report['compose_before'],report['compose_after'],path),flush=True)
            if report['wallet_before']!=report['wallet_after']:print('[炼丹炉] 货币发生变化，请检查记录；已停止。',flush=True)
            if reply.get('code')!=200 or reply.get('error'):print('[炼丹炉] 本次未成功：%s；未重试。'%reply.get('error',reply.get('code')),flush=True)
        data=view(info);data.update(account=str(account.get('username','')),slot=slot)
        print('__STOVE_STATE__'+json.dumps(data,ensure_ascii=False),flush=True)
    finally:
        if flow:flow.disconnect()

if __name__=='__main__':main()
