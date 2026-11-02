"""黑市：筛选展示、灵魂购买、VIP免费刷新；不调用付费刷新或点券购买。"""
import argparse,json
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parent
ZONE=timezone(timedelta(hours=8))
TICKET_GOODS={'天清气':200,'地浊气':200,'风灵参':100,'火灵参':100,'水灵参':100,'土灵参':100}

def config():
    folders=sorted(ROOT.glob('cg_config_out_cg1_*'),reverse=True)
    folder=next(p for p in folders if (p/'BlackMarket.json').is_file())
    load=lambda name:json.loads((folder/(name+'.json')).read_text(encoding='utf-8-sig'))
    common=load('Common')['1'];activity=load('Activity').get(str(common.get('blackMarketActivityId')),{});active=False
    try:
        parse=lambda s:datetime.strptime(s,'%Y/%m/%d-%H:%M:%S').replace(tzinfo=ZONE)
        active=parse(activity['shelfTime'])<=datetime.now(ZONE)<=parse(activity['underTime'])
    except (ValueError,KeyError,TypeError):pass
    return folder,active,load('BlackMarket_activity' if active else 'BlackMarket'),load('Prop'),load('VIP')

def visible_goods(table,raw):
    result=[]
    for sid,bought in raw.items():
        cfg=table.get(str(sid))
        if not cfg:continue
        soul=cfg.get('consume_type')=='coin' and cfg.get('consume_subType')=='spirit'
        ticket=(cfg.get('consume_type')=='coin' and cfg.get('consume_subType')=='ticket'
                and cfg.get('name') in TICKET_GOODS and str(cfg.get('discount'))=='4'
                and int(cfg['consume_count'])==TICKET_GOODS[cfg['name']])
        if soul or ticket:
            result.append({'id':str(sid),'name':cfg['name'],'count':int(cfg['sell_count']),
                           'currency':'灵魂' if soul else '点券','price':int(cfg['consume_count']),
                           'discount':cfg.get('discount'),'bought':bool(bought),'can_buy':soul and not bool(bought)})
    return result

def main():
    from teacher_trial import connect,enter,checked
    from bag_warehouse import quantity,state,is_consume
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action',choices=['status','buy','refresh'],default='status')
    parser.add_argument('--shop',type=int)
    args=parser.parse_args()
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account.get('record_index',0))
    folder,active,table,props,vips=config();suffix='_activity' if active else ''
    free_field='freeblackMarketNum'+suffix
    route=lambda name:'scene.shopHandler.'+name+suffix
    output=ROOT/'black_market_reports';output.mkdir(exist_ok=True)
    path=output/(datetime.now(ZONE).strftime('%Y%m%d_%H%M%S_%f')+'.json')
    report={'slot':slot,'config':folder.name,'activity':active,'action':args.action};flow=None
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def current():
        info=enter(flow,slot);user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'读取余额')['user']
        if user.get('ticket') is None or info.get('spirit') is None:raise RuntimeError('缺少点券或灵魂余额')
        market=checked(flow.request(route('getBlackMarket'),{}),'读取黑市')
        raw=(market.get('blackMarket') or {}).get('data')
        if not isinstance(raw,dict):raise RuntimeError('未取得有效黑市商品列表')
        daily=info.get('everyDaySetting')
        if not isinstance(daily,dict):raise RuntimeError('缺少每日次数数据')
        vip=int((info.get('vip') or {}).get('level',0));limit=int(vips[str(vip)]['freeblackMarketNum']);used=int(daily.get(free_field,0))
        payload={'slot':slot,'username':account.get('username'),'vip':vip,'ticket':user['ticket'],'spirit':info['spirit'],
                 'free_limit':limit,'free_used':used,'free_remaining':max(0,limit-used),'rows':visible_goods(table,raw),'activity':active}
        return info,user,raw,payload
    try:
        flow,_=connect(account,slot)
        info,user,raw,before=current();report['before']=before;save()
        print('[黑市] 槽%d VIP%d，灵魂%s，点券%s；免费刷新剩余%d/%d' % (slot,before['vip'],before['spirit'],before['ticket'],before['free_remaining'],before['free_limit']),flush=True)
        if args.action!='status':
            if args.action=='buy':
                sid=str(args.shop);cfg=table.get(sid)
                if not cfg or not any(v['id']==sid and v['can_buy'] for v in before['rows']):raise RuntimeError('只允许购买当前未购的灵魂商品；点券商品仅展示')
                cost=int(cfg['consume_count']);pid=str(cfg['sell_subType']);count=int(cfg['sell_count'])
                if cost<0 or before['spirit']<cost:raise RuntimeError('灵魂不足，未购买')
                old_count=quantity(info,'bag',pid);kind='消耗品' if is_consume({},props.get(pid,{})) else '材料'
                capacity=state(info,user,props)['capacity']['bag'][kind]
                if old_count==0 and (capacity['max'] is None or capacity['used']>=capacity['max']):raise RuntimeError('对应背包无可确认空格，未购买')
                request_route=route('buyBlackMarket');params={'shopId':int(sid)}
                report['product']=cfg;report['old_count']=old_count
            else:
                if before['free_remaining']<=0:raise RuntimeError('免费刷新次数已用完，未调用付费刷新')
                request_route=route('freeForceRefreshBlackMarket');params={}
            report['pending']={'route':request_route,'params':params};save()
            reply=flow.request(request_route,params);report['reply']=reply;save()
            print('[黑市] 原始回复：'+json.dumps(reply,ensure_ascii=False),flush=True)
            after_info,_,_,after=current();report['after']=after
            accepted=isinstance(reply,dict) and reply.get('code')==200 and not reply.get('error')
            if args.action=='buy':
                new_count=quantity(after_info,'bag',pid);report['quantity']=[old_count,new_count]
                verified=accepted and new_count-old_count==count and before['spirit']-after['spirit']==cost
            else:verified=accepted and after['free_used']==before['free_used']+1 and after['spirit']==before['spirit']
            report['verified']=verified and before['ticket']==after['ticket'];save()
            print('[黑市] 核对：'+json.dumps({'verified':report['verified'],'ticket':[before['ticket'],after['ticket']],'spirit':[before['spirit'],after['spirit']],'quantity':report.get('quantity'),'free_used':[before['free_used'],after['free_used']]},ensure_ascii=False),flush=True)
            print('__BLACK_MARKET_STATE__'+json.dumps(after,ensure_ascii=False),flush=True)
            if not report['verified']:raise RuntimeError('操作未通过到账/消耗核对，已停止，不自动重发')
        else:print('__BLACK_MARKET_STATE__'+json.dumps(before,ensure_ascii=False),flush=True)
    except Exception as exc:
        report['error']=str(exc);save();print('[黑市] '+str(exc)+'；未自动重试',flush=True);raise
    finally:
        save();print('[黑市] 报告：'+str(path),flush=True)
        if flow:flow.disconnect()

if __name__=='__main__':main()
