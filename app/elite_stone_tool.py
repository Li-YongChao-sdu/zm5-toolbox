"""独立工具：精英免费翻牌每日4个万能强化石，只保留强化石。"""
import argparse
import json
import os
import random
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STONE = '101005001'


def select_stage(info, grades):
    for mid in sorted(int(k) for k in grades if str(k).isdigit() and 30010 <= int(k) <= 30800 and int(k) % 10 == 0):
        rec = (info.get('dungeon') or {}).get(str(mid)) or {}
        grade = grades[str(mid)]
        points = str(grade.get('treasurePointTicket', '')).split(';')[0]
        items = str(grade.get('treasureItemNum', '')).split(';')[0]
        if int(rec.get('passNum') or 0) > 0 and int(rec.get('dailyCount') or 0) < 2 and points == '0' and items in ('', '0'):
            return mid
    return None


def is_stone(pid, props):
    return str(pid) == STONE or int(props.get(str(pid), {}).get('propType') or 0) == 1005


def run(flow, slot, *, wait_seconds=25, max_rounds=160, report_dir=None, log=print):
    from teacher_trial import enter, checked
    from bag_warehouse import quantity, sell, state
    if not 0 <= wait_seconds <= 3600 or not 1 <= max_rounds <= 160:
        raise ValueError('等待时间或最大轮数无效')
    config = ROOT / 'cg_config_out_cg1_20261019_1'
    props = json.loads((config / 'Prop.json').read_text(encoding='utf-8-sig'))
    grades = json.loads((config / 'DungeonGrade.json').read_text(encoding='utf-8-sig'))
    folder = Path(report_dir) if report_dir else ROOT / 'elite_stone_reports'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
    report = {'slot': slot, 'steps': [], 'rounds': []}
    password = os.environ.pop('ZM5_STONE_SELL_PASSWORD', '')
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
            raise RuntimeError('请求结果不明，停止且不重发，请先刷新状态') from None
        row.update(phase='returned', reply=reply)
        save()
        return checked(reply, route)
    def snapshot():
        info = enter(flow, slot)
        user = checked(flow.request('connector.roleHandler.getUserInfo', {}), '余额')['user']
        wallet = {k: user.get(k) for k in ('ticket', 'yuanbao')}
        if any(v is None for v in wallet.values()):
            raise RuntimeError('无法读取余额')
        return info, user, {'today': int((info.get('everyDaySetting') or {}).get('eliteSweep') or 0),
                            'reset': (info.get('everyDaySetting') or {}).get('resetTime'),
                            'bag': quantity(info, 'bag', STONE), 'wallet': wallet}
    try:
        info, user, before = snapshot()
        report['before'] = before
        save()
        for _ in range(max_rounds):
            info, user, pre = snapshot()
            if pre['today'] >= 4:
                report['status'] = 'daily_limit'
                break
            if pre['wallet'] != before['wallet'] or pre['reset'] != before['reset']:
                raise RuntimeError('余额变化或跨日，停止')
            mid = select_stage(info, grades)
            if mid is None:
                report['status'] = 'no_free_stages'
                break
            # 牌面可能给药品：两类包都预留一格，避免结算后无法翻牌。
            for kind, capacity in state(info, user)['capacity']['bag'].items():
                if capacity['max'] is None or capacity['used'] >= capacity['max']:
                    raise RuntimeError('%s背包已满，请先腾出至少1格' % kind)
            log('[万能强化石] 精英%s；今日%s/4；只保留强化石' % (mid, pre['today']))
            base = {str(k): quantity(info, 'bag', k) for k in props}
            gained = Counter()
            def collect(reply):
                for gift in reply.get('give') or []:
                    if gift.get('type') == 'item':
                        gained[str(gift['subType'])] += int(gift.get('count') or 0)
                    elif gift.get('type') == 'equipment':
                        raise RuntimeError('服务器直接发放装备，停止；未自动出售未核对的装备')
            info_before = info
            rnd = random.randint(0, 9999)
            created = request('scene.copyHandler.createSinglePlayerCopy', {'mid': mid, 'rnd': rnd})
            # 本工具只翻牌：所有场景掉落均不拾取。
            time.sleep(wait_seconds)
            collect(request('scene.copyHandler.finishSingleCopy', {
                'win': 1, 'rnd': int(created['rnd']) ^ rnd, 'star': 3, 'starInfo': 7,
                'sceneBuffScore': 0, 'maxCombo': 0, 'killMonsterCnt': 0,
                'useMagicWeaponCnt': 0, 'useBossCardCnt': 0}))
            cards = request('scene.copyHandler.getCard', {})
            if not cards.get('items'):
                raise RuntimeError('服务器牌面为空，停止')
            turned = request('scene.copyHandler.turnCard', {})
            if turned.get('consume'):
                raise RuntimeError('免费翻牌出现消耗，停止')
            collect(turned)
            info, user, post = snapshot()
            if post['wallet'] != before['wallet'] or post['reset'] != before['reset']:
                raise RuntimeError('余额变化或跨日，停止')
            pre_count = int(((info_before.get('dungeon') or {}).get(str(mid)) or {}).get('dailyCount') or 0)
            post_count = int(((info.get('dungeon') or {}).get(str(mid)) or {}).get('dailyCount') or 0)
            if post_count != pre_count + 1:
                raise RuntimeError('服务器精英关卡次数变化不符，停止且不补计次数')
            if post['bag'] - pre['bag'] != gained[STONE]:
                raise RuntimeError('万能强化石入包不符')
            row = {'mid': mid, 'before': pre, 'after': post, 'cards': cards['items'], 'sales': []}
            report['rounds'].append(row)
            save()
            for pid, n in gained.items():
                if is_stone(pid, props) or n <= 0:
                    continue
                if quantity(info, 'bag', pid) - base.get(pid, 0) < n:
                    raise RuntimeError('待售奖励增量不足，停止避免出售旧库存')
                sale = {'id': pid, 'count': n, 'phase': 'pending'}
                row['sales'].append(sale)
                save()
                result, info, user = sell(flow, info, user, pid, n, password,
                                          refresh=lambda: enter(flow, slot))
                sale.update(phase='returned', result=result)
                save()
                if not result['verified'] or any(user.get(k) != before['wallet'][k] for k in ('ticket', 'yuanbao')):
                    raise RuntimeError('奖励出售核对失败；需要二级密码时请填写后再执行')
            log('[万能强化石] 本场翻牌结束，今日%s→%s；万能强化石背包%s→%s' %
                (pre['today'], post['today'], pre['bag'], post['bag']))
            if post['today'] >= 4:
                report['status'] = 'daily_limit'
                break
        else:
            report['status'] = 'round_limit'
        _, _, report['after'] = snapshot()
        save()
        return report
    except Exception as exc:
        report.update(status='stopped', error=str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__)
        save()
        raise RuntimeError('%s；记录：%s' % (report['error'], path)) from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--wait', type=float, default=25)
    args = parser.parse_args()
    from teacher_trial import connect, checked
    from bag_warehouse import quantity
    account = json.loads((ROOT / 'account.local.json').read_text(encoding='utf-8-sig'))
    slot = int(account['record_index'])
    flow = None
    try:
        flow, info = connect(account, slot)
        if args.status:
            print('[万能强化石] 槽%s，今日已获取%s/4；背包库存%s（库存不代表今日数量）' %
                  (slot, (info.get('everyDaySetting') or {}).get('eliteSweep', 0), quantity(info, 'bag', STONE)), flush=True)
        else:
            result = run(flow, slot, wait_seconds=args.wait, log=lambda s: print(s, flush=True))
            print('[万能强化石] 结束：%s；今日%s/4' % (result['status'], result['after']['today']), flush=True)
    finally:
        if flow:
            flow.disconnect()

if __name__ == '__main__':
    main()
