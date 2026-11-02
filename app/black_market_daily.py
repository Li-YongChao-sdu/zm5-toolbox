"""每日黑市：只买灵魂商品，自动使用VIP当天剩余免费刷新次数。"""
import argparse,json,time
from datetime import datetime
from pathlib import Path
from black_market import config,visible_goods,ROOT,ZONE
from teacher_trial import connect,enter,checked
from bag_warehouse import quantity,state,is_consume

def soul_product(cfg):
    return isinstance(cfg,dict) and cfg.get('consume_type')=='coin' and cfg.get('consume_subType')=='spirit'

def run(flow,slot,account=None,report_dir=None,log=print):
    folder,active,table,props,vips=config();suffix='_activity' if active else ''
    field='freeblackMarketNum'+suffix;route=lambda name:'scene.shopHandler.'+name+suffix
    directory=Path(report_dir) if report_dir else ROOT/'black_market_reports';directory.mkdir(exist_ok=True,parents=True)
    path=directory/(datetime.now(ZONE).strftime('daily_%Y%m%d_%H%M%S_%f')+'.json')
    report={'slot':slot,'activity':active,'refresh_limit':None,'purchases':[],'refreshes':[],'status':'reading'}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def read():
        info=enter(flow,slot);user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'读取余额')['user']
        ticket=user.get('ticket');yuanbao=user.get('yuanbao',info.get('yuanbao'));spirit=info.get('spirit')
        if any(x is None for x in (ticket,yuanbao,spirit)):raise RuntimeError('货币余额不完整，停止')
        daily=info.get('everyDaySetting');vip=int((info.get('vip') or {}).get('level',0))
        if not isinstance(daily,dict) or str(vip) not in vips:raise RuntimeError('每日次数或VIP配置缺失')
        market=checked(flow.request(route('getBlackMarket'),{}),'读取黑市');raw=(market.get('blackMarket') or {}).get('data')
        if not isinstance(raw,dict):raise RuntimeError('黑市列表缺失')
        used=int(daily.get(field,0));limit=int(vips[str(vip)]['freeblackMarketNum'])
        payload={'slot':slot,'username':(account or {}).get('username'),'vip':vip,'ticket':ticket,'yuanbao':yuanbao,'spirit':spirit,'free_used':used,'free_limit':limit,'free_remaining':max(0,limit-used),'rows':visible_goods(table,raw),'activity':active,'day':datetime.now(ZONE).strftime('%Y-%m-%d'),'reset':daily.get('resetTime')}
        return info,user,raw,payload
    def verify_wallet(before,after):
        if any(before[k]!=after[k] for k in ('ticket','yuanbao','day','reset')):raise RuntimeError('点券、元宝或日期发生变化，停止，不重发')
    try:
        info,user,raw,current=read();target=current['free_limit'];report['refresh_limit']=target;report['before']=current;save()
        while True:
            # Each displayed product is bought at most once per list; only spirit currency is accepted.
            for sid in list(raw):
                cfg=table.get(str(sid))
                if raw[sid] or not soul_product(cfg):continue
                price=int(cfg['consume_count']);pid=str(cfg['sell_subType']);count=int(cfg['sell_count'])
                if price<0 or count<=0:raise RuntimeError('商品价格或数量配置无效')
                if current['spirit']<price:
                    log('[黑市日常] 灵魂不足，跳过'+str(cfg.get('name',sid)),flush=True);continue
                old=quantity(info,'bag',pid);kind='消耗品' if is_consume({},props.get(pid,{})) else '材料'
                capacity=state(info,user,props)['capacity']['bag'][kind]
                if old==0 and (capacity['max'] is None or capacity['used']>=capacity['max']):
                    log('[黑市日常] 背包空间不足，停止本项，未购买或刷新',flush=True);report['status']='bag_full';report['after']=current;save();return report
                report['pending']={'route':route('buyBlackMarket'),'shopId':str(sid),'before':current,'old_count':old};save()
                reply=flow.request(route('buyBlackMarket'),{'shopId':int(sid)});report['last_reply']=reply;save()
                next_info,next_user,next_raw,after=read();verify_wallet(current,after)
                if not (isinstance(reply,dict) and reply.get('code')==200 and not reply.get('error') and quantity(next_info,'bag',pid)-old==count and current['spirit']-after['spirit']==price and after['free_used']==current['free_used'] and bool(next_raw.get(str(sid),next_raw.get(sid)))):
                    raise RuntimeError('购买结果未通过核对，停止且不重发')
                report['purchases'].append({'id':str(sid),'name':cfg.get('name'),'count':count,'spirit_cost':price});report['pending']=None
                info,user,raw,current=next_info,next_user,next_raw,after;report['after']=current;save()
                log('[黑市日常] 已购%s×%s，灵魂-%s'%(cfg.get('name',sid),count,price),flush=True);time.sleep(1.2)
            if current['free_used']>=target or current['free_remaining']<=0:break
            report['pending']={'route':route('freeForceRefreshBlackMarket'),'before':current};save()
            reply=flow.request(route('freeForceRefreshBlackMarket'),{});report['last_reply']=reply;save()
            next_info,next_user,next_raw,after=read();verify_wallet(current,after)
            if not (isinstance(reply,dict) and reply.get('code')==200 and not reply.get('error') and after['free_used']==current['free_used']+1 and after['spirit']==current['spirit']):raise RuntimeError('免费刷新未通过核对，停止且不重发')
            report['refreshes'].append({'before':current['free_used'],'after':after['free_used']});report['pending']=None
            info,user,raw,current=next_info,next_user,next_raw,after;report['after']=current;save();time.sleep(1.2)
        report.update(status='complete',after=current);save()
        log('[黑市日常] 完成：购买%s项；本次免费刷新%s次，今日已刷新%s/%s。'%(len(report['purchases']),len(report['refreshes']),current['free_used'],target),flush=True)
        log('__BLACK_MARKET_STATE__'+json.dumps(current,ensure_ascii=False),flush=True)
        return report
    except Exception as exc:report.update(status='stopped',error_type=type(exc).__name__);save();raise
    finally:log('[黑市日常] 报告：'+str(path),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.parse_args()
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account.get('record_index',0));flow=None
    try:flow,_=connect(account,slot);run(flow,slot,account=account)
    finally:
        if flow:flow.disconnect()
