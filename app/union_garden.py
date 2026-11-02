"""联盟药园：仅本账号已开放土地，普通收获和已有种子种植。"""
import json
import time
from pathlib import Path


def catalog():
    rows=json.loads((Path(__file__).parent/'feature_config'/'GardenPlant.json').read_text(encoding='utf-8'))
    return {int(row['id']):row for row in rows.values()}


def checked(reply):
    if isinstance(reply, dict) and reply.get('code') == 502:
        raise RuntimeError('购买需要正确的二级密码，已停止该账号后续操作')
    if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):
        raise RuntimeError('药园操作失败：'+str((reply or {}).get('error') or (reply or {}).get('code')))
    return reply


def classify(soil,now,plants):
    if not soil or not soil.get('plantId'): return '空地'
    config=plants.get(int(soil['plantId']))
    if not config or any(key not in soil for key in ('finishTime','pickNum','fertilizeNum')):
        return '状态未知'
    if float(soil['finishTime'])>now: return '成长中'
    if int(soil['pickNum'])==0: return '可收获'
    if int(soil['pickNum'])+int(soil['fertilizeNum'])>=int(config['fruiCount']):
        return '已无领取次数'
    return '普通收获已领取，仍可琼浆浇灌'


def run_garden(account,slot,label,options):
    from teacher_trial import connect, enter
    plants=catalog()
    selected=int(options.garden_plant or 0)
    if selected and selected not in plants: raise ValueError('种子不在配置表中')
    mode = getattr(options, 'garden_mode', 'direct')
    limit = int(getattr(options, 'garden_count', 1))
    if limit < 0: raise ValueError('种植数量不能为负数')
    password = getattr(options, 'garden_password', '')
    if selected and mode == 'buy' and not password:
        raise ValueError('购买并种植须填写该账号的二级密码')
    shops = json.loads((Path(__file__).parent/'feature_config'/'GardenSeedShop.json').read_text(encoding='utf-8'))
    planted = 0
    flow,info=connect(account,slot)
    try:
        def wallet():
            user=checked(flow.request('connector.roleHandler.getUserInfo',{})).get('user') or {}
            if 'ticket' not in user: raise RuntimeError('无法读取点券，停止操作')
            return user['ticket']
        original=wallet()
        def read():
            data=checked(flow.request('scene.gardenHandler.getGardenInfo',{})).get('garden')
            if not isinstance(data,dict) or str(data.get('uid'))!=str(account['uid']):
                raise RuntimeError('无法确认自己的药园')
            if not all(key in data for key in ('soil','soilCnt','serverTime')):
                raise RuntimeError('药园资料不完整')
            return data
        def mutate(action,param):
            reply=checked(flow.request('scene.gardenHandler.'+action,param))
            if wallet()!=original: raise RuntimeError('点券发生变化，停止后续操作')
            print('[%s] %s 地块%s；奖励%s；点券不变'%(label,action,param['soilIndex'],reply.get('give') or []),flush=True)
            time.sleep(2)
            return read()
        garden=read()
        for pos in range(int(garden['soilCnt'])):
            soil=(garden['soil'] or {}).get(str(pos)) or (garden['soil'] or {}).get(pos) or {}
            state=classify(soil,float(garden['serverTime']),plants)
            plant=plants.get(int(soil.get('plantId') or 0),{})
            print('[%s] 地块%s：%s，%s'%(label,pos,plant.get('name','空地'),state),flush=True)
            if plant and all(k in soil for k in ('finishTime','pickNum','fertilizeNum')):
                print('[%s] 剩余成长%.1f小时；普通领取%s；琼浆剩余%s次' %
                      (label, max(0,float(soil['finishTime'])-float(garden['serverTime']))/3600000,
                       max(0,1-int(soil['pickNum'])),
                       max(0,int(plant['fruiCount'])-1-int(soil['fertilizeNum']))), flush=True)
            param={'soilIndex':pos,'plantId':soil.get('plantId'),'targetId':garden['uid'],'ticket':0}
            if options.garden_pick and state=='可收获':
                garden=mutate('pick',param)
                soil=(garden['soil'] or {}).get(str(pos)) or (garden['soil'] or {}).get(pos) or {}
                state=classify(soil,float(garden['serverTime']),plants)
            if options.garden_uproot and state=='已无领取次数':
                garden=mutate('uproot',param)
                soil=(garden['soil'] or {}).get(str(pos)) or (garden['soil'] or {}).get(pos) or {}
                state=classify(soil,float(garden['serverTime']),plants)
            if selected and state=='空地' and (limit == 0 or planted < limit):
                info=enter(flow,slot)
                if mode == 'buy':
                    row = next((r for r in shops.values() if int(r['sell_subType'])==int(plants[selected]['seedPropId'])), None)
                    if not row or row['consume_type']!='coin' or row['consume_subType']!='unionMoney':
                        raise ValueError('所选种子没有贡献购买配置')
                    cost = int(row['consume_count'])
                    balance = int((info.get('league') or {}).get('unionMoney', -1))
                    if balance < cost: raise ValueError('联盟贡献不足')
                    seed = str(plants[selected]['seedPropId'])
                    before_count = int((((info.get('bag') or {}).get('item') or {}).get(seed) or {}).get('count') or 0)
                    bought = checked(flow.request('scene.shopHandler.buy', {'shopId':int(row['id']), 'count':1, 'password':password}))
                    if wallet()!=original: raise RuntimeError('点券发生变化，停止后续操作')
                    info=enter(flow,slot)
                    after_count = int((((info.get('bag') or {}).get('item') or {}).get(seed) or {}).get('count') or 0)
                    if after_count != before_count+1: raise RuntimeError('购买种子未确认入包，停止种植')
                    print('[%s] 贡献购买种子1颗；贡献%s→%s'%(label,balance,(info.get('league') or {}).get('unionMoney')),flush=True)
                item=((info.get('bag') or {}).get('item') or {}).get(str(plants[selected]['seedPropId'])) or {}
                if int(item.get('count') or 0)<=0:
                    print('[%s] 所选种子不足，跳过种植'%(label),flush=True)
                    continue
                garden=mutate('sow',{'soilIndex':pos,'plantId':selected,'type':0})
                planted += 1
        print('[%s] 药园处理完成；点券%s→%s'%(label,original,wallet()),flush=True)
        return True
    finally:
        flow.disconnect()
