"""魔法水晶球：主线手动掉落领取；不扫荡、不购买、不使用道具。"""
import json
import random
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

BALL = '101098027'


def pickup_goal(today):
    today = int(today)
    if today < 0:
        raise ValueError('今日计数异常')
    if today >= 10:
        return 0
    if today == 9:
        return 2
    if today == 8:
        return 1
    return min(2, 8 - today)


def choose_stage(info, main_ids):
    """最新可进入主线=最高已通关的下一关；全通时以最后一关为准。"""
    ids = sorted(set(map(int, main_ids)))
    records = info.get('dungeon') or {}
    passed = [mid for mid in ids if int((records.get(str(mid)) or {}).get('passNum') or 0) > 0]
    if not passed:
        raise RuntimeError('没有已通关主线，不能选择上一关')
    top = ids.index(max(passed))
    latest = min(top + 1, len(ids) - 1)
    if latest == 0:
        raise RuntimeError('最新主线没有上一关')
    mid = ids[latest - 1]
    if mid not in passed:
        raise RuntimeError('目标上一关尚未确认通关')
    return ids[latest], mid


def run(flow, slot, *, main_ids=None, report_dir=None, wait_seconds=10,
        round_seconds=2, max_rounds=20, log=print):
    from activity_availability import require_open
    require_open('RUN_MAGIC_CRYSTAL')
    from teacher_trial import enter, checked
    from bag_warehouse import quantity

    if wait_seconds < 0 or round_seconds < 0 or not 1 <= max_rounds <= 50:
        raise ValueError('等待时间或最大轮数无效')
    root = Path(__file__).resolve().parent
    if main_ids is None:
        main_ids = [r['mid'] for r in json.loads((root / 'main_custom_stages.json').read_text(encoding='utf-8-sig'))]
    folder = Path(report_dir) if report_dir else root / 'crystal_reports'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
    report = {'slot': slot, 'steps': [], 'checkpoints': []}

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def request(route, params):
        row = {'route': route, 'params': params, 'phase': 'pending'}
        report['steps'].append(row)
        save()
        try:
            reply = flow.request(route, params)
        except Exception:
            row['phase'] = 'uncertain'
            save()
            raise RuntimeError('请求结果不明，停止且不重发；请刷新状态后再运行') from None
        row.update(phase='returned', reply=reply)
        save()
        return checked(reply, route)

    def snapshot():
        info = enter(flow, slot)
        user = checked(flow.request('connector.roleHandler.getUserInfo', {}), '读取余额')['user']
        wallet = {k: user.get(k) for k in ('ticket', 'yuanbao')}
        if any(v is None for v in wallet.values()):
            raise RuntimeError('无法确认余额')
        setting = info.get('everyDaySetting') or {}
        snap = {'today': int(setting.get('dungeonActivityCnt') or 0),
                'bag': quantity(info, 'bag', BALL), 'wallet': wallet,
                'day': datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
                'server_reset': setting.get('resetTime')}
        return info, snap

    try:
        info, initial = snapshot()
        report['before'] = initial
        latest, mid = choose_stage(info, main_ids)
        report.update(latest_main=latest, target_main=mid)
        save()
        log('[水晶球] 最新主线%s，选择上一关%s；今日已获取%s' % (latest, mid, initial['today']))
        current = initial
        for _ in range(max_rounds):
            if pickup_goal(current['today']) == 0:
                report['status'] = 'complete' if current['today'] == 11 else 'daily_limit'
                break
            # 每次开局前刷新，不以背包库存代替当天活动计数。
            info, before = snapshot()
            if before['wallet'] != initial['wallet']:
                raise RuntimeError('点券或元宝发生变化，停止')
            if before['day'] != initial['day'] or before['server_reset'] != initial['server_reset']:
                raise RuntimeError('已跨日或服务器日计数重置，停止后重新运行')
            wanted = pickup_goal(before['today'])
            if not wanted:
                current = before
                report['status'] = 'daily_limit'
                break
            rnd = random.randint(0, 9999)
            created = request('scene.copyHandler.createSinglePlayerCopy', {'mid': mid, 'rnd': rnd})
            if created.get('rnd') is None:
                raise RuntimeError('开局缺少服务端随机数，停止')
            candidates = [(i, d) for i, d in enumerate(created.get('drops') or [])
                          if d.get('type') == 'item' and str(d.get('subType')) == BALL
                          and int(d.get('count') or 0) == 1 and d.get('da') == 1]
            chosen = candidates[:wanted]
            if chosen:
                time.sleep(wait_seconds)
            actual = 0
            for ordinal, drop in chosen:
                salt = random.randint(1, 10000)
                reply = request('scene.copyHandler.syncDropInfo', {
                    'index': (int(drop.get('dropIndex', ordinal)) + salt) ^ (int(created['rnd']) ^ rnd),
                    'key': salt ^ rnd})
                amount = sum(int(x.get('count') or 0) for x in reply.get('give') or []
                             if x.get('type') == 'item' and str(x.get('subType')) == BALL)
                if amount != 1:
                    raise RuntimeError('拾取回包不是1个球，停止且不重发')
                actual += amount
            request('scene.copyHandler.finishSingleCopy', {'win': 0, 'star': 0, 'rnd': int(created['rnd']) ^ rnd})
            info, current = snapshot()
            report['checkpoints'].append({'before': before, 'after': current, 'picked': actual})
            save()
            if current['wallet'] != initial['wallet']:
                raise RuntimeError('点券或元宝发生变化，停止')
            if current['day'] != initial['day'] or current['server_reset'] != initial['server_reset']:
                raise RuntimeError('跨日，停止并保留本次记录')
            if current['today'] - before['today'] != actual or current['bag'] - before['bag'] != actual:
                raise RuntimeError('今日计数或实际入包增量不一致，停止')
            log('[水晶球] 本局领取%s，今日%s→%s，背包%s→%s' %
                (actual, before['today'], current['today'], before['bag'], current['bag']))
            if current['today'] == 11:
                report['status'] = 'complete'
                break
            if round_seconds:
                time.sleep(round_seconds)
        else:
            report['status'] = 'round_limit'
        report['after'] = current
        save()
        return report
    except Exception as exc:
        report.update(status='stopped', error=str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__)
        save()
        raise RuntimeError('水晶球流程停止：%s；记录：%s' % (report['error'], path)) from None
