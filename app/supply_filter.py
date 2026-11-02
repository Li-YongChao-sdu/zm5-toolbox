"""所有游戏连接共用的场景拾取过滤；直接发放的奖励不能选择拒收。"""
import sys

IDS = {'101014001', '101014002', '101014003', '101014004'}

def enabled():
    config = sys.modules.get('daily_auto')
    if config is not None:
        return bool(getattr(config, 'PICKUP_SUPPLIES', False))
    try:
        import gui_config
        return bool(getattr(gui_config, 'PICKUP_SUPPLIES', False))
    except ImportError:
        return False

def excluded(drop):
    return isinstance(drop, dict) and drop.get('type') == 'item' and str(drop.get('subType')) in IDS

def before(flow, route, data):
    if enabled():
        return None
    drop = None
    if route == 'scene.copyHandler.syncDropInfo':
        scene = getattr(flow, '_supply_scene', None)
        if scene and 'index' in data and 'key' in data:
            client, server, drops = scene
            index = (int(data['index']) ^ (server ^ client)) - (int(data['key']) ^ client)
            drop = next((d for i, d in enumerate(drops)
                         if int(d.get('dropIndex', i)) == index), None)
    elif route == 'scene.copyHandler.getDungeonTreasureReward':
        drops = getattr(flow, '_supply_chest', [])
        index = int(data.get('i', -1))
        drop = next((d for i, d in enumerate(drops)
                     if int(d.get('dropIndex', i)) == index), None)
    if excluded(drop):
        print('[全局拾取] 已跳过萝卜/蟠桃/蓝瓶/蓝壶：%s×%s' %
              (drop.get('subType'), drop.get('count')), flush=True)
        return {'code': 200, 'give': [], 'filtered': True}
    return None

def after(flow, route, data, reply):
    if not isinstance(reply, dict) or reply.get('code') != 200:
        return
    if 'drops' in reply and 'rnd' in reply and 'rnd' in data:
        flow._supply_scene = (int(data['rnd']), int(reply['rnd']), reply.get('drops') or [])
    if route == 'scene.copyHandler.getDungeonTreasureDrop':
        flow._supply_chest = reply.get('drop') or []
    if route.endswith('finishSingleCopy') or route.endswith('entry'):
        flow._supply_scene = None
        flow._supply_chest = []
