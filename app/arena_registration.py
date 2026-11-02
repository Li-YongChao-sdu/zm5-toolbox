"""竞技场／斗宠报名：路由与参数按客户端确认（scene.*Handler.applyFor，{"index":0}）。

客户端依据 EveryWeekSetting.applyForArenaTime / applyForPetArenaTime 判断是否已报名：
大于 0 视为本周已报名（见 ArenaModule.as 报名图标逻辑）。
"""
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
    """重新读一次存档 info（报名状态只在 entry 的 everyWeekSetting 里可靠）。"""
    if slot is None:
        from daily_auto import RECORD_INDEX
        slot = RECORD_INDEX
    r = flow.request('connector.entryHandler.entry',
                     {'index': int(slot), 'userAgent': flow.user_agent})
    if isinstance(r, dict) and not r.get('error'):
        return r.get('info') or {}
    return {}


def ensure(flow, handler, label=None, info=None, index=0, slot=None):
    """未报名则发送报名；返回 True=已报名可用，False=无法报名。

    不改任何本地文件；已报名时不会重复发请求。
    """
    if handler not in ROUTES:
        raise ValueError('未知报名类型')
    label = label or LABELS[handler]
    if info is None:
        info = entry_info(flow, slot)
    if applied_time(info, handler) > 0:
        print('[%s] 本周已报名，跳过报名' % label)
        return True
    if handler == 'petArena' and not (info.get('petTeam') or []):
        print('[%s] 斗宠阵容未设置（请先在游戏内设置斗宠阵容），跳过报名' % label)
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
    # 客户端 getApplyBack 只要拿到回包就提示“报名成功”，回包即整份 everyWeekSetting。
    print('[%s] 报名成功' % label)
    return True


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
