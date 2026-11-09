"""手动乱斗单场流程：只在窗口按钮触发后匹配，不自动连续开场。"""
import queue
import time
from pet_brawl import R_INFO, R_MATCH, R_CANCEL, R_READY, R_LOADED, DUNGEON, _message, _checked

def read_settlement_state(flow, slot):
    home = _checked(flow.request(R_INFO, {}), '刷新乱斗战绩')
    entry = _checked(flow.request('connector.entryHandler.entry',
        {'index': slot, 'userAgent': flow.user_agent}), '刷新乱斗币')
    info = entry.get('info') or {}
    record = ((home.get('petPvp') or {}).get('1') or {})
    if 'total' not in record or 'petBtlM' not in info:
        raise RuntimeError('服务器未下发完整战绩或乱斗币，不能确认到账')
    return {'total': int(record['total']), 'win': int(record.get('win') or 0),
            'fail': int(record.get('fail') or 0), 'score': int(record.get('score') or 0),
            'coin': int(info['petBtlM']),
            'daily_coin': int((info.get('everyDaySetting') or {}).get('addPetPvpM') or 0)}


def finish_and_refresh(flow, slot, before, data):
    result = {0:'负', 1:'胜', 2:'平'}.get(data.get('winType'), '待确认')
    prefix = f'本场结果：{result}'
    latest = None
    try:
        for attempt in range(3):
            latest = read_settlement_state(flow, slot)
            if latest['total'] > before['total']:
                break
            if attempt < 2:
                time.sleep(2)
        delta = latest['coin'] - before['coin']
        verified = (latest['total'] == before['total'] + 1
                    and type(data.get('addPetBtlM')) is int
                    and delta == data['addPetBtlM'])
        text = (f'{prefix}；乱斗币实到{delta:+d}（余额{latest["coin"]}，'
                f'今日已获{latest["daily_coin"]}）；积分{int(data.get("addScore") or 0):+d}')
        if not verified:
            text += '；到账或场次尚未核对一致，请重新查询后再匹配'
        return {'confirmed': True, 'can_match': verified, 'verified': verified,
                'text': text, 'raw': data, 'stats': latest, 'coin_delta': delta}
    except Exception as exc:
        return {'confirmed': True, 'can_match': False, 'verified': False,
                'text': prefix + '；已收到结算，刷新失败：' + str(exc),
                'raw': data, 'stats': latest}


def play_one(flow, events, control, match_seconds=90, battle_seconds=600, slot=0):
    before = read_settlement_state(flow, slot)
    _checked(flow.request(R_MATCH, {}), '发起手动匹配')
    deadline = time.monotonic() + match_seconds
    room = None
    loading = False
    next_loading = 0
    while not control.stopped.is_set():
        control.process(flow)
        now = time.monotonic()
        if now >= deadline:
            if not room:
                _checked(flow.request(R_CANCEL, {}), '取消超时匹配')
                return {'confirmed': False, 'can_match': True, 'text': '匹配超时，已取消排队'}
            return {'confirmed': False, 'can_match': False, 'text': '本场观察超时，未确认离开房间；请关闭窗口重连后再匹配'}
        if loading and now >= next_loading:
            reply = flow.request(R_LOADED, {'roomId': room})
            if reply.get('code') == 500:
                loading = False
            else:
                _checked(reply, '上报加载状态')
            next_loading = time.monotonic() + 2
        try:
            route, body = events.get(timeout=0.2)
        except queue.Empty:
            continue
        data = _message(body)
        if route == 'kicked':
            raise RuntimeError('连接已被服务器断开，请关闭窗口重连')
        if route == 'onPVPMatchResult':
            _checked(data, '匹配')
            deadline = time.monotonic() + battle_seconds
        elif route == 'onPrepareCreateOnlineCopy' and int(data.get('dungeonId') or 0) == DUNGEON:
            if room:
                continue
            room = data.get('roomId')
            if not room:
                raise RuntimeError('服务器未下发房间编号')
            _checked(flow.request(R_READY, {'roomId': room, 'status': 4}), '准备入房')
            loading = True
            deadline = time.monotonic() + battle_seconds
        elif route == 'onPetPVPFinish':
            if data.get('error'):
                raise RuntimeError(str(data['error']))
            control.notify('服务器已结算，正在刷新战绩和乱斗币')
            return finish_and_refresh(flow, slot, before, data)
        elif route == 'onPetPvpBtlExit':
            return {'confirmed': False, 'can_match': True, 'text': '已退出房间，未收到完整胜负结算'}
    raise InterruptedError('手动乱斗已停止')

def main():
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from teacher_trial import connect
    from pet_brawl_control import run_window
    root = Path(__file__).resolve().parent
    account = json.loads((root/'account.local.json').read_text(encoding='utf-8-sig'))
    flow = None
    try:
        flow, _ = connect(account, int(account.get('record_index', 0)))
        run_window(flow, account['uid'], SimpleNamespace(match_seconds=90, battle_seconds=600, record_index=int(account.get('record_index', 0))))
    finally:
        if flow:
            flow.disconnect()

if __name__ == '__main__':
    main()
