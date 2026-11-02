"""庆典用药前先炼制两次，仅拾取止血草。"""
import random,time
from union_warehouse import quantity
from main_farm import _create,_finish

POTIONS=(101009001,101009002)
def potion_count(info):return sum(quantity(info,k) for k in POTIONS)
def craft_once(flow,info,refresh,checked):
    herb=quantity(info,101002000);before={k:quantity(info,k) for k in POTIONS}
    if herb<2:raise ValueError('止血草不足，未炼制')
    reply=checked(flow.request('scene.itemHandler.compose',{'composeId':1}))
    expected={k:0 for k in POTIONS}
    for row in reply.get('give') or []:
        if row.get('type')!='item' or str(row.get('subType')) not in ('101009001','101009002'):raise RuntimeError('炼制出现未知产出，停止')
        expected[int(row['subType'])]+=int(row.get('count',0))
    if any(n<0 for n in expected.values()):raise RuntimeError('炼制产出数量异常，停止')
    consumed=sum(int(row.get('count',0)) for row in reply.get('consume') or [] if row.get('type')=='item' and str(row.get('subType'))=='101002000')
    refresh()
    if consumed!=2 or quantity(info,101002000)!=herb-2 or any(quantity(info,k)!=before[k]+expected[k] for k in POTIONS):raise RuntimeError('炼丹材料或药品数量核对失败，停止且不重发')
    return expected

def prepare(flow,info,refresh,checked):
    target=4
    for attempt in range(3):
        refresh()
        if quantity(info,101002000)>=target:break
        print('[庆典任务] 先炼丹：止血草%s/4，第一关第%s局（最多3局）'%(quantity(info,101002000),attempt+1),flush=True)
        rnd,created=_create(flow,1);active=True
        try:
            for i,d in enumerate(created.get('drops') or []):
                if d.get('type')!='item' or str(d.get('subType'))!='101002000':continue
                salt=random.randint(1,10000)
                checked(flow.request('scene.copyHandler.syncDropInfo',{'index':(int(d.get('dropIndex',i))+salt)^(int(created['rnd'])^rnd),'key':salt^rnd}))
            time.sleep(25)
            checked(flow.request('scene.copyHandler.finishSingleCopy',{'win':1,'rnd':int(created['rnd'])^rnd,'star':3,'maxCombo':15,'killMonsterCnt':36,'useMagicWeaponCnt':3,'useBossCardCnt':0}))
            active=False
        finally:
            if active:
                try:_finish(flow,created,rnd,False)
                except Exception:pass
        refresh()
        if quantity(info,101002000)<target and attempt<2:time.sleep(5)
    refresh()
    if quantity(info,101002000)<target:
        print('[庆典任务] 首局及额外2局后仍不足4个止血草，停止炼丹和用药；未购买补药',flush=True)
        return False
    for index in range(2):
        output=craft_once(flow,info,refresh,checked)
        print('[庆典任务] 先炼丹：第%s/2次已核对，回元露产出%s'%(index+1,output),flush=True)
    return True


def spirit_backup(flow,info,refresh,checked,password,craft_remaining=True):
    """仅在补草明确不足后启用，购买缺口；不重试拒绝或结果不明的请求。"""
    refresh()
    # 有现成止血草时先尽量炼制，减少备用购买数量。
    for _ in range(min(2,quantity(info,101002000)//2) if craft_remaining else 0):
        craft_once(flow,info,refresh,checked)
    missing=max(0,2-potion_count(info))
    if not missing:return
    spirit_buy_potions(flow,info,refresh,checked,missing,password,label='[庆典任务] 备用')


def spirit_buy_potions(flow,info,refresh,checked,count,password,label='[备用补药]'):
    """用灵魂购买一品回元露：与庆典相同的路由与核对口径（scene.shopHandler.buy shopId=2）。

    要求带二级密码；核对灵魂扣减、道具到账、点券与元宝不变，任何一项不符立即停止且不重发。
    """
    count=int(count)
    if count<=0:return
    if not password:raise RuntimeError('%s需要填写二级密码，未购买'%label)
    import json
    from pathlib import Path
    row=json.loads((Path(__file__).resolve().parent/'cg_config_out_cg1_20261019_1/Shop.json').read_text(encoding='utf-8-sig')).get('2') or {}
    if row.get('consume_type')!='coin' or row.get('consume_subType')!='spirit' or str(row.get('sell_subType'))!='101009001' or int(row.get('sell_count',0))!=1:raise RuntimeError('%s商品配置不符，未购买'%label)
    cost=int(row['consume_count'])*count
    if int(info.get('spirit',0))<cost:raise RuntimeError('%s灵魂不足（需%s），未购买'%(label,cost))
    before_spirit=int(info['spirit']);before_count=quantity(info,101009001)
    before=checked(flow.request('connector.roleHandler.getUserInfo',{})).get('user') or {}
    if before.get('ticket') is None or before.get('yuanbao') is None:raise RuntimeError('%s货币余额缺失，未购买'%label)
    checked(flow.request('scene.shopHandler.buy',{'shopId':2,'count':count,'password':password}));refresh()
    after=checked(flow.request('connector.roleHandler.getUserInfo',{})).get('user') or {}
    if int(info.get('spirit',0))!=before_spirit-cost or quantity(info,101009001)!=before_count+count or any(before[k]!=after.get(k) for k in ('ticket','yuanbao')):raise RuntimeError('%s到账或消耗未通过核对，停止且不重发'%label)
    print('%s购买回元露%s瓶，灵魂-%s；点券、元宝未变化'%(label,count,cost),flush=True)
