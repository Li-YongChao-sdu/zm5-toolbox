"""读取最新配置中的公开暗语，逐条领取当期免费礼包。"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from game_version import latest_config_folder, beijing_now

ROOT = Path(__file__).resolve().parent
ROUTE = 'scene.activityHandler.getArgotReward'


def load_argots(now=None):
    now = beijing_now(now)
    folder = latest_config_folder(now=now)
    if folder is None:
        raise RuntimeError('未找到完整的本地配置，请先更新配置')
    rows = json.loads((folder / 'Argot.json').read_text(encoding='utf-8-sig'))
    props = json.loads((folder / 'Prop.json').read_text(encoding='utf-8-sig'))
    active, skipped, seen = [], [], set()
    for row in rows.values():
        text = str(row.get('argot') or '').strip()
        try:
            start = datetime.strptime(row['openTime'], '%Y/%m/%d-%H:%M:%S').replace(tzinfo=now.tzinfo)
            end = datetime.strptime(row['underTime'], '%Y/%m/%d-%H:%M:%S').replace(tzinfo=now.tzinfo)
        except (KeyError, ValueError, TypeError):
            skipped.append((row.get('id'), '日期格式异常，跳过'))
            continue
        if not text or text in seen:
            continue
        if not start <= now <= end:
            skipped.append((row.get('id'), '已过期' if now > end else '尚未开放'))
            continue
        seen.add(text)
        ids = str(row.get('subType', '')).split(',')
        counts = str(row.get('count', '')).split(',')
        reward = '；'.join('%s×%s' % (props.get(pid, {}).get('name', pid), count)
                          for pid, count in zip(ids, counts))
        active.append(dict(row, argot=text, reward_text=reward))
    return folder, active, skipped


def claim_argots(flow, rows, pause=time.sleep, now=None):
    """每条最多请求一次；结果不明或非重复领取错误时中止，不自动重发。"""
    result = {'claimed': 0, 'already_claimed': 0, 'skipped': 0}
    for index, row in enumerate(rows):
        if index:
            pause(1)
        # 每次请求前重新检查截止时间，防止批量执行中跨越有效期。
        current = beijing_now(now)
        start = datetime.strptime(row['openTime'], '%Y/%m/%d-%H:%M:%S').replace(tzinfo=current.tzinfo)
        end = datetime.strptime(row['underTime'], '%Y/%m/%d-%H:%M:%S').replace(tzinfo=current.tzinfo)
        if not start <= current <= end:
            result['skipped'] += 1
            continue
        reply = flow.request(ROUTE, {'text': row['argot']})
        if not isinstance(reply, dict):
            raise RuntimeError('暗语领取结果不明，已停止，未重发')
        error = str(reply.get('error') or '')
        if reply.get('code') == 200 and not error:
            result['claimed'] += 1
            print('[暗语礼包] %s：领取成功；%s' % (row['argot'], row['reward_text']), flush=True)
        elif any(word in error for word in ('已经领取', '已领取', '已兑换', '已经兑换', '重复领取')):
            result['already_claimed'] += 1
            print('[暗语礼包] %s：已领取，跳过' % row['argot'], flush=True)
        else:
            raise RuntimeError('暗语%s领取未成功：%s；已停止，未重发' % (row['argot'], error or reply.get('code')))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claim', action='store_true')
    args = parser.parse_args()
    folder, rows, skipped = load_argots()
    print('[暗语礼包] 配置%s：当期%d条，过期/未开放/日期异常%d条' % (folder.name, len(rows), len(skipped)), flush=True)
    for row in rows:
        print('[暗语礼包] %s：%s；截止%s' % (row['argot'], row['reward_text'], row['underTime']), flush=True)
    if not rows:
        print('[暗语礼包] 当前无有效暗语，未连接服务器、未发送领取请求', flush=True)
        return
    if not args.claim:
        return
    from teacher_trial import connect
    account = json.loads((ROOT / 'account.local.json').read_text(encoding='utf-8-sig'))
    flow = None
    try:
        flow, _ = connect(account, int(account.get('record_index', 0)))
        result = claim_argots(flow, rows)
        print('[暗语礼包] 完成：领取%d条，已领跳过%d条，过期跳过%d条' %
              (result['claimed'], result['already_claimed'], result['skipped']), flush=True)
    finally:
        if flow:
            flow.disconnect()


if __name__ == '__main__':
    main()
