"""GUI分类点券权限：不同三框组合、单次任务预算、请求前检查与账务核查。"""
import json,os,re
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parent
CATEGORIES={
 'daily':('日常任务1','101'), 'rewards':('日常任务2／领奖','110'),
 'dungeons':('日常副本／刷图','100'), 'festival':('节日／活动副本','111'),
 'weekly':('周常副本／领奖','011'), 'cultivation':('宠物／幻兽／养成','010'),
 'commerce':('商店／购买／兑换','001')}
ENV='ZM5_CATEGORY_SPEND_CONTEXT';_spent={};_halted=set()

def config(name):return json.loads((ROOT/'cg_config_out_cg1_20261019_1'/(name+'.json')).read_text(encoding='utf-8-sig'))
def matched(category,bits):return category in CATEGORIES and str(bits)==CATEGORIES[category][1]
def context():
    raw=os.environ.get(ENV)
    if not raw:return None
    obj=json.loads(raw)
    if not isinstance(obj,dict) or not obj.get('token'):raise RuntimeError('分类点券授权信息无效')
    return obj

def quote(route,data):
    # 已验证参数与配置的点券入口。未知点券分支不因三框开启而放行。
    if route in ('scene.arenaHandler.beginArenaBattleWithTicket','scene.petArenaHandler.beginArenaBattleWithTicket'):
        return {'category':'daily','cost':int(config('Challenge')['1' if '.arenaHandler.' in route else '2']['challengeAgainTicket']),'kind':'arena'}
    if route in ('scene.shopHandler.buyBlackMarket','scene.shopHandler.buyBlackMarket_activity'):
        from black_market import config as market_config,visible_goods
        _,active,table,_,_=market_config()
        expected='scene.shopHandler.buyBlackMarket'+('_activity' if active else '')
        if route!=expected:raise RuntimeError('黑市活动状态已改变，请重新读取')
        sid=str(data.get('shopId'));cfg=table.get(sid)
        if not cfg:raise RuntimeError('黑市商品配置未知')
        if cfg.get('consume_type')=='coin' and cfg.get('consume_subType')=='spirit':return None
        rows=visible_goods(table,{sid:0})
        if len(rows)!=1 or rows[0]['currency']!='点券':raise RuntimeError('该黑市点券商品尚未登记确认价格')
        return {'category':'commerce','cost':rows[0]['price'],'kind':'black_market','shop_id':sid,'activity':active}
    if route.startswith('scene.fairyHandler.'):
        name=route.rsplit('.',1)[-1];keys={'complete':'completeTicket','reset':'sendTicket','buyCollectCount':'sendTicket'}
        if name=='refreshCollectTask' and int(data.get('type',0))==1:keys[name]='refreshTicket'
        if name in keys:return {'category':'cultivation','cost':int(config('FairySendHelp')['1'][keys[name]]),'kind':name}
    if route in ('scene.shopHandler.buy','scene.shopHandler.double11Buy','scene.shopHandler.buyGlobalLimitShop'):
        table={'scene.shopHandler.buy':'Shop','scene.shopHandler.double11Buy':'Double11Shop','scene.shopHandler.buyGlobalLimitShop':'GlobalBuy'}[route]
        if table=='GlobalBuy':
            from old_shop import latest_global_config
            rows=json.loads((latest_global_config()/'GlobalBuy.json').read_text(encoding='utf-8-sig'))
        else:rows=config(table)
        cfg=rows.get(str(data.get('shopId')))
        if cfg is None:raise RuntimeError('商品配置未知，禁止购买')
        keys=str(cfg.get('consume_subType','')).split(',');values=str(cfg.get('consume_count','')).split(',')
        if len(keys)!=len(values):raise RuntimeError('商品价格配置不完整')
        if cfg.get('extTicket') not in (None,-1,'-1',0,'0'):raise RuntimeError('附加点券价格尚未完成核验，不开放购买')
        if 'ticket' in keys:
            count=data.get('count',1)
            if type(count) is not int or count<=0:raise RuntimeError('购买数量无效')
            return {'category':'commerce','cost':sum(int(v) for k,v in zip(keys,values) if k=='ticket')*count,'kind':'shop','config':cfg,'shop_id':str(data['shopId']),'count':count}
        return None
    name=route.rsplit('.',1)[-1].lower()
    if any(word in name for word in ('withticket','withgem','_ticket','fastbuy','buymonthcard','opensummerhighlvlogin')) or any(float(data.get(k,0) or 0)>0 for k in ('costGem','costTicket','useTicket','double','must')):
        raise RuntimeError('此付费分支尚未登记独立价格与次数检测，不开放：'+route)
    energy_routes = {
        'scene.activityHandler.copyBuyCountByEnergy': 0,
        'scene.activityHandler.buyLandformChallengeCnt': 1,
        'scene.activityHandler.buyDemonTowerCnt': 2,
        'scene.activityHandler.buyDungeonTreasureCnt': 4,
    }
    if route in energy_routes:
        rows=json.loads((ROOT/'time_energy_catalog.json').read_text(encoding='utf-8-sig'))
        energy_id=data.get('energyId')
        cfg=rows.get(str(energy_id)) if type(energy_id) is int else None
        category=energy_routes[route]
        expected={'energyId','dungeonId'} if category==0 else {'energyId'}
        if (not cfg or cfg.get('type')!=category or cfg.get('consume_type')!='coin'
                or cfg.get('consume_subType')!='energy' or int(cfg.get('consume_count',0))<=0
                or set(data)!=expected):
            raise RuntimeError('补次数参数未经核验；仅允许匹配配置的时光能量兑换')
        if category==0 and (type(data['dungeonId']) is not int
                or str(data['dungeonId']) not in str(cfg.get('dungeonId','')).split(';')):
            raise RuntimeError('时光能量兑换关卡不属于所选项目')
        return None
    return None

def raw(flow,route,data):
    reply=flow._request_sync(flow.game,route,data,15)
    if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):raise RuntimeError('点券操作前后状态读取失败，停止')
    return reply

def quota_check(q,info,flow,user=None,data=None):
    daily=info.get('everyDaySetting');weekly=info.get('everyWeekSetting')
    if not isinstance(daily,dict) or not isinstance(weekly,dict):raise RuntimeError('独立次数状态不完整')
    if q['kind'] in ('reset','complete'):
        from fairy_api import slots,slot_state
        state=slot_state(slots(info).get(int((data or {}).get('pos',-1))))
        if state['state']!='running':raise RuntimeError('此派遣位置未在进行中，不提交点券完成或召回')
    if q['kind']=='buyCollectCount':
        from fairy_api import quota
        if quota(info)['sendLeft']>0:raise RuntimeError('仍有免费派遣次数，不购买次数')
    if q['kind']=='refreshCollectTask':
        cap=int(config('FairySendHelp')['1']['refreshTicketMaxNum'])
        if int(daily.get('fairyRefreshTicketDayNum') or 0)>=cap:raise RuntimeError('幻兽点券刷新次数已用尽')
    if q['kind']=='arena':
        handler='arena' if q['category']=='daily' and flow._category_pending_route.startswith('scene.arenaHandler') else 'petArena'
        home=raw(flow,'scene.'+handler+'Handler.getArenaInfo',{})
        # 免费部分由既有挑战程序逐局检测；付费入口还要有实际对手和服务器主页。
        if not isinstance(home.get('self'),dict):raise RuntimeError('竞技场当前档状态不完整')
    if q['kind']=='black_market':
        route='scene.shopHandler.getBlackMarket'+('_activity' if q['activity'] else '')
        market=raw(flow,route,{})
        goods=(market.get('blackMarket') or {}).get('data')
        if not isinstance(goods,dict) or q['shop_id'] not in goods or bool(goods[q['shop_id']]):raise RuntimeError('黑市商品已购或不在当前列表，请重新读取')
    if q['kind']=='shop':
        cfg=q['config'];sid=q['shop_id'];n=q['count']
        now=datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
        for field,is_start in [('shelfTime',True),('underTime',False)]:
            value=cfg.get(field)
            if value in (None,'-1',-1,''):continue
            try:bound=datetime.strptime(str(value),'%Y/%m/%d-%H:%M:%S')
            except ValueError:raise RuntimeError('商品有效期格式未知，禁止点券购买')
            if (is_start and now<bound) or (not is_start and now>bound):raise RuntimeError('商品不在配置有效期内')
        from bag_warehouse import quantity
        for resource,count in zip(str(cfg['consume_subType']).split(','),str(cfg['consume_count']).split(',')):
            need=int(count)*n
            have=(user or {}).get(resource,info.get(resource))
            if have is None and resource.isdigit():have=quantity(info,'bag',int(resource))
            if have is None or float(have)<need:raise RuntimeError('商品所需货币或材料不足／未知：'+resource)
        for field,state in [('dayPurchaseMaxNum',daily),('weekPurchaseMaxNum',weekly)]:
            cap=int(cfg.get(field,-1) if cfg.get(field) is not None else -1)
            rec=(state.get('shopBuyCount') or {}).get(sid) or {}
            if cap>=0 and int(rec.get('buyCount') or 0)+n>cap:raise RuntimeError('商品每日或每周限购已达上限')
        # 有总量限制而返回未定义格式时，不猜测已购次数。
        cap=int(cfg.get('purchaseMaxNum',-1) if cfg.get('purchaseMaxNum') is not None else -1);rec=(info.get('shop') or {}).get(sid)
        if cap>=0:
            if rec is not None and (not isinstance(rec,dict) or 'buyCount' not in rec):raise RuntimeError('商品累计限购字段尚未核实，禁止购买')
            if int((rec or {}).get('buyCount') or 0)+n>cap:raise RuntimeError('商品累计限购已满')

def before(flow,route,data):
    ctx=context()
    if ctx is None:return None
    token=ctx['token']
    if token in _halted:raise RuntimeError('本次任务有未确认消耗或异常，禁止继续提交')
    q=quote(route,data)
    if q is None:return None
    permission=(ctx.get('permissions') or {}).get(q['category']) or {}
    if not matched(q['category'],permission.get('bits')):raise RuntimeError('未开启本类独立三框权限：'+CATEGORIES[q['category']][0])
    if str(getattr(flow,'uid',''))!=str(ctx.get('uid')):raise RuntimeError('点券权限不属于当前账号')
    if getattr(flow,'_category_slot',None)!=ctx.get('slot'):raise RuntimeError('点券权限不属于当前存档')
    budget=int(permission.get('budget',0));used=_spent.get((token,q['category']),0)
    if q['cost']<=0 or used+q['cost']>budget:raise RuntimeError('本类本次点券预算不足')
    user=raw(flow,'connector.roleHandler.getUserInfo',{}).get('user') or {}
    if user.get('ticket') is None or int(user['ticket'])<q['cost']:raise RuntimeError('点券余额不足或未知')
    info=raw(flow,'connector.entryHandler.entry',{'index':ctx['slot'],'userAgent':flow.user_agent}).get('info') or {}
    flow._category_pending_route=route;quota_check(q,info,flow,user,data)
    q.update(token=token,ticket_before=int(user['ticket']),route=route,params=data,phase='pending')
    folder=ROOT/'category_spend_reports';folder.mkdir(exist_ok=True);path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json');q['_path']=str(path);save(q)
    print('[分类点券检测] %s｜本次%s点券｜预算已用%s/%s｜%s'%(CATEGORIES[q['category']][0],q['cost'],used,budget,route),flush=True)
    return q

def save(q):
    Path(q['_path']).write_text(json.dumps({k:v for k,v in q.items() if k!='_path'},ensure_ascii=False,indent=2),encoding='utf-8')

def uncertain(q):
    if q:_halted.add(q['token']);q['phase']='uncertain';save(q)

def after(flow,route,data,reply,q):
    if route=='connector.entryHandler.entry' and isinstance(reply,dict) and reply.get('code')==200:
        flow._category_slot=data.get('index')
    if q is None:
        ctx=context()
        if ctx and isinstance(reply,dict) and any(str(c.get('subType','')).lower()=='ticket' and int(c.get('count',0))>0 for c in reply.get('consume') or []):
            _halted.add(ctx['token']);raise RuntimeError('未登记路由返回点券消耗，已停止本次任务，请核查余额')
        return
    q['reply']=reply
    try:
        user=raw(flow,'connector.roleHandler.getUserInfo',{}).get('user') or {};ticket=user.get('ticket')
        if ticket is None:raise RuntimeError('点券操作后余额未知')
        delta=q['ticket_before']-int(ticket);success=isinstance(reply,dict) and reply.get('code')==200 and not reply.get('error')
        if delta!=(q['cost'] if success else 0):raise RuntimeError('实际点券消耗与独立预算不一致')
        _spent[(q['token'],q['category'])]=_spent.get((q['token'],q['category']),0)+delta
        q.update(phase='verified',ticket_after=int(ticket),actual_cost=delta);save(q)
    except Exception:
        uncertain(q);raise
