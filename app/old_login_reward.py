"""旧五日登录：只查询，或由用户明确点击后领取一次。"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROUTE = 'scene.activityHandler.getRechargeLandingReward'
REWARDS = (10, 15, 15, 15, 20)
ZONE = timezone(timedelta(hours=8))

def status(info, now=None):
    state = info.get('rechargeLandingReward') or {}
    day = int(state.get('day') or 0)
    if not 0 <= day <= 5:
        raise RuntimeError('服务器返回的领取天数异常')
    currency = info.get('baoquan')
    if not isinstance(currency, dict) or 'cnt' not in currency:
        raise RuntimeError('未下发宝券余额，不能核对奖励')
    stamp = state.get('lastGetTime')
    last = datetime.fromtimestamp(float(stamp)/1000, ZONE) if stamp else None
    today = (now or datetime.now(ZONE)).astimezone(ZONE).date()
    return {'day': day, 'baoquan': int(currency['cnt']),
            'last_date': last.date().isoformat() if last else None,
            'can_claim': day < 5 and (last is None or last.date() < today)}

def execute(flow, info, claim=False, refresh=None, now=None):
    before = status(info, now)
    print(f"[五日登录] 已领取 {before['day']}/5 天；宝券 {before['baoquan']}；上次领取 {before['last_date'] or '无'}", flush=True)
    if not claim:
        print('[五日登录] ' + ('可尝试领取下一天奖励' if before['can_claim'] else '今日已领取或五天已领完'), flush=True)
        return {'before': before}
    if not before['can_claim']:
        print('[五日登录] 今日已领取或五天已领完，未发送领奖请求', flush=True)
        return {'before': before, 'skipped': True}
    if refresh is None:
        raise ValueError('领取必须提供状态刷新函数')
    wallet = flow.request('connector.roleHandler.getUserInfo', {})
    if wallet.get('code') != 200 or wallet.get('error') or (wallet.get('user') or {}).get('ticket') is None:
        raise RuntimeError('无法确认点券余额，未发送领奖请求')
    ticket = wallet['user']['ticket']
    # 只发送一次。响应超时或核对异常时不自动重发，避免重复操作。
    reply = flow.request(ROUTE, {})
    if reply.get('code') != 200 or reply.get('error'):
        raise RuntimeError('领取失败：' + str(reply.get('error') or reply.get('code')))
    after = status(refresh(), now)
    latest = flow.request('connector.roleHandler.getUserInfo', {})
    if latest.get('code') != 200 or latest.get('error') or (latest.get('user') or {}).get('ticket') is None:
        raise RuntimeError('领奖已回复成功，但点券核对失败；未重发请求，请查询状态')
    actual = after['baoquan'] - before['baoquan']
    if after['day'] != before['day']+1 or actual != REWARDS[before['day']] or latest['user']['ticket'] != ticket:
        raise RuntimeError(f'领奖核对异常：天数{before["day"]}→{after["day"]}，宝券变化{actual}，点券{ticket}→{latest["user"]["ticket"]}；未自动重领')
    print(f'[五日登录] 第{after["day"]}天领取成功：宝券 {before["baoquan"]}→{after["baoquan"]}（+{actual}）；点券 {ticket}→{ticket}', flush=True)
    return {'before':before, 'after':after, 'reply':reply}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claim', action='store_true')
    args = parser.parse_args()
    from teacher_trial import connect, enter
    root = Path(__file__).resolve().parent
    account = json.loads((root/'account.local.json').read_text(encoding='utf-8-sig'))
    slot = int(account.get('record_index', 0))
    flow = None
    try:
        print(f'[五日登录] 使用工具箱当前账号，存档槽{slot}', flush=True)
        flow, info = connect(account, slot)
        execute(flow, info, claim=args.claim, refresh=lambda: enter(flow, slot))
    finally:
        if flow:
            flow.disconnect()

if __name__ == '__main__':
    main()
