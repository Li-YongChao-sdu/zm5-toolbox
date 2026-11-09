"""独立模块执行器：在原脚本外加非点券请求拦截，不改变其业务参数。"""
import json,runpy,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def non_ticket_exchange(script,route,data):
    """带 buy 字样但明确使用时光能量/联盟货币的原有接口。"""
    if script=='time_energy.py':
        from time_energy import CATALOG,ROUTES
        cfg=CATALOG.get(data.get('energyId'))
        return bool(cfg and route==ROUTES.get(int(cfg['type'])) and set(data)<=({'energyId','dungeonId'} if int(cfg['type'])==0 else {'energyId'}))
    if script=='union_warehouse.py' and route in ('scene.leagueHandler.buyItem','scene.leagueHandler.buyItemByUnionMoney'):
        from union_warehouse import catalog,STONE,JADE
        cfg=catalog().get(data.get('itemId'))
        kind=0 if route.endswith('.buyItem') else 1
        return bool(cfg and int(cfg['itemId']) in (STONE,JADE) and data.get('type')=='whBuy' and data.get('buyType')==kind and type(data.get('count')) is int and data['count']>0 and set(data)<={'itemId','count','type','buyType','password'})
    return False

def main():
    args=sys.argv[1:]
    if not args:raise ValueError('缺少模块脚本')
    target=Path(args[0]).resolve()
    if target.parent!=ROOT or target.suffix!='.py' or target.name in ('gui.py','my_daily_script.py'):
        raise ValueError('模块脚本不在工具箱内')
    from pypomelo.flow import GameLoginFlow
    from my_daily_policy import FreeDailyFlow,is_readonly_route
    from my_daily_execution import load_shops, FATAL_EXIT, is_expected_skip
    shops=load_shops()
    original=GameLoginFlow.request;guards={};approved=None
    if target.name=='old_shop.py' and '--buy' in args:
        from old_shop import load_catalog,requires_ticket,purchase_request
        source=args[args.index('--catalog')+1] if '--catalog' in args else 'Shop'
        sid=args[args.index('--shop')+1];cfg=load_catalog(source)[0].get(sid)
        if not cfg or requires_ticket(cfg):raise ValueError('我的日常不执行点券或未知价格商品')
        approved=purchase_request(source,int(sid))
    class Raw:
        def __init__(self,flow):self.flow=flow
        def request(self,*a,**kw):return original(self.flow,*a,**kw)
    def request(flow,route,params=None,*a,**kw):
        guard=guards.setdefault(flow,FreeDailyFlow(Raw(flow),shops))
        try:
            if (approved is not None and route==approved[0] and params==approved[1]) or non_ticket_exchange(target.name,route,params or {}):
                if guard.halted:raise RuntimeError('上次请求未确认，已停止')
                try:reply=original(flow,route,params,*a,**kw)
                except Exception:guard.halted=True;raise
                for cost in (reply.get('consume') or []) if isinstance(reply,dict) else []:
                    if str(cost.get('subType','')).lower() in ('ticket','gem'):guard.deny('出现非预期点券消耗')
            else:reply=guard.request(route,params,*a,**kw)
        except Exception:
            if not guard.halted:guard.failed=True
            raise
        readonly=is_readonly_route(route)
        if not isinstance(reply,dict) and not readonly:
            guard.deny('变更请求回包格式不明')
        if isinstance(reply,dict) and not readonly:
            if reply.get('error') or reply.get('code',200) not in (None,200):
                if not is_expected_skip(reply.get('error') or reply.get('code')):guard.failed=True
            else:guard.writes=getattr(guard,'writes',0)+1
        return reply
    GameLoginFlow.request=request;sys.argv=[str(target)]+args[1:];exit_code=0
    try:
        try:runpy.run_path(str(target),run_name='__main__')
        except SystemExit as exc:exit_code=exc.code or 0
        if any(g.halted for g in guards.values()):raise SystemExit(FATAL_EXIT)
        if exit_code:raise SystemExit(exit_code)
        if any(getattr(g,'failed',False) for g in guards.values()):raise SystemExit(1)
        if guards and not any(getattr(g,'writes',0) for g in guards.values()):raise SystemExit(3)
    except BaseException:
        if any(g.halted for g in guards.values()):raise SystemExit(FATAL_EXIT)
        raise
    finally:GameLoginFlow.request=original

if __name__=='__main__':main()
