"""竞技场／斗宠报名：路由与参数按客户端确认（scene.*Handler.applyFor，{"index":0}）。

客户端依据 EveryWeekSetting.applyForArenaTime / applyForPetArenaTime 判断是否已报名：
大于 0 视为本周已报名（见 ArenaModule.as 报名图标逻辑）。
"""
from datetime import datetime, timedelta, timezone

ROUTES = {'arena': 'scene.arenaHandler.applyFor',
          'petArena': 'scene.petArenaHandler.applyFor'}
FIELDS = {'arena': 'applyForArenaTime', 'petArena': 'applyForPetArenaTime'}
LABELS = {'arena': '竞技场', 'petArena': '斗宠大会'}


def applied_time(info, handler):
    """从 entry 返回的存档 info 读取本周报名时间（毫秒），未报名返回 0。"""
    weekly = (info or {}).get('everyWeekSetting') or {}
    try:
        return float(weekly.get(FIELDS[handler]) or 0)
    except (TypeError, ValueError):
        return 0


def entry_info(flow, slot=None):
    """重新读一次存档 info；报名状态也可能出现在 getArenaInfo 回包里。"""
    if slot is None:
        from daily_auto import RECORD_INDEX
        slot = RECORD_INDEX
    r = flow.request('connector.entryHandler.entry',
                     {'index': int(slot), 'userAgent': flow.user_agent})
    if isinstance(r, dict) and not r.get('error'):
        return r.get('info') or {}
    return {}


def _rank(info):
    """读取当前存档排名；未上榜/未报名通常是 -1。"""
    try:
        value = ((info or {}).get('self') or {}).get('rank')
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def enrolled(info, handler):
    """本周已报名：报名时间>0，或已进入榜单(rank>=0)。"""
    if applied_time(info, handler) > 0:
        return True
    rank = _rank(info)
    return rank is not None and rank >= 0


def registration_open(now=None):
    """报名时段：周五16:00至周日22:00（北京时间）。"""
    now = now or datetime.now(timezone(timedelta(hours=8)))
    weekday = now.weekday()
    if weekday == 4:      # 周五
        return now.hour >= 16
    if weekday == 5:      # 周六
        return True
    if weekday == 6:      # 周日
        return now.hour < 22
    return False


def _merge_home(flow, handler, info):
    """合并 getArenaInfo 的报名状态；部分账号的 everyWeekSetting 只在竞技场回包里。"""
    home = flow.request('scene.%sHandler.getArenaInfo' % handler, {})
    if not isinstance(home, dict) or home.get('error'):
        return info
    merged = dict(info or {})
    weekly = dict(merged.get('everyWeekSetting') or {})
    weekly.update(home.get('everyWeekSetting') or {})
    merged['everyWeekSetting'] = weekly
    if home.get('self') is not None:
        merged['self'] = home['self']
    if not merged.get('petTeam') and home.get('petTeam'):
        merged['petTeam'] = home['petTeam']
    return merged


def ensure(flow, handler, label=None, info=None, index=0, slot=None):
    """先检测报名，未报名且处于报名时段才发送报名；返回 True=可挑战。

    不改任何本地文件；已报名时不会重复发请求。报名回包不再直接当作成功，
    会重新读取状态确认；时段外未报名则明确停止，不进入对战。
    """
    if handler not in ROUTES:
        raise ValueError('未知报名类型')
    label = label or LABELS[handler]
    if info is None:
        info = entry_info(flow, slot)
    info = info or {}
    if not enrolled(info, handler):
        info = _merge_home(flow, handler, info)
    if enrolled(info, handler):
        print('[%s] 报名状态：本周已报名，跳过报名' % label)
        return True
    if handler == 'petArena' and not (info.get('petTeam') or []):
        print('[%s] 斗宠阵容未设置（请先在游戏内设置斗宠阵容），跳过报名' % label)
        return False
    if not registration_open():
        print('[%s] 报名状态：本周未报名，当前不在报名时段（周五16:00~周日22:00）；'
              '已停止，请报名时段内先报名' % label)
        return False
    r = flow.request(ROUTES[handler], {'index': int(index)})
    if not isinstance(r, dict):
        print('[%s] 报名未成功：%s' % (label, r))
        return False
    err = r.get('error')
    if err:
        text = str(err)
        if '已报名' in text or '重复' in text:
            print('[%s] 服务器提示已报名：%s' % (label, text))
            return True
        print('[%s] 报名未成功：%s（可能不在报名时段）' % (label, text))
        return False
    weekly = r.get('everyWeekSetting') or (r.get('info') or {}).get('everyWeekSetting')
    if weekly and applied_time({'everyWeekSetting': weekly}, handler) > 0:
        print('[%s] 报名成功' % label)
        return True
    fresh = entry_info(flow, slot)
    if not enrolled(fresh, handler):
        fresh = _merge_home(flow, handler, fresh)
    if enrolled(fresh, handler):
        print('[%s] 报名成功' % label)
        return True
    print('[%s] 报名回包未确认成功（可能不在报名时段）；已停止，未进入对战' % label)
    return False


def register(flow, handler, index=0):
    """兼容旧调用：返回 (是否成功, 提示)。"""
    info = entry_info(flow)
    ok = ensure(flow, handler, info=info, index=index)
    return ok, ('报名完成' if ok else '报名未完成')


def _main(argv):
    import argparse
    import json
    import io
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument('--handler', required=True, choices=sorted(ROUTES))
    ap.add_argument('--expected-uid', required=True)
    ap.add_argument('--expected-slot', required=True, type=int)
    ap.add_argument('--index', type=int, default=0)
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parent
    account = json.loads((root / 'account.local.json').read_text(encoding='utf-8-sig'))
    if str(account.get('uid')) != args.expected_uid:
        print('账号已变更，未报名')
        return 1
    from teacher_trial import connect
    flow = None
    try:
        flow, info = connect(account, args.expected_slot)
        if args.handler == 'petArena' and not (info.get('petTeam') or []):
            print('[%s] 斗宠阵容未设置（请先在游戏内设置斗宠阵容），未报名'
                  % LABELS[args.handler])
            return 1
        return 0 if ensure(flow, args.handler, info=info, index=args.index) else 1
    finally:
        if flow:
            flow.disconnect()


if __name__ == '__main__':
    import sys
    sys.exit(_main(sys.argv[1:]))
