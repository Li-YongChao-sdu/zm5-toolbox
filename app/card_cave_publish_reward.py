"""已发布藏宝洞收益：迁移旧领取脚本，使用当前选定账号与存档。"""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROUTE = 'scene.cardHandler.getReward'


def execute(flow, slot, account_uid, claim=False, report_dir=None):
    from teacher_trial import checked
    from card_cave_target import state
    folder = Path(report_dir) if report_dir else ROOT / 'card_cave_publish_reports'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
    report = {'slot': slot, 'claim': claim, 'rounds': [], 'status': 'querying'}

    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def snapshot():
        info, wallet = state(flow, slot)
        rid = info.get('_id') or info.get('rid')
        if not isinstance(rid, str) or not re.fullmatch(re.escape(str(account_uid)) + r'_r\d+', rid):
            raise RuntimeError('无法确认当前存档实际RID，未领取')
        if wallet.get('fairyMoney') is None:
            raise RuntimeError('缺少仙魄余额，未领取')
        wallet['rid'] = rid
        wallet['landformPublish'] = info.get('landformPublish')
        return wallet

    try:
        before = snapshot()
        rid = before['rid']
        reply = checked(flow.request('scene.cardHandler.getPublishLandform', {'rid': rid}), '查询本人已发布关卡')
        rows = reply.get('data')
        if not isinstance(rows, list):
            raise RuntimeError('已发布关卡列表格式异常，未领取')
        seen = set()
        report.update(rid=rid, before=before, published=rows)
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError('已发布关卡条目格式异常，未领取')
            entity = row.get('entityId') if isinstance(row, dict) else None
            if row.get('rid') != rid or not isinstance(entity, str) or not re.fullmatch(re.escape(rid) + r'_\d+', entity):
                raise RuntimeError('查询结果含不属于当前存档的关卡，已停止')
            if entity in seen:
                continue
            seen.add(entity)
        print('[藏宝洞收益] 槽%s：已发布%d个关卡；仙魄%s' % (slot, len(seen), before['fairyMoney']), flush=True)
        for entity in sorted(seen):
            print('[藏宝洞收益] 本人关卡：' + entity, flush=True)
        if not claim or not seen:
            report['status'] = 'query_only' if not claim else 'no_published_levels'
            print('[藏宝洞收益] %s，未发送领取请求' % ('仅查询' if not claim else '没有已发布关卡'), flush=True)
            return report
        for entity in sorted(seen):
            before = snapshot()
            if before['rid'] != rid:
                raise RuntimeError('存档身份变化，停止领取')
            item = {'entityId': entity, 'before': before, 'phase': 'claim_pending'}
            report['rounds'].append(item)
            save()
            # 与旧脚本相同：先落盘再单次请求；结果不明绝不自动重发。
            reward = flow.request(ROUTE, {'entityId': entity})
            item.update(reply=reward, phase='claim_returned')
            save()
            checked(reward, '领取已发布关卡收益')
            after = snapshot()
            item['after'] = after
            give = reward.get('give') or []
            amount = sum(int(g.get('count', 0)) for g in give
                         if g.get('type') == 'coin' and g.get('subType') == 'fairyMoney')
            if reward.get('consume') or any(g.get('type') != 'coin' or g.get('subType') != 'fairyMoney' for g in give):
                raise RuntimeError('领取回包含非预期消耗或奖励，已停止，请核查记录')
            if amount < 0 or after['fairyMoney'] - before['fairyMoney'] != amount:
                raise RuntimeError('仙魄到账核对异常，未重发')
            if any(before[k] != after[k] for k in ('ticket', 'yuanbao', 'used', 'rid')):
                raise RuntimeError('点券、元宝、挑战次数或存档身份发生异常变化，已停止')
            item.update(amount=amount, phase='verified')
            save()
            print('[藏宝洞收益] %s：仙魄%s→%s（+%s）；点券、元宝及挑战次数不变' %
                  (entity, before['fairyMoney'], after['fairyMoney'], amount), flush=True)
        report['status'] = 'verified'
        return report
    except Exception as exc:
        report.update(status='stopped', error=str(exc))
        print('[藏宝洞收益] 已停止，未自动重发领取请求', flush=True)
        raise
    finally:
        save()
        print('[藏宝洞收益] 记录：' + str(path), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claim', action='store_true')
    args = parser.parse_args()
    from teacher_trial import connect
    account = json.loads((ROOT / 'account.local.json').read_text(encoding='utf-8-sig'))
    slot = int(account.get('record_index', 0))
    flow = None
    try:
        flow, _ = connect(account, slot)
        execute(flow, slot, account['uid'], claim=args.claim)
    finally:
        if flow:
            flow.disconnect()


if __name__ == '__main__':
    main()
