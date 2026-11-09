"""道具背包、个人仓库与超级仓库存取；按服务器状态核对，不自动重试。"""
import argparse,json,os
from pathlib import Path
from datetime import datetime,timezone,timedelta

ROOT=Path(__file__).resolve().parent
CONFIG=ROOT/'cg_config_out_cg1_20261012_1'
TABLES={'bag':'item','warehouse':'warehouseItem','super':'superWareHouseItem'}
ROUTES={('bag','warehouse'):'scene.recordHandler.bagToWarehouse',
        ('warehouse','bag'):'scene.recordHandler.warehouseToBag',
        ('bag','super'):'scene.recordHandler.bagToSuperWarehouse',
        ('super','bag'):'scene.recordHandler.superWarehouseToBag'}

def super_rules():return json.loads((CONFIG/'SuperWarehouse.json').read_text(encoding='utf-8-sig'))

def props():return json.loads((CONFIG/'Prop.json').read_text(encoding='utf-8-sig'))
def entries(info,location):return ((info.get('bag') or {}).get(TABLES[location]) or {})
def quantity(info,location,item_id):
    return sum(int(v.get('count') or 0) for k,v in entries(info,location).items() if str(v.get('id',k))==str(item_id))
def is_consume(item,config):
    value=item.get('isConsume',config.get('isConsume',0))
    return str(value).lower() in ('1','true')

def rune_entries(info):
    # 与洗练共用属性及战力展示；优先排除镶嵌对象，不提供卸符或出售已镶嵌灵符。
    from wash_data import list_runes
    rows=[]
    for row in list_runes(info):
        if row['location']!='背包':continue
        row=dict(row)
        row['locked']=str(row.get('lock',0)).lower() in ('1','true')
        rows.append(row)
    return rows

def state(info,user=None,config=None):
    config=config if config is not None else props();bag=info.get('bag') or {};rows=[];capacity={}
    for location in TABLES:
        used={'材料':0,'消耗品':0}
        for key,item in entries(info,location).items():
            pid=str(item.get('id',key));count=int(item.get('count') or 0)
            if count<=0:continue
            cfg=config.get(pid,{})
            kind='消耗品' if is_consume(item,cfg) else '材料';used[kind]+=1
            rows.append({'location':location,'id':pid,'name':cfg.get('name') or item.get('name') or pid,'kind':kind,'count':count,'sellable':str(cfg.get('isSell',0))=='1','price':cfg.get('price'),'description':cfg.get('describe',''),'quality':cfg.get('quality'),'locked':bool(item.get('lock'))})
        if location!='super':
            suffix='BagMax' if location=='bag' else 'WarehouseMax'
            capacity[location]={kind:{'used':used[kind],'max':bag.get(prefix+suffix)} for kind,prefix in [('材料','item'),('消耗品','consumables')]}
        else:capacity[location]={'材料':{'used':used['材料'],'max':bag.get('superWareHouseItemBagMax')},'消耗品':{'used':used['消耗品'],'max':bag.get('superWareHouseConsumablesBagMax')}}
    capacity['rune']={'灵符':{'used':len(bag.get('rune') or {}),'max':bag.get('runeBagMax')}}
    return {'rows':rows,'runes':rune_entries(info),'capacity':capacity,'ticket':(user or {}).get('ticket'),
            'spacePointUsed':(info.get('everyWeekSetting') or {}).get('spacePoint'),
            'secondPasswordConfigured':((user or {}).get('secondPassword') or {}).get('havePwd')}

def move(flow,info,user,source,target,item_id,count,password='',refresh=None):
    if (source,target) not in ROUTES:raise ValueError('仅支持背包与个人仓库/超级仓库之间存取')
    if type(count) is not int or count<=0:raise ValueError('数量必须是正整数')
    if quantity(info,source,item_id)<count:raise ValueError('来源道具数量不足')
    if user.get('ticket') is None:raise ValueError('无法确认点券余额，未发送存取请求')
    if refresh is None:raise ValueError('必须提供服务器状态刷新函数')
    if 'super' in (source,target) and str(item_id) not in super_rules():
        raise ValueError('该道具不在超级仓库支持列表中')
    before={loc:quantity(info,loc,item_id) for loc in TABLES}
    params={'itemId':int(item_id),'count':count,'password':password or ''}
    route=ROUTES[source,target]
    reply=flow.request(route,params)
    after_info=refresh()
    wallet=flow.request('connector.roleHandler.getUserInfo',{})
    if wallet.get('code')!=200 or wallet.get('error') or (wallet.get('user') or {}).get('ticket') is None:
        raise RuntimeError('请求已发送，但货币核对失败；未重发，请刷新状态')
    after_user=wallet['user'];after={loc:quantity(after_info,loc,item_id) for loc in TABLES}
    ok=reply.get('code')==200 and not reply.get('error')
    expected=dict(before);expected[source]-=count;expected[target]+=count
    verified=ok and after==expected and user['ticket']==after_user['ticket']
    result={'route':route,'params':{'itemId':int(item_id),'count':count},'password_supplied':bool(password),
            'reply':reply,'before':before,'after':after,'ticket_before':user['ticket'],'ticket_after':after_user['ticket'],
            'space_before':(info.get('everyWeekSetting') or {}).get('spacePoint'),
            'space_after':(after_info.get('everyWeekSetting') or {}).get('spacePoint'),
            'needs_password':reply.get('code')==502,'verified':verified}
    return result,after_info,after_user

def sell(flow,info,user,item_id,count,password='',refresh=None):
    cfg=props().get(str(item_id),{})
    item=next((v for k,v in entries(info,'bag').items() if str(v.get('id',k))==str(item_id)),{})
    if str(cfg.get('isSell',0))!='1':raise ValueError('配置标记该物品不可出售')
    if item.get('lock'):raise ValueError('锁定物品不可出售')
    extract=item.get('extract') or {}
    if extract.get('level',0)>0 or extract.get('exp',0)>0:raise ValueError('已提炼物品不可出售')
    if type(count) is not int or count<=0 or quantity(info,'bag',item_id)<count:raise ValueError('出售数量无效')
    if refresh is None or user.get('ticket') is None:raise ValueError('无法核对状态，未出售')
    before={loc:quantity(info,loc,item_id) for loc in TABLES}
    reply=flow.request('scene.itemHandler.sellObject',{'type':'item','id':str(item_id),'count':count,'password':password or ''})
    after_info=refresh();wallet=flow.request('connector.roleHandler.getUserInfo',{})
    if wallet.get('code')!=200 or wallet.get('error') or (wallet.get('user') or {}).get('ticket') is None:raise RuntimeError('出售已发送但余额核对失败，请刷新；未重试')
    after_user=wallet['user'];after={loc:quantity(after_info,loc,item_id) for loc in TABLES}
    expected=dict(before);expected['bag']-=count
    result={'route':'scene.itemHandler.sellObject','params':{'type':'item','id':str(item_id),'count':count},'reply':reply,
            'before':before,'after':after,'ticket_before':user['ticket'],'ticket_after':after_user['ticket'],
            'yuanbao_before':user.get('yuanbao'),'yuanbao_after':after_user.get('yuanbao'),
            'spirit_before':user.get('spirit'),'spirit_after':after_user.get('spirit'),
            'needs_password':reply.get('code')==502,
            'verified':reply.get('code')==200 and not reply.get('error') and after==expected and user['ticket']==after_user['ticket']}
    return result,after_info,after_user

def sell_rune(flow,info,user,entity_id,password='',refresh=None):
    rows={r['entityId']:r for r in rune_entries(info)}
    row=rows.get(entity_id)
    if not row:raise ValueError('所选灵符不在当前背包或已经镶嵌，请刷新')
    if row['locked']:raise ValueError('锁定灵符不能出售')
    if refresh is None or user.get('ticket') is None or user.get('yuanbao') is None:
        raise ValueError('缺少状态刷新或余额，未出售')
    before=set((info.get('bag') or {}).get('rune') or {})
    if entity_id not in before:raise ValueError('所选灵符不在背包')
    ticket_before,yuanbao_before=user['ticket'],user['yuanbao']
    spirit_before=int(info.get('spirit') or 0)
    params={'type':'rune','id':entity_id,'count':1}
    reply=flow.request('scene.itemHandler.sellObject',{**params,'password':password or ''})
    after_info=refresh()
    wallet=flow.request('connector.roleHandler.getUserInfo',{})
    if wallet.get('code')!=200 or wallet.get('error'):
        raise RuntimeError('出售已发送，余额核对失败；未重发，请刷新状态')
    after_user=wallet.get('user') or {}
    after=set((after_info.get('bag') or {}).get('rune') or {})
    spirit_gain=sum(int(g.get('count') or 0) for g in reply.get('give') or []
                    if g.get('type')=='coin' and g.get('subType')=='spirit')
    verified=(reply.get('code')==200 and not reply.get('error') and
              after==before-{entity_id} and
              ticket_before==after_user.get('ticket') and yuanbao_before==after_user.get('yuanbao') and
              int(after_info.get('spirit') or 0)-spirit_before==spirit_gain)
    result={'route':'scene.itemHandler.sellObject','params':params,'name':row['name'],
            'reply':reply,'verified':verified,'needs_password':reply.get('code')==502,
            'ticket_before':ticket_before,'ticket_after':after_user.get('ticket'),
            'yuanbao_before':yuanbao_before,'yuanbao_after':after_user.get('yuanbao'),
            'spirit_gain':spirit_gain,'runes_before':len(before),'runes_after':len(after)}
    return result,after_info,after_user

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',choices=list(TABLES),default='bag')
    parser.add_argument('--target',choices=list(TABLES))
    parser.add_argument('--sell',action='store_true')
    parser.add_argument('--item',type=int)
    parser.add_argument('--count',type=int,default=1)
    parser.add_argument('--sell-rune',action='append',default=[],metavar='ENTITY_ID')
    args=parser.parse_args()
    if args.sell_rune and (args.sell or args.target or args.item is not None):
        parser.error('灵符出售不能与材料出售或存取混用')
    if len(args.sell_rune)!=len(set(args.sell_rune)):
        parser.error('不能重复选择同一张灵符')
    from teacher_trial import connect,enter,checked
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
    slot=int(account.get('record_index',0));password=os.environ.pop('ZM5_WAREHOUSE_PASSWORD','');flow=None
    try:
        flow,info=connect(account,slot)
        user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'读取账号余额')['user']
        if args.sell_rune:
            # 整批先检查，防止选入锁定/镶嵌对象后先卖掉前几张。
            rows={r['entityId']:r for r in rune_entries(info)}
            for entity_id in args.sell_rune:
                if entity_id not in rows or rows[entity_id]['locked']:
                    raise ValueError('选中灵符已不在背包或被锁定，请刷新后重新选择')
            folder=ROOT/'bag_warehouse_reports';folder.mkdir(exist_ok=True)
            path=folder/(datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S_%f')+'_runes.json')
            report={'slot':slot,'selected':args.sell_rune,'results':[],'status':'running'}
            def journal():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            for entity_id in args.sell_rune:
                report['pending']=entity_id;journal()
                try:
                    result,info,user=sell_rune(flow,info,user,entity_id,password,lambda:enter(flow,slot))
                except Exception as exc:
                    report.update(status='uncertain',error_type=type(exc).__name__);journal();raise
                report['results'].append(result);report['pending']=None;journal()
                if not result['verified']:
                    report['status']='stopped';journal()
                    print('[灵符背包] '+('服务器要求二级密码，请填写后重新查询再选择出售。' if result['needs_password'] else '出售未通过核对，请刷新状态检查。')+'已停止后续出售，未自动重试。',flush=True)
                    break
            else:report['status']='verified';journal()
            print('[灵符背包] 已核对出售%s/%s张；报告：%s' %
                  (sum(r['verified'] for r in report['results']),len(args.sell_rune),path),flush=True)
        if args.target or args.sell:
            if args.item is None:raise ValueError('请选择道具')
            if args.sell:
                result,info,user=sell(flow,info,user,args.item,args.count,password,lambda:enter(flow,slot))
            else:
                result,info,user=move(flow,info,user,args.source,args.target,args.item,args.count,password,lambda:enter(flow,slot))
            folder=ROOT/'bag_warehouse_reports';folder.mkdir(exist_ok=True)
            path=folder/(datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S_%f')+'.json')
            path.write_text(json.dumps({'slot':slot,**result},ensure_ascii=False,indent=2),encoding='utf-8')
            print('[背包/仓库] '+json.dumps(result,ensure_ascii=False),flush=True)
            print('[背包/仓库] 报告：'+str(path),flush=True)
            if result['needs_password']:print('[背包/仓库] 服务器要求二级密码，请填写后再手动执行；未自动重试。',flush=True)
            elif not result['verified']:print('[背包/仓库] 操作未通过到账核对，请查看服务器回复；未自动重试。',flush=True)
        view=state(info,user);view['account']=str(account.get('username',''));view['slot']=slot
        print('__BAG_STATE__'+json.dumps(view,ensure_ascii=False),flush=True)
    finally:
        if flow:flow.disconnect()

if __name__=='__main__':main()
