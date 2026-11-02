"""Shop配置浏览与单次购买测试，生成不含登录凭据的分享报告。"""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT=Path(__file__).resolve().parent
CONFIG=ROOT/'cg_config_out_cg1_20261012_1'
ZONE=timezone(timedelta(hours=8))
NAMES={0:'普通商店',1:'联盟商店',2:'中秋',4:'竞技商店',5:'宝石',6:'时光',7:'周年/圣诞历史混合',8:'藏宝',9:'斗宠',10:'春节/年兽',11:'充值积分',12:'元宵',13:'药园',14:'白菊绝版',15:'五一',16:'端午',19:'七夕',21:'重阳',23:'星斗',24:'试炼',25:'万妖',26:'经书',27:'暑期',28:'盛典',29:'魔龙',30:'师徒',31:'挑战GM材料',32:'光环',33:'宝券',34:'龙宫',35:'精气/真灵',36:'擂台积分',37:'GM切磋',38:'水晶签到',39:'篇章/妖王精血',41:'仙晶新手',42:'乱斗',44:'白骨',45:'圣兽币礼包',97:'周年集字',98:'特惠',99:'历史混合兑换'}
MONEY={'ticket':'点券','yuanbao':'元宝','spirit':'灵魂','rechargeMoney':'充值积分','rechargeMoney2':'充值积分2','arenaMoney':'竞技积分','petArenaMoney':'斗宠积分','baoquan':'宝券','gutou':'白骨','yuanxiaoMoney':'元宵积分','workersMoney':'劳动积分','unionMoney':'联盟贡献','petBtlMoney':'乱斗币','dailyTaskMoney':'活跃积分'}
MATERIAL_SHOP_CATEGORIES={'material_small':'材料快捷购买 · 小材料（木／矿／布）',
                          'material_boss':'材料快捷购买 · BOSS进阶材料',
                          'material_forest':'材料快捷购买 · 神兽森林材料'}
def shop_category(cfg):
    sid=int(cfg['id'])
    if int(cfg.get('type',-1))==99:
        if 99701<=sid<=99781:return 'material_small'
        if 99601<=sid<=99681:return 'material_boss'
        if 99501<=sid<=99544:return 'material_forest'
    return cfg['type']
# ShopMore未列出的分类，按客户端modules/shop/utils/ShopConst.as补全。
NAMES.update({17:'新手商店一',18:'新手商店二',20:'老玩家回归',22:'日常任务兑换',
              40:'白龙新手商店（玉珠）',43:'小周年商店',46:'GC新商店（GC_NEW_SHOP）'})

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def latest_global_config():
    candidates=[p for p in ROOT.glob('cg_config_out_cg1_*') if (p/'GlobalBuy.json').is_file() and (p/'Prop.json').is_file()]
    return max(candidates,key=lambda p:p.name) if candidates else CONFIG

def load_catalog(source='Shop'):
    if source not in ('Shop','Double11Shop','GlobalBuy','FestivalFree'):raise ValueError('不支持的商品配置表')
    directory=latest_global_config() if source in ('GlobalBuy','FestivalFree') else CONFIG
    props=read(directory/'Prop.json')
    if source=='FestivalFree':
        activities=read(directory/'Activity.json');rewards=read(directory/'Reward.json');shops={}
        for key,row in activities.items():
            if 'jieQiActivity' not in str(row.get('posName','')):continue
            reward=rewards.get(str(row.get('rewardId')))
            if not reward or reward.get('type')!='item':continue
            shops[key]=dict(row,type=0,sell_type='item',sell_subType=reward['subType'],sell_count=reward['count'],consume_type='coin',consume_subType='spirit',consume_count=0,purchaseMaxNum=row.get('receiveNum',1),freeGift=True)
    else:
        shops=read(directory/(source+'.json'))
    if source=='GlobalBuy':
        shops={k:v for k,v in shops.items() if v.get('consume_type')=='coin' and v.get('consume_subType')=='spirit' and not requires_ticket(v)}
    if source=='Double11Shop':
        shops={k:dict(v,type=3,shelfTime='-1',underTime='-1') for k,v in shops.items()}
    labels=dict(MONEY);labels.update({str(k):v.get('name',str(k)) for k,v in props.items()})
    return shops,labels

def purchase_request(source,shop_id):
    if source=='Double11Shop':return 'scene.shopHandler.double11Buy',{'shopId':int(shop_id)}
    if source=='FestivalFree':return 'scene.activityHandler.getResetActivityReward',{'activeId':int(shop_id)}
    if source=='GlobalBuy':return 'scene.shopHandler.buyGlobalLimitShop',{'shopId':int(shop_id),'count':1}
    if source=='Shop':return 'scene.shopHandler.buy',{'shopId':int(shop_id),'count':1}
    raise ValueError('不支持的商品配置表')

def costs(cfg):
    keys=str(cfg['consume_subType']).split(',');values=str(cfg['consume_count']).split(',')
    if len(keys)!=len(values):raise ValueError('多材料价格配置不完整')
    return list(zip(keys,values))

def requires_ticket(cfg):
    return 'ticket' in str(cfg.get('consume_subType','')).split(',') or cfg.get('extTicket') not in (None,'-1',-1,0,'0')

def price(cfg,labels):
    if cfg.get('freeGift'):return '免费领取（不调用付费购买）'
    text=' + '.join(f'{labels.get(k,k)}×{v}' for k,v in costs(cfg))
    if cfg.get('extTicket') not in (None,'-1',-1,0,'0'):
        text+=f"；额外点券规则 {cfg['extTicket']}（上限{cfg.get('extTicketMaxNum')}）"
    return text

def dated_state(cfg,now=None):
    if 'isOpen' in cfg:return '配置开放 isOpen=1' if cfg['isOpen']==1 else '配置隐藏 isOpen='+str(cfg['isOpen'])
    now=now or datetime.now(ZONE)
    for field,past in [('underTime',True),('shelfTime',False)]:
        raw=cfg.get(field)
        if raw in (None,-1,'-1',''):continue
        try:time=datetime.strptime(raw,'%Y/%m/%d-%H:%M:%S').replace(tzinfo=ZONE)
        except (ValueError,TypeError):return '日期格式待核对'
        if past and time<now:return '商品日期已过'
        if not past and time>now:return '尚未到上架时间'
    return '商品日期在期内' if cfg.get('underTime') not in (None,-1,'-1','') else '商品无独立期限'

def remaining_text(cfg,now=None):
    """按配置下架时间返回剩余时长文本。"""
    raw=cfg.get('underTime')
    if raw in (None,-1,'-1',''):return '无固定下架时间'
    now=now or datetime.now(ZONE)
    try:end=datetime.strptime(raw,'%Y/%m/%d-%H:%M:%S').replace(tzinfo=ZONE)
    except (ValueError,TypeError):return '日期格式待核对'
    left=int((end-now).total_seconds())
    if left<=0:return '已下架'
    days,rest=divmod(left,86400);hours,rest=divmod(rest,3600)
    if days:return '剩 %d 天 %d 小时'%(days,hours)
    return '剩 %d 小时 %d 分'%(hours,rest//60)

def inventory(info):
    result={}
    for tab,items in (info.get('bag') or {}).items():
        if not isinstance(items,dict):continue
        for key,item in items.items():
            if not isinstance(item,dict):continue
            pid=str(item.get('id',key));name=str(item.get('name') or pid)
            count=item.get('count',1)
            if not isinstance(count,(int,float)):continue
            entry=result.setdefault(f'{tab}/{pid}',{'id':pid,'tab':tab,'name':name,'count':0})
            entry['count']+=count
    return result

def snapshot(info,user,cfg):
    wallet={}
    for source,values in [('role',info),('user',user)]:
        for key,value in values.items():
            if isinstance(value,(int,float)) and any(w in key.lower() for w in ('money','ticket','spirit','yuanbao','point','stone','lingyu','jingshu','gutou')):
                wallet[source+'.'+key]=value
    wallet['role.baoquan.cnt']=(info.get('baoquan') or {}).get('cnt')
    for key,_ in costs(cfg):
        if isinstance(info.get(key),(int,float)):wallet['role.'+key]=info[key]
        if isinstance(user.get(key),(int,float)):wallet['user.'+key]=user[key]
    sid=str(cfg['id'])
    return {'wallet':wallet,'bag':inventory(info),
            'quota':{'shop':(info.get('shop') or {}).get(sid),
                     'daily':((info.get('everyDaySetting') or {}).get('shopBuyCount') or {}).get(sid)}}

def differences(before,after):
    wallet=[];items=[]
    for key in sorted(set(before['wallet'])|set(after['wallet'])):
        a,b=before['wallet'].get(key),after['wallet'].get(key)
        if a!=b:wallet.append({'field':key,'before':a,'after':b,'delta':b-a if isinstance(a,(int,float)) and isinstance(b,(int,float)) else None})
    for key in sorted(set(before['bag'])|set(after['bag'])):
        a,b=before['bag'].get(key),after['bag'].get(key);n=(b or {}).get('count',0)-(a or {}).get('count',0)
        if n:items.append({**(b or a),'before':(a or {}).get('count',0),'after':(b or {}).get('count',0),'delta':n})
    return {'wallet':wallet,'items':items,'quota_before':before['quota'],'quota_after':after['quota']}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shop',type=int,required=True)
    parser.add_argument('--catalog',choices=['Shop','Double11Shop','GlobalBuy','FestivalFree'],default='Shop')
    parser.add_argument('--buy',action='store_true',help='明确发送一次购买；默认只查询')
    args=parser.parse_args()
    shops,labels=load_catalog(args.catalog);cfg=shops.get(str(args.shop))
    if cfg is None:raise ValueError('商品不在本地配置中')
    from teacher_trial import connect,enter,checked
    account=read(ROOT/'account.local.json');slot=int(account.get('record_index',0))
    out=ROOT/'shop_test_reports';out.mkdir(exist_ok=True)
    route,params=purchase_request(args.catalog,args.shop)
    report={'time':datetime.now(ZONE).isoformat(),'slot':slot,'config':(latest_global_config() if args.catalog in ('GlobalBuy','FestivalFree') else CONFIG).name,'catalog':args.catalog,
            'shopId':args.shop,'product':cfg,'price':price(cfg,labels),'route':route,'requested':False}
    path=out/(datetime.now(ZONE).strftime('%Y%m%d_%H%M%S_%f')+f'_shop{args.shop}.json')
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    flow=None
    try:
        flow,info=connect(account,slot)
        user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'读取账号余额')['user']
        if user.get('ticket') is None:raise RuntimeError('无法确认点券余额')
        if args.catalog=='GlobalBuy':
            report['global_stock']=flow.request('scene.shopHandler.getLimitShopInfo',{'shopIds':[args.shop]})
            print('[限时灵魂商品] 全服库存：'+json.dumps(report['global_stock'],ensure_ascii=False),flush=True)
        before=snapshot(info,user,cfg);report['before']=before;save()
        print(f"[商店测试] 槽{slot}，商品{args.shop} {cfg['name']}；购买1次获得{cfg['sell_count']}；价格：{price(cfg,labels)}",flush=True)
        print('[商店测试] 商品日期：'+dated_state(cfg)+'；这不代表服务端允许购买',flush=True)
        print('[商店测试] 货币：'+json.dumps(before['wallet'],ensure_ascii=False),flush=True)
        if args.buy and args.catalog=='FestivalFree' and dated_state(cfg)!='商品日期在期内':
            raise RuntimeError('免费节气礼包不在配置领取期限，未发请求')
        if not args.buy:
            print('[商店测试] 仅查询，未发送购买请求',flush=True);return
        # 不预挡“材料不足/过期”，以便获取真实服务端回复；仅一次请求，无自动重试。
        report['requested']=True;report['params']=params;save()
        reply=flow.request(route,params);report['reply']=reply;save()
        print('[商店测试] 原始购买回复：'+json.dumps(reply,ensure_ascii=False),flush=True)
        latest=enter(flow,slot)
        wallet=checked(flow.request('connector.roleHandler.getUserInfo',{}),'核对账号余额')['user']
        report['after']=snapshot(latest,wallet,cfg)
        report['changes']=differences(before,report['after']);save()
        print('[商店测试] 货币/道具/次数变化：'+json.dumps(report['changes'],ensure_ascii=False),flush=True)
        print('[商店测试] 点券：'+str(user.get('ticket'))+'→'+str(wallet.get('ticket')),flush=True)
    except Exception as exc:
        report['error']=str(exc);save()
        print('[商店测试] '+str(exc)+'；未自动重发购买请求',flush=True)
        raise
    finally:
        save();print('[商店测试] 可分享测试报告：'+str(path),flush=True)
        if flow:flow.disconnect()

if __name__=='__main__':main()
