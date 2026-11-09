"""我的日常：限定任务范围，拦截点券入口和不明结果后的继续提交。"""
import re


def is_readonly_route(route):
    """get前缀不保证只读：领取buff、礼包、掉落和移除邮件都会改状态。"""
    name = route.rsplit('.', 1)[-1].lower()
    return (name.startswith(('get', 'query', 'entry', 'auth'))
            and not any(word in name for word in
                        ('reward', 'claim', 'commit', 'buffer', 'gift', 'remove',
                         'receive', 'lottery', 'drop', 'award')))

def configure(module,keys,catalog):
    allowed={row[1] for row in catalog if not row[3] and row[1].startswith('RUN_')}
    selected=set(keys)
    if not selected or not selected<=allowed:raise ValueError('包含不存在或付费的任务')
    if 'RUN_ELITE' in selected:selected.add('RUN_ACCEPT_DAILY_TASKS')
    for key,value in list(vars(module).items()):
        if key.startswith('RUN_') and isinstance(value,bool):setattr(module,key,key in selected)
    for key in ('ARENA_PAID_EXTRA','PET_ARENA_PAID_EXTRA','NIGHTMARE_CARD_PAID'):
        setattr(module,key,False)
    module.RUN_ACTIVITY=any(k.startswith('RUN_ACT_') for k in selected)
    module.ARENA_PAID_EXTRA_TIMES=0;module.PET_ARENA_PAID_EXTRA_TIMES=0
    module.PAID_CONFIRM_BITS='000';module.NIGHTMARE_CARD_STRATEGY='free'
    return selected

class FreeDailyFlow:
    def __init__(self,flow,shops):self.flow=flow;self.shops=shops;self.halted=False;self._mystery_stall=None
    def __getattr__(self,name):return getattr(self.flow,name)
    def deny(self,message):
        self.halted=True;raise RuntimeError('[我的日常] '+message+'；已停止后续请求')
    def request(self,route,params=None,*args,**kwargs):
        if self.halted:raise RuntimeError('[我的日常] 上一请求未确认或触发付费拦截，禁止继续请求')
        data=params or {};name=route.rsplit('.',1)[-1].lower()
        if any(x in name for x in ('withticket','withgem','fastbuy','pay','ticket')):
            self.deny('已拦截点券/付费路由：'+route)
        for key in ('costGem','costTicket','useTicket','ticket','pay','double','must'):
            try:positive=float(data.get(key,0) or 0)>0
            except (TypeError,ValueError):positive=True
            if positive:self.deny('已拦截付费参数：'+key)
        if 'buy' in name or 'purchase' in name:
            if route in ('scene.shopHandler.buyBlackMarket','scene.shopHandler.buyBlackMarket_activity'):
                from black_market import config
                _,active,table,_,_=config()
                expected='scene.shopHandler.buyBlackMarket'+('_activity' if active else '')
                shop=table.get(str(data.get('shopId')))
                if route!=expected or not shop or shop.get('consume_type')!='coin' or shop.get('consume_subType')!='spirit':self.deny('黑市仅允许当前配置的灵魂商品')
            elif route=='scene.shopHandler.buyMysteryShop':
                # 只能购买本连接最近一次查询确认的格位；每次购买后必须重新查询。
                stall=self._mystery_stall;self._mystery_stall=None
                if set(data)!={'stallNum'} or not isinstance(data.get('stallNum'),int) or isinstance(data['stallNum'],bool):
                    self.deny('神秘商店购买参数未确认')
                item=(stall or {}).get(str(data['stallNum']))
                if item is None:self.deny('神秘商店格位尚未查询确认')
                import json
                from game_version import latest_config_folder
                root=latest_config_folder()
                if root is None:self.deny('神秘商店配置未知')
                table=json.loads((root/'MysteryShop.json').read_text(encoding='utf-8-sig'))
                shop=table.get(str(item))
                if (not shop or shop.get('consume_type')!='coin' or shop.get('consume_subType')!='spirit'
                        or int(shop.get('stallNum',-1))!=data['stallNum'] or float(shop.get('consume_count',0))<=0):
                    self.deny('神秘商店仅允许已确认的灵魂商品')
            elif route=='scene.shopHandler.buy':shop=self.shops.get(str(data.get('shopId')))
            else:self.deny('此购买入口未经我的日常确认：'+route)
            if not shop:self.deny('商品价格配置未知')
            if shop.get('consume_type') not in ('coin','item') or not str(shop.get('consume_subType','')):
                self.deny('商品货币类型未知')
            if str(shop.get('consume_subType','')).lower() in ('ticket','gem') or str(shop.get('consume_type','')).lower() in ('ticket','gem') or float(shop.get('extTicket') or 0)>0:
                self.deny('商品需要点券')
        if route=='scene.shopHandler.getMysteryShop':self._mystery_stall=None
        readonly=is_readonly_route(route)
        try:reply=self.flow.request(route,params,*args,**kwargs)
        except Exception:
            if not readonly:self.halted=True
            raise
        if isinstance(reply,dict):
            if route=='scene.shopHandler.getMysteryShop' and reply.get('code')==200 and not reply.get('error'):
                stall=(reply.get('mysteryShop') or {}).get('stall')
                if isinstance(stall,dict):self._mystery_stall=dict(stall)
            for cost in reply.get('consume') or []:
                if str(cost.get('subType','')).lower() in ('ticket','gem'):
                    self.deny('回包出现非预期点券消耗，请核查记录')
        return reply
