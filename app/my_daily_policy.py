"""我的日常：限定任务范围，拦截点券入口和不明结果后的继续提交。"""
import re

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
    def __init__(self,flow,shops):self.flow=flow;self.shops=shops;self.halted=False
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
            elif route=='scene.shopHandler.buy':shop=self.shops.get(str(data.get('shopId')))
            else:self.deny('此购买入口未经我的日常确认：'+route)
            if not shop:self.deny('商品价格配置未知')
            if shop.get('consume_type') not in ('coin','item') or not str(shop.get('consume_subType','')):
                self.deny('商品货币类型未知')
            if str(shop.get('consume_subType','')).lower() in ('ticket','gem') or str(shop.get('consume_type','')).lower() in ('ticket','gem') or float(shop.get('extTicket') or 0)>0:
                self.deny('商品需要点券')
        readonly=name.startswith(('get','query','entry','auth')) and not any(x in name for x in ('reward','claim','commit'))
        try:reply=self.flow.request(route,params,*args,**kwargs)
        except Exception:
            if not readonly:self.halted=True
            raise
        if isinstance(reply,dict):
            for cost in reply.get('consume') or []:
                if str(cost.get('subType','')).lower() in ('ticket','gem'):
                    self.deny('回包出现非预期点券消耗，请核查记录')
        return reply
