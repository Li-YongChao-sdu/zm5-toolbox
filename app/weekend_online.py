"""周末在线奖励：用真实连接计时补足未实时刷新的任务进度。"""
import json
import time
from datetime import datetime
from fashion_online import OnlineClock, BEIJING, checked
from game_version import latest_config_folder


def run(flow, info, part='all', *, wait=False, sleep=None, log=print, progress=None):
    sleep = sleep or time.sleep
    ids = {'buff': (960001,), 'rest': tuple(range(960002, 960007)),
           'all': tuple(range(960001, 960007))}.get(part)
    if ids is None:
        raise ValueError('未知周末奖励分组')
    folder = latest_config_folder()
    if folder is None:
        raise RuntimeError('未找到完整在线奖励配置')
    cfg = json.loads((folder / 'OnlineReward.json').read_text(encoding='utf-8-sig'))
    clock = getattr(flow, '_weekend_online_clock', None)
    if clock is None:
        clock = OnlineClock()
        flow._weekend_online_clock = clock
    clock.enter(info)
    day = datetime.now(BEIJING).date()

    def fetch():
        reply = checked(flow.request('scene.questHandler.getQuestList', {}), '周末在线任务查询')
        return {int(q['id']): q for q in reply.get('quest') or []
                if 960001 <= int(q.get('id', 0)) <= 960006}

    def live():
        if datetime.now(BEIJING).date() != day:
            clock.close()
            raise RuntimeError('在线等待跨日，已停止')
        if not getattr(getattr(flow, 'game', None), '_running', False):
            clock.close()
            raise RuntimeError('连接已断开，停止计时及领奖，不自动重登')

    quests = fetch()
    timed = [q for k, q in quests.items() if k < 960006]
    if not timed:
        log('[周末在线] 当前未下发在线任务，未提交领奖')
        return {'status': 'unavailable', 'claimed': []}
    sample = max(timed, key=lambda q: int((q.get('progress') or {}).get('0', 0)))
    clock.sample(sample)
    wallet = checked(flow.request('connector.roleHandler.getUserInfo', {}), '读取余额')['user']
    before = {k: wallet.get(k) for k in ('ticket', 'yuanbao')}
    if any(v is None for v in before.values()):
        raise RuntimeError('无法确认点券元宝，未提交领奖')
    claimed, waiting = [], []
    for tid in ids:
        quests = fetch()
        q = quests.get(tid)
        if q is None or q.get('status') == 3:
            continue
        target = int(cfg[str(tid)]['targetNum'])
        total = clock.total(q)
        if tid < 960006:
            while q.get('status') != 2 and total < target and wait:
                live()
                if progress:
                    progress({'task': tid, 'stored_seconds': int((q.get('progress') or {}).get('0', 0)),
                              'estimated_seconds': total, 'target_seconds': target,
                              'session_seconds': clock.elapsed()})
                sleep(min(30, max(1, target - total)))
                live()
                total = clock.total(q)
            if q.get('status') != 2 and total < target:
                waiting.append(tid)
                continue
            # 本地时长达标时仍要求连接有效；不向服务器写入任何进度。
            if q.get('status') != 2:
                live()
        elif q.get('status') != 2:
            waiting.append(tid)
            continue
        if wait:
            live()
        # 达标后仅提交一次正常领奖；超时、拒绝和核对异常均停止，不重发。
        reply = checked(flow.request('scene.questHandler.commitQuest', {'qId': tid}), '周末在线领奖')
        if reply.get('consume'):
            raise RuntimeError('免费领奖出现非预期消耗，停止且不重发')
        after = fetch()
        if (after.get(tid) or {}).get('status') != 3:
            raise RuntimeError('领奖已返回，但领取状态未确认，未重发')
        user = checked(flow.request('connector.roleHandler.getUserInfo', {}), '核对余额')['user']
        if {k: user.get(k) for k in before} != before:
            raise RuntimeError('点券或元宝发生变化，停止')
        claimed.append({'id': tid, 'give': reply.get('give') or []})
        log('[周末在线] %s领取成功：%s' %
            ('累计礼包' if tid == 960006 else '第%d档' % (tid - 960000),
             json.dumps(reply.get('give') or [], ensure_ascii=False)))
    return {'status': 'complete' if not waiting else 'waiting', 'claimed': claimed,
            'waiting': waiting, 'estimated_seconds': clock.total(sample)}
