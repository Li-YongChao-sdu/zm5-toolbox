"""乱斗商店（当前赛季）：查询乱斗币余额、每周限购，或按指定数量购买。

配置来自最新 cg1 的 Shop.json（type=42、页签1、未下架商品）。
购买只发送一次请求，不自动重试；默认仅查询，显式 --apply 才下单。
"""
import argparse
import json
from datetime import datetime

from game_version import BEIJING, latest_config_folder
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHOP_TYPE = 42
SHOP_TAB = '1'


def config_folder():
    folder = latest_config_folder()
    if folder is not None and (folder / 'Shop.json').is_file():
        return folder
    for path in sorted(ROOT.glob('cg_config_out_cg1_*'), reverse=True):
        if (path / 'Shop.json').is_file():
            return path
    raise RuntimeError('未找到 Shop.json 配置，请先在“配置更新”页下载配置')


def _expired(row):
    raw = row.get('underTime')
    if raw in (None, -1, '-1', ''):
        return False
    try:
        return datetime.strptime(str(raw), '%Y/%m/%d-%H:%M:%S').replace(tzinfo=BEIJING) < datetime.now(BEIJING)
    except (TypeError, ValueError):
        return False


def active_items():
    """返回当前在售的乱斗商店商品 [(shopId, 名称, 单价, 周限, 总限)]。"""
    shops = json.loads((config_folder() / 'Shop.json').read_text(encoding='utf-8-sig'))
    items = []
    for row in shops.values():
        if int(row.get('type') or -1) != SHOP_TYPE or str(row.get('tabLabel')) != SHOP_TAB:
            continue
        if str(row.get('consume_subType')) != 'petBtlMoney' or _expired(row):
            continue
        try:
            cap = lambda key: int(row.get(key) if row.get(key) not in (None, '') else -1)
            items.append((int(row['id']), str(row.get('name') or row['id']),
                          int(str(row.get('consume_count') or '0').split(',')[0]),
                          cap('weekPurchaseMaxNum'), cap('purchaseMaxNum')))
        except (TypeError, ValueError):
            continue
    return sorted(items)


def _count(record):
    if isinstance(record, dict):
        return int(record.get('buyCount') or 0)
    return int(record or 0)


def used_counts(info, sid):
    shop = (info.get('shop') or {}).get(str(sid))
    week = ((info.get('everyWeekSetting') or {}).get('shopBuyCount') or {}).get(str(sid))
    day = ((info.get('everyDaySetting') or {}).get('shopBuyCount') or {}).get(str(sid))
    return _count(shop), _count(week), _count(day)


def remaining(week_cap, total_cap, shop_used, week_used):
    limits = []
    if week_cap >= 0:
        limits.append(max(0, week_cap - week_used))
    if total_cap >= 0:
        limits.append(max(0, total_cap - shop_used))
    return min(limits) if limits else None


def fmt_remaining(week_cap, total_cap, shop_used, week_used):
    parts = []
    if week_cap >= 0:
        parts.append('周限%d，已购%d，剩%d' % (week_cap, week_used, max(0, week_cap - week_used)))
    if total_cap >= 0:
        parts.append('总限%d，已购%d，剩%d' % (total_cap, shop_used, max(0, total_cap - shop_used)))
    return '；'.join(parts) or '不限购'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slot', type=int)
    parser.add_argument('--status', action='store_true', help='查询余额与每周限购')
    parser.add_argument('--buy', action='append', default=[], metavar='ID:数量')
    parser.add_argument('--apply', action='store_true', help='真正发送购买请求')
    args = parser.parse_args()

    from teacher_trial import connect, enter, checked

    catalog = {sid: (name, cost, week, total) for sid, name, cost, week, total in active_items()}
    jobs = []
    for raw in args.buy:
        try:
            sid, count = (int(x) for x in raw.split(':'))
        except ValueError:
            raise ValueError('购买参数须为 ID:数量，例如 42838:1')
        if sid not in catalog:
            raise ValueError('商品 %d 不在当前在售的乱斗商店配置中' % sid)
        if count < 1:
            raise ValueError('数量必须大于 0')
        jobs.append((sid, count))

    account = json.loads((ROOT / 'account.local.json').read_text(encoding='utf-8-sig'))
    slot = args.slot if args.slot is not None else int(account.get('record_index', 0))
    flow = None
    try:
        flow, info = connect(account, slot)
        print('[乱斗商店] 槽%d 角色 %s，乱斗币 %s' % (slot, info.get('name'), info.get('petBtlM')), flush=True)
        for sid, name, cost, week_cap, total_cap in active_items():
            shop_used, week_used, _ = used_counts(info, sid)
            print('[乱斗商店] %d %s · %d乱斗币 · %s' %
                  (sid, name, cost, fmt_remaining(week_cap, total_cap, shop_used, week_used)), flush=True)
        if not jobs:
            return
        money = int(info.get('petBtlM') or 0)
        for sid, count in jobs:
            name, cost, week_cap, total_cap = catalog[sid]
            shop_used, week_used, _ = used_counts(info, sid)
            left = remaining(week_cap, total_cap, shop_used, week_used)
            if left is not None:
                if left <= 0:
                    print('[乱斗商店] %d %s 已达限购，跳过' % (sid, name), flush=True)
                    continue
                if count > left:
                    print('[乱斗商店] %d %s 填写 %d 件，但只剩 %d 件限购，按 %d 件购买'
                          % (sid, name, count, left, left), flush=True)
                    count = left
            need = cost * count
            if money < need:
                affordable = money // cost
                if affordable <= 0:
                    print('[乱斗商店] %d %s 乱斗币不足（单价%d，余%d），跳过'
                          % (sid, name, cost, money), flush=True)
                    continue
                print('[乱斗商店] %d %s 乱斗币不足：需要%d，余%d，本次购买%d件'
                      % (sid, name, need, money, affordable), flush=True)
                count = affordable
            if not args.apply:
                print('[乱斗商店] 预览：%d %s × %d，共 %d 乱斗币；未下单' % (sid, name, count, cost * count), flush=True)
                continue
            reply = flow.request('scene.shopHandler.buy', {'shopId': sid, 'count': count})
            print('[乱斗商店] %d %s × %d 回复：%s' % (sid, name, count, json.dumps(reply, ensure_ascii=False)), flush=True)
            if not isinstance(reply, dict) or reply.get('code') != 200:
                break
            money -= cost * count
    finally:
        if flow is not None:
            try:
                latest = enter(flow, slot)
                print('[乱斗商店] 结束余额：乱斗币 %s' % latest.get('petBtlM'), flush=True)
            except Exception as exc:
                print('[乱斗商店] 结束状态读取失败：%s' % exc, flush=True)
            flow.disconnect()


if __name__ == '__main__':
    main()
