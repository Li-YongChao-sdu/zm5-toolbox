"""联盟仓库按缺口最少售出材料后购买；每步核对，失败不重发。"""

import json,math

from pathlib import Path

from datetime import datetime

import union_warehouse as uw

ROOT=Path(__file__).resolve().parent



def donor_ids(value):
    values=[value] if isinstance(value,int) else value
    if not isinstance(values,(list,tuple)) or not values or any(type(k)!=int for k in values):raise ValueError('请勾选售出材料')
    return list(dict.fromkeys(values))

def funding_plan(config,state,info,item_id,count,donor_id):
    donors=donor_ids(donor_id)
    if item_id not in config or count<1:raise ValueError('购买材料或数量无效')
    if any(k not in config for k in donors):raise ValueError('售出材料配置不存在')
    row=config[item_id];currency=int(row['itemId'])
    if currency not in (uw.STONE,uw.JADE):raise ValueError('不支持该兑换货币')
    if state['stock'].get(str(item_id),0)<count:raise ValueError('仓库库存不足，未售出材料')
    if state['buyUsed']+count>int(row['buyMaxDayNum']):raise ValueError('今日购买次数不足，未售出材料')
    cost=uw.buy_cost(row,count,state['buyUsed'])
    if cost<0 or cost!=int(cost):raise ValueError('购买价格无效')
    cost=int(cost);gap=max(0,cost-uw.quantity(info,currency));left=gap;used=state['sellUsed'];sales=[]
    for key in donors:
        if left<=0:break
        donor=config[key]
        if key==item_id or int(donor['itemId'])!=currency:continue
        gain=int(donor['sell_count'])
        if gain<=0:raise ValueError('售出兑换数量无效')
        capacity=min(uw.quantity(info,key),max(0,int(donor['sellMaxDayNum'])-used))
        n=min(capacity,(left+gain-1)//gain)
        if n>0:sales.append({'item':key,'count':n});used+=n;left=max(0,left-n*gain)
    if left>0:raise ValueError('勾选材料的余额或售出额度不足，未售出任何材料')
    return {'currency':currency,'cost':cost,'shortfall':gap,'donation':sum(x['count'] for x in sales),'sales':sales}

def run(flow,info,reload_info,item_id,count,donor_id,password='',report_dir=None):

    donors=donor_ids(donor_id)
    cfg=uw.catalog();folder=Path(report_dir) if report_dir else ROOT/'union_warehouse_reports';folder.mkdir(parents=True,exist_ok=True)

    path=folder/(datetime.now().strftime('auto_%Y%m%d_%H%M%S_%f')+'.json');report={'buy_item':item_id,'count':count,'donor_items':donors,'actions':[],'phase':'reading'}

    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    def snapshot(i):

        state=uw.warehouse_status(flow,i,cfg);user=uw.checked(flow.request('connector.roleHandler.getUserInfo',{}),'余额')['user']

        if any(user.get(k) is None for k in ('ticket','yuanbao')):raise RuntimeError('货币余额缺失')

        return state|{'ticket':user['ticket'],'yuanbao':user['yuanbao'],'target':uw.quantity(i,item_id),'donors':{str(k):uw.quantity(i,k) for k in donors if k!=item_id},'reset':(i.get('everyDaySetting') or {}).get('resetTime')}

    def stable(a,b,currency):

        for key in ('ticket','yuanbao','contribution','leagueId','reset', 'stone' if currency==uw.JADE else 'jade'):

            if a[key]!=b[key]:raise RuntimeError('非预期变化：'+key+'；停止且不重发')

    def transact(action,item,n,i):

        event={'action':action,'item':item,'count':n,'phase':'pending'};report['actions'].append(event);save()

        _,reply=uw.transact(flow,i,action,item,n,pay='material',password=password)

        event.update(phase='returned',reply={k:reply[k] for k in ('code','consume','give') if k in reply});save()

        latest=reload_info();after=snapshot(latest);event['after']=after;save();return latest,after,event

    try:

        before=snapshot(info);plan=funding_plan(cfg,before,info,item_id,count,donor_id);report.update(before=before,plan=plan);save()

        current=before;currency=plan['currency'];money='jade' if currency==uw.JADE else 'stone';n=plan['donation']

        for sale in plan['sales']:
            key= sale['item'];amount=sale['count']
            print('[联盟仓库] 按顺序售出%s×%s'%(cfg[key]['name'],amount),flush=True)
            latest,after,event=transact('donate',key,amount,info);stable(current,after,currency)
            expected=dict(current['donors']);expected[str(key)]-=amount
            if after['donors']!=expected or after[money]!=current[money]+amount*int(cfg[key]['sell_count']) or after['sellUsed']!=current['sellUsed']+amount or after['buyUsed']!=current['buyUsed'] or after['target']!=current['target']:raise RuntimeError('售出结果核对失败，未继续购买')
            event['phase']='verified';info,current=latest,after;save()
        fresh=funding_plan(cfg,current,info,item_id,count,donor_id)

        if fresh['donation'] or fresh['cost']!=plan['cost']:raise RuntimeError('余额或价格变化，未继续购买')

        latest,after,event=transact('buy',item_id,count,info);stable(current,after,currency)

        if after['target']!=current['target']+count or after[money]!=current[money]-plan['cost'] or after['buyUsed']!=current['buyUsed']+count or after['sellUsed']!=current['sellUsed'] or after['donors']!=current['donors']:raise RuntimeError('购买结果核对失败，停止且不重发')

        event['phase']='verified';report.update(after=after,phase='verified');save()

        print('[联盟仓库] 已购买%s×%s；售出补足%s件；贡献、点券、元宝未变化'%(cfg[item_id]['name'],count,n),flush=True)

        return latest

    except Exception as exc:report.update(phase='stopped',error_type=type(exc).__name__);save();raise

    finally:print('[联盟仓库] 报告：'+str(path),flush=True)

