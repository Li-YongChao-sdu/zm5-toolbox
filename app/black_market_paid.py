"""黑市点券单次确认购买；需GUI传入独立权限，不执行自动选购或刷新。"""
import argparse,json
from pathlib import Path
from datetime import datetime
from black_market import ROOT,ZONE,config,visible_goods
from teacher_trial import connect,enter,checked
from bag_warehouse import quantity,state,is_consume
from category_spend_guard import context,matched,quote

def authorize(account,slot,price):
    ctx=context();permission=((ctx or {}).get('permissions') or {}).get('commerce') or {}
    if not ctx or not matched('commerce',permission.get('bits')):raise ValueError('未开启商店独立点券权限')
    if str(ctx.get('uid'))!=str(account.get('uid')) or ctx.get('slot')!=slot:raise ValueError('点券授权与账号或槽位不符')
    if type(price) is not int or price<=0 or int(permission.get('budget',0))<price:raise ValueError('点券预算不足或价格无效')

def run(flow,account,slot,shop,price,report_dir=None):
    authorize(account,slot,price)
    folder,active,table,props,vips=config();suffix='_activity' if active else '';sid=str(shop);cfg=table.get(sid)
    route='scene.shopHandler.buyBlackMarket'+suffix
    registered=quote(route,{'shopId':int(shop)})
    if not registered or registered['category']!='commerce' or registered['cost']!=price:raise ValueError('当前价格与确认价格不符，请重新读取')
    directory=Path(report_dir) if report_dir else ROOT/'black_market_reports';directory.mkdir(parents=True,exist_ok=True)
    path=directory/(datetime.now(ZONE).strftime('paid_%Y%m%d_%H%M%S_%f')+'.json');report={'slot':slot,'shop':sid,'price':price,'status':'reading'}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def read():
        info=enter(flow,slot);user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'读取余额')['user']
        market=checked(flow.request('scene.shopHandler.getBlackMarket'+suffix,{}),'读取黑市');raw=(market.get('blackMarket') or {}).get('data')
        if not isinstance(raw,dict):raise RuntimeError('黑市商品数据缺失')
        daily=info.get('everyDaySetting')
        if not isinstance(daily,dict):raise RuntimeError('每日状态缺失')
        data={'ticket':user.get('ticket'),'yuanbao':user.get('yuanbao',info.get('yuanbao')),'spirit':info.get('spirit'),'free_used':int(daily.get('freeblackMarketNum'+suffix,0)),'day':datetime.now(ZONE).strftime('%Y-%m-%d'),'reset':daily.get('resetTime')}
        if any(data[k] is None for k in ('ticket','yuanbao','spirit')):raise RuntimeError('货币余额未知')
        return info,user,raw,data
    try:
        info,user,raw,before=read();report['before']=before;save()
        if sid not in raw or raw[sid]:raise ValueError('商品不在当前黑市或已购买')
        if before['ticket']<price:raise ValueError('点券不足')
        pid=str(cfg['sell_subType']);count=int(cfg['sell_count']);old=quantity(info,'bag',pid)
        kind='消耗品' if is_consume({},props.get(pid,{})) else '材料';cap=state(info,user,props)['capacity']['bag'][kind]
        if old==0 and (cap['max'] is None or cap['used']>=cap['max']):raise ValueError('背包空间不足或未知')
        report['pending']={'route':route,'shopId':int(shop),'old_count':old};save()
        reply=flow.request(route,{'shopId':int(shop)});report['reply']=reply;save()
        after_info,_,after_raw,after=read();report['after']=after;report['quantity']=[old,quantity(after_info,'bag',pid)]
        if not (isinstance(reply,dict) and reply.get('code')==200 and not reply.get('error') and before['ticket']-after['ticket']==price and all(before[k]==after[k] for k in ('yuanbao','spirit','free_used','day','reset')) and report['quantity'][1]-old==count and bool(after_raw.get(sid))):raise RuntimeError('点券购买未通过到账核对，停止，不自动重发')
        report.update(status='verified',pending=None);save()
        print('[黑市点券] %s×%s，点券%s→%s；道具到账核对通过。'%(cfg['name'],count,before['ticket'],after['ticket']),flush=True)
        vip=int((after_info.get('vip') or {}).get('level',0));limit=int(vips[str(vip)]['freeblackMarketNum'])
        payload={'slot':slot,'username':account.get('username'),'vip':vip,**after,'free_limit':limit,'free_remaining':max(0,limit-after['free_used']),'rows':visible_goods(table,after_raw),'activity':active}
        print('__BLACK_MARKET_STATE__'+json.dumps(payload,ensure_ascii=False),flush=True)
        return report
    except Exception as exc:report.update(status='stopped',error_type=type(exc).__name__);save();raise
    finally:print('[黑市点券] 报告：'+str(path),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--shop',type=int,required=True);p.add_argument('--price',type=int,required=True);p.add_argument('--slot',type=int,required=True);args=p.parse_args()
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));authorize(account,args.slot,args.price)
    if int(account.get('record_index',0))!=args.slot:raise ValueError('当前槽位已改变')
    flow=None
    try:flow,_=connect(account,args.slot);run(flow,account,args.slot,args.shop,args.price)
    finally:
        if flow:flow.disconnect()
