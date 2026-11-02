"""灵宠试炼工具：状态、当前六关、前进、后退和仅免费重置。"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def stage_ids(layer):
    return list(range((int(layer) - 1) * 6 + 1, int(layer) * 6 + 1))


def view(info, user):
    setting = info.get('petDungeonSetting') or {}
    layer = int(setting.get('layerId') or 1)
    history = setting.get('dungeonHistory') or {}
    return {'layer': layer, 'trialStone': int(setting.get('trialStone') or 0),
            'cooldown_end_ms': int(setting.get('resetTime') or 0),
            'cooldown_seconds': max(0, (int(setting.get('resetTime') or 0) - int(time.time() * 1000) + 999) // 1000),
            'reset_used': int((info.get('everyDaySetting') or {}).get('petDungeonResetCnt') or 0),
            'day_reset': (info.get('everyDaySetting') or {}).get('resetTime'),
            'team': info.get('petDungeonTeam') or [],
            'stages': [{'id': sid, 'passed': int((history.get(str(sid)) or {}).get('dailyCnt') or 0) > 0}
                       for sid in stage_ids(layer)],
            'wallet': {k: user.get(k) for k in ('ticket', 'yuanbao')}}


def run(flow, slot, action='status', wait_seconds=2, *, report_dir=None, log=print):
    from teacher_trial import enter, checked
    if action not in ('status', 'clear', 'next', 'previous', 'reset'):
        raise ValueError('未知操作')
    if not 0 <= wait_seconds <= 3600:
        raise ValueError('等待时间须为0～3600秒')
    layers = json.loads((ROOT / 'cg_config_out_cg1_20261019_1/PetChallengeLayer.json').read_text(encoding='utf-8-sig'))
    folder = Path(report_dir) if report_dir else ROOT / 'pet_trial_reports'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
    report = {'slot': slot, 'action': action, 'steps': []}
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    def snapshot():
        info = enter(flow, slot)
        user = checked(flow.request('connector.roleHandler.getUserInfo', {}), '余额')['user']
        state = view(info, user)
        if any(v is None for v in state['wallet'].values()):
            raise RuntimeError('无法确认余额')
        return state
    def request(route, params):
        row = {'route': route, 'params': params, 'phase': 'pending'}
        report['steps'].append(row)
        save()
        try:
            reply = flow.request(route, params)
        except Exception:
            row['phase'] = 'uncertain'
            save()
            raise RuntimeError('请求结果不明，停止且不重发；请重新查询状态') from None
        row.update(reply=reply, phase='returned')
        save()
        checked(reply, route)
        if reply.get('consume'):
            raise RuntimeError('出现非预期消耗，停止并核查记录')
        return reply
    def verify(state):
        if state['wallet'] != report['before']['wallet']:
            raise RuntimeError('点券或元宝变化，停止')
        if state['day_reset'] != report['before']['day_reset']:
            raise RuntimeError('跨日，停止后重新查询')
    try:
        before = snapshot()
        report['before'] = before
        save()
        log('[灵宠试炼] 第%s周天，试炼石%s；六关%s；今日已重置%s次；切层冷却%s秒' %
            (before['layer'], before['trialStone'], ' '.join('%s:%s' % (s['id'], '已通' if s['passed'] else '未通') for s in before['stages']), before['reset_used'], before['cooldown_seconds']))
        log('[灵宠试炼] 现有阵容：%s' % ', '.join(map(str, before['team'])))
        if action == 'clear':
            if not any(x and x != '-1' for x in before['team']):
                raise RuntimeError('没有现有出战阵容，请先在游戏中配置')
            for stage in before['stages']:
                current = snapshot()
                verify(current)
                if current['layer'] != before['layer']:
                    raise RuntimeError('周天变化，停止')
                if next(s['passed'] for s in current['stages'] if s['id'] == stage['id']):
                    continue
                request('scene.petHandler.beginChallengeDungeon', {'petDungeonId': stage['id']})
                time.sleep(wait_seconds)
                request('scene.petHandler.endChallengeDugeon', {'win': 1})
                current = snapshot()
                verify(current)
                if current['layer'] != before['layer'] or not next(s['passed'] for s in current['stages'] if s['id'] == stage['id']):
                    raise RuntimeError('服务器未确认本关通关，停止')
                log('[灵宠试炼] %s关已通过，试炼石%s' % (stage['id'], current['trialStone']))
        elif action in ('next', 'previous'):
            if before['cooldown_seconds']:
                raise RuntimeError('切层冷却尚余%s秒' % before['cooldown_seconds'])
            if action == 'next' and not all(s['passed'] for s in before['stages']):
                raise RuntimeError('当前六关尚未全部通关，请先通关当前六关')
            if action == 'previous' and before['layer'] <= 1:
                raise RuntimeError('第一周天不能后退')
            request('scene.petHandler.toNextLayer' if action == 'next' else 'scene.petHandler.resetPreLayer', {})
        elif action == 'reset':
            cfg = layers[str(before['layer'])]
            if before['reset_used'] >= int(cfg['resetNumber']):
                raise RuntimeError('今日免费重置已用尽，不付费重置')
            request('scene.petHandler.resetPetChallengeDungeon', {'petDungeonId': before['stages'][0]['id']})
        after = snapshot()
        verify(after)
        report['after'] = after
        save()
        if action == 'next' and after['layer'] != before['layer'] + 1:
            raise RuntimeError('前进后周天核对未通过')
        if action == 'previous' and after['layer'] != before['layer'] - 1:
            raise RuntimeError('后退后周天核对未通过')
        if action == 'reset' and (after['layer'] != before['layer'] or after['reset_used'] != before['reset_used'] + 1 or any(s['passed'] for s in after['stages'])):
            raise RuntimeError('免费重置核对未通过')
        if action == 'clear' and not all(s['passed'] for s in after['stages']):
            raise RuntimeError('服务器未确认六关全部通过')
        report['status'] = 'complete'
        save()
        log('[灵宠试炼] %s完成；周天%s→%s，试炼石%s→%s；记录：%s' % (action, before['layer'], after['layer'], before['trialStone'], after['trialStone'], path))
        return report
    except Exception as exc:
        report.update(status='stopped', error=str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__)
        save()
        raise RuntimeError('%s；记录：%s' % (report['error'], path)) from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=('status', 'clear', 'next', 'previous', 'reset'), default='status')
    parser.add_argument('--wait', type=float, default=2)
    args = parser.parse_args()
    from teacher_trial import connect
    account = json.loads((ROOT / 'account.local.json').read_text(encoding='utf-8-sig'))
    slot = int(account['record_index'])
    flow = None
    try:
        flow, _ = connect(account, slot)
        run(flow, slot, args.action, args.wait, log=lambda s: print(s, flush=True))
    finally:
        if flow:
            flow.disconnect()

if __name__ == '__main__':
    main()
