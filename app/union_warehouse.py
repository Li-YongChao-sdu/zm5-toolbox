"""联盟仓库：查询、蛮荒材料捐献和仓库购买。"""

import argparse
import os

import json

from pathlib import Path



HERE = Path(__file__).resolve().parent

STONE, JADE = 101026007, 101026013



def catalog():

    with (HERE / 'feature_config' / 'UnionWarehouse.json').open(encoding='utf-8') as f:

        rows = json.load(f)

    values = rows.values() if isinstance(rows, dict) else rows

    return {int(row['id']): row for row in values}



def quantity(info, item_id):

    item = ((info.get('bag') or {}).get('item') or {}).get(str(item_id)) or {}

    return int(item.get('count') or 0) if isinstance(item, dict) else 0



def league_id(info):

    league = info.get('league') or {}

    return league.get('leagueId') or league.get('id') or info.get('leagueId')



def checked(reply, action):

    if not isinstance(reply, dict) or reply.get('error') or reply.get('code', 200) != 200:

        raise RuntimeError('%s失败：%s' % (action, reply))

    return reply



def warehouse_status(flow, info, config=None):

    config = config or catalog()

    lid = league_id(info)

    if not lid:

        raise RuntimeError('当前存档未加入联盟')

    reply = checked(flow.request('league.leagueHandler.getLeagueWarehouse', {'leagueId': lid}), '读取联盟仓库')

    stock = reply.get('warehouse')

    if not isinstance(stock, dict):

        raise RuntimeError('服务器未返回仓库库存：%s' % list(reply))

    daily = info.get('everyDaySetting') or {}

    league = info.get('league') or {}

    return {

        'name': info.get('name'), 'leagueId': lid,

        'stone': quantity(info, STONE), 'jade': quantity(info, JADE),

        'contribution': league.get('unionMoney', info.get('unionMoney')),

        'buyUsed': int(daily.get('leagueBuyItemCnt') or 0),

        'contributionBuyUsed': int(daily.get('unionMoneyBuyMaxDayNum') or 0),

        'sellUsed': int(daily.get('leagueSellItemCnt') or 0),

        'stock': {str(key): int(value) for key,value in stock.items()},

        'rows': [{'id': item_id, 'name': row['name'],

                  'stock': int(stock.get(str(item_id)) or 0),

                  'currency': int(row['itemId']),

                  'buyCount': int(row['buy_count']),

                  'currentCost': buy_cost(row,1,int(daily.get('leagueBuyItemCnt') or 0)),

                  'sellCount': int(row['sell_count']),

                  'unionMoney': int(row['unionMoney']),

                  'buyMax': int(row['buyMaxDayNum'])}

                 for item_id,row in sorted(config.items()) if int(stock.get(str(item_id)) or 0) > 0],

        'bag': [{'id': item_id, 'name': row['name'], 'count': quantity(info,item_id)}

                for item_id,row in sorted(config.items()) if quantity(info,item_id) > 0],

    }



def buy_cost(row, count, used):

    discount_count, factor = row['dayBuy'].split(';')

    discounted = max(0, min(count, int(discount_count)-used))

    # 客户端在已用次数小于优惠上限时显示这一档价格。

    return int(row['buy_count']) * (discounted * float(factor) + count-discounted)



def transact(flow, info, action, item_id, count, pay='material', password=''):

    config = catalog()

    if item_id not in config:

        raise ValueError('仅支持配置表内的蛮荒材料')

    if count < 1:

        raise ValueError('数量必须大于0')

    row = config[item_id]

    before = warehouse_status(flow, info, config)

    if action == 'donate':

        if quantity(info,item_id) < count:

            raise ValueError('背包材料不足')

        if before['sellUsed'] + count > int(row['sellMaxDayNum']):

            raise ValueError('超过今日捐献上限')

        route = 'scene.leagueHandler.sellItem'

        payload = {'itemId':item_id,'count':count,'type':'whSell','buyType':0}

    else:

        if before['stock'].get(str(item_id),0) < count:

            raise ValueError('联盟仓库库存不足')

        if pay == 'material':

            if before['buyUsed'] + count > int(row['buyMaxDayNum']):

                raise ValueError('超过今日购买上限')

            currency = int(row['itemId'])

            cost = buy_cost(row,count,before['buyUsed'])

            if quantity(info,currency) < cost:

                raise ValueError('蛮荒魂石/魂玉不足：需要%d，当前%d' % (cost,quantity(info,currency)))

            route = 'scene.leagueHandler.buyItem'

            buy_type = 0

        elif pay == 'contribution':

            used = int((info.get('everyDaySetting') or {}).get('unionMoneyBuyMaxDayNum') or 0)

            if used + count > int(row['unionMoneyBuyMaxDayNum']):

                raise ValueError('今日联盟贡献购买次数不足')

            if before['contribution'] is None:

                raise ValueError('无法读取联盟贡献余额')

            if int(before['contribution']) < count*int(row['unionMoney']):

                raise ValueError('联盟贡献不足')

            route = 'scene.leagueHandler.buyItemByUnionMoney'

            buy_type = 1

        else:

            raise ValueError('未知支付方式')

        payload = {'itemId':item_id,'count':count,'type':'whBuy','buyType':buy_type}

    payload['password'] = password or ''

    reply = flow.request(route,payload)

    if isinstance(reply,dict) and reply.get('code') == 502:

        raise RuntimeError('服务器要求二级密码；请在联盟仓库页面填写正确的二级密码')

    reply = checked(reply,action)

    return before, reply



def main():

    parser = argparse.ArgumentParser()

    parser.add_argument('--action',choices=['status','donate','buy'],default='status')

    parser.add_argument('--item',type=int)

    parser.add_argument('--count',type=int,default=1)

    parser.add_argument('--pay',choices=['material','contribution'],default='material')

    parser.add_argument('--password',default=os.environ.pop('ZM5_UNION_WAREHOUSE_PASSWORD',''))

    parser.add_argument('--auto-fund',type=int,action='append',metavar='DONOR_ITEM',help='余额不足时最少售出此材料补足，仅支持材料购买')

    parser.add_argument('--account-file',help=argparse.SUPPRESS)

    parser.add_argument('--slot',type=int,default=None,help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.action != 'status' and args.item is None:

        parser.error('捐献或购买必须指定材料ID')

    if args.auto_fund is not None and (args.action!='buy' or args.pay!='material'):

        parser.error('自动售出补足仅支持蛮荒魂石/魂玉购买')

    if args.account_file:

        from teacher_trial import connect, enter

        account = json.loads(Path(args.account_file).read_text(encoding='utf-8-sig'))

        slot = 0 if args.slot is None else args.slot

        flow, info = connect(account,slot)

        reload_info = lambda: enter(flow,slot)

    else:

        import daily_auto as da

        flow, info = da.login()

        reload_info = lambda: checked(flow.request('connector.entryHandler.entry',

                              {'index':da.RECORD_INDEX,'userAgent':flow.user_agent}),'重新读取存档').get('info')

    try:

        if args.auto_fund is not None:

            from union_warehouse_auto import run

            info=run(flow,info,reload_info,args.item,args.count,args.auto_fund,args.password)

        elif args.action != 'status':

            before, reply = transact(flow,info,args.action,args.item,args.count,args.pay,args.password)

            print('操作成功：%s 材料%d × %d；服务器返回 %s' %

                  (args.action,args.item,args.count,json.dumps({k:reply[k] for k in ('code','consume','give') if k in reply},ensure_ascii=False)))

            info = reload_info()

        status = warehouse_status(flow,info)

        print('角色：%s；蛮荒魂石 %d；蛮荒魂玉 %d；联盟贡献 %s' %

              (status['name'],status['stone'],status['jade'],status['contribution']))

        print('今日购买 %d 次；捐献 %d 次；仓库材料 %d 种' %

              (status['buyUsed'],status['sellUsed'],len(status['rows'])))

        for row in status['rows']:

            print('%s（%d）：仓库 %d；当前单件价 %d×%s；背包 %d' %

                  (row['name'],row['id'],row['stock'],row['currentCost'],

                   '魂石' if row['currency']==STONE else '魂玉',quantity(info,row['id'])))

        print('__UNION_STATUS__'+json.dumps(status,ensure_ascii=False))

    finally:

        flow.disconnect()



if __name__ == '__main__':

    main()

