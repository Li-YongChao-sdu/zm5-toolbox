"""黑市点券自动购买：双重显式授权、六种四折白名单、VIP免费刷新。"""
import argparse,json,time
from pathlib import Path
from datetime import datetime
from black_market import ROOT,ZONE,TICKET_GOODS,config,visible_goods
from black_market_paid import authorize,run as buy_one
from category_spend_guard import context
from teacher_trial import connect,enter,checked

def selected_goods(goods,allow_ticket=False,auto_confirm=False):
    if not allow_ticket or not auto_confirm:raise ValueError('必须同时开启允许花点券和自动购买选中商品')
    if not isinstance(goods,list) or not goods or any(not isinstance(x,str) or x not in TICKET_GOODS for x in goods):raise ValueError('请明确勾选六种四折商品中的至少一种')
    return list(dict.fromkeys(goods))

def run(flow,account,slot,goods,allow_ticket=False,auto_confirm=False,report_dir=None,log=print):
    goods=selected_goods(goods,allow_ticket,auto_confirm)
    # Validates account/slot authorization before any purchase or refresh.
    authorize(account,slot,min(TICKET_GOODS[name] for name in goods))
    permission=context()['permissions']['commerce'];budget=int(permission['budget'])
    _,active,table,_,vips=config();suffix='_activity' if active else '';field='freeblackMarketNum'+suffix
    directory=Path(report_dir) if report_dir else ROOT/'black_market_reports';directory.mkdir(parents=True,exist_ok=True)
    path=directory/(datetime.now(ZONE).strftime('paid_auto_%Y%m%d_%H%M%S_%f')+'.json')
    report={'slot':slot,'selected_goods':goods,'budget':budget,'purchases':[],'refreshes':[],'status':'reading'}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def read():
        if config()[1]!=active:raise RuntimeError('黑市活动切换，停止并重新查询')
        info=enter(flow,slot);user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'读取余额')['user']
        market=checked(flow.request('scene.shopHandler.getBlackMarket'+suffix,{}),'读取黑市');raw=(market.get('blackMarket') or {}).get('data')
        if not isinstance(raw,dict):raise RuntimeError('黑市商品列表缺失')
        daily=info.get('everyDaySetting');vip=int((info.get('vip') or {}).get('level',0))
        if not isinstance(daily,dict) or str(vip) not in vips:raise RuntimeError('免费刷新次数未知')
        wallet={'ticket':user.get('ticket'),'yuanbao':user.get('yuanbao',info.get('yuanbao')),'spirit':info.get('spirit'),'used':int(daily.get(field,0)),'limit':int(vips[str(vip)]['freeblackMarketNum']),'day':datetime.now(ZONE).strftime('%Y-%m-%d'),'reset':daily.get('resetTime')}
        if any(wallet[k] is None for k in ('ticket','yuanbao','spirit')):raise RuntimeError('货币余额不完整')
        return raw,wallet
    def same_wallet(before,after,cost=0):
        if before['ticket']-after['ticket']!=cost or any(before[k]!=after[k] for k in ('yuanbao','spirit','day','reset')):raise RuntimeError('货币或日期变化不符，停止且不重发')
    try:
        raw,current=read();report['before']=current;save();spent=0
        while True:
            rows=visible_goods(table,raw)
            for row in rows:
                if row['currency']!='点券' or row['bought'] or row['name'] not in goods:continue
                price=row['price']
                if spent+price>budget or current['ticket']<price:
                    report.update(status='budget_or_balance_limit',after=current,spent=spent);save();log('[黑市点券自动] 预算或余额不足，停止购买和刷新',flush=True);return report
                report['pending']={'action':'buy','shop':row['id'],'price':price,'before':current};save()
                result=buy_one(flow,account,slot,int(row['id']),price,report_dir=directory)
                if result.get('status')!='verified':raise RuntimeError('单项购买未确认，停止')
                next_raw,after=read();same_wallet(current,after,price)
                if after['used']!=current['used']:raise RuntimeError('购买时刷新次数意外改变')
                spent+=price;report['purchases'].append({'id':row['id'],'name':row['name'],'count':row['count'],'price':price});report.update(pending=None,spent=spent,after=after)
                raw,current=next_raw,after;save();time.sleep(1.2)
            if current['used']>=current['limit']:break
            if spent+min(TICKET_GOODS[name] for name in goods)>budget:
                report['status']='budget_limit';break
            report['pending']={'action':'free_refresh','before':current};save()
            reply=flow.request('scene.shopHandler.freeForceRefreshBlackMarket'+suffix,{});report['last_reply']=reply;save()
            next_raw,after=read();same_wallet(current,after)
            if not (isinstance(reply,dict) and reply.get('code')==200 and not reply.get('error') and after['used']==current['used']+1):raise RuntimeError('免费刷新未确认，停止且不重发')
            report['refreshes'].append({'before':current['used'],'after':after['used']});raw,current=next_raw,after;report.update(pending=None,after=current);save();time.sleep(1.2)
        report.update(status='complete' if report['status']=='reading' else report['status'],after=current,spent=spent);save()
        log('[黑市点券自动] 结束：购买%s项，消耗%s点券，免费刷新%s次。'%(len(report['purchases']),spent,len(report['refreshes'])),flush=True)
        return report
    except Exception as exc:report.update(status='stopped',error_type=type(exc).__name__);save();raise
    finally:log('[黑市点券自动] 报告：'+str(path),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--goods',required=True);p.add_argument('--allow-ticket',action='store_true');p.add_argument('--auto-confirm',action='store_true');args=p.parse_args()
    goods=selected_goods(json.loads(args.goods),args.allow_ticket,args.auto_confirm)
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account.get('record_index',0));authorize(account,slot,min(TICKET_GOODS[name] for name in goods));flow=None
    try:flow,_=connect(account,slot);run(flow,account,slot,goods,args.allow_ticket,args.auto_confirm)
    finally:
        if flow:flow.disconnect()
