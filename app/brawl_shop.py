"""乱斗商店（当前赛季）：查询余额与限购，或按指定数量购买。

配置来自最新 cg1 的 Shop.json（type=42、页签 1/2/3、未下架商品）。
页签 1=乱斗商店（乱斗币）、2=符箓商店、3=天赋商店（灵魂/兽印）。
购买只发送一次请求，不自动重试；默认仅查询，显式 --apply 才下单。
"""
import argparse
import json
from datetime import datetime

from game_version import BEIJING, latest_config_folder
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHOP_TYPE = 42
TAB_NAMES = {1: '乱斗商店', 2: '符箓商店', 3: '天赋商店'}
CURRENCIES = {'petBtlMoney': ('petBtlMoney', '乱斗币'),
              'spirit': ('spirit', '灵魂'),
              '101724001': ('101724001', '兽印')}


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


def _currency(row):
    sub = str(row.get('consume_subType') or '')
    return CURRENCIES.get(sub)


def active_items(tab=1):
    """返回当前在售商品 [(shopId, 名称, 单价, 货币键, 货币名, 日限, 周限, 总限)]。"""
    shops = json.loads((config_folder() / 'Shop.json').read_text(encoding='utf-8-sig'))
    items = []
    for row in shops.values():
        if int(row.get('type') or -1) != SHOP_TYPE or str(row.get('tabLabel')) != str(tab):
            continue
        currency = _currency(row)
        if currency is None or _expired(row):
            continue
        try:
            cap = lambda key: int(row.get(key) if row.get(key) not in (None, '') else -1)
            items.append((int(row['id']), str(row.get('name') or row['id']),
                          int(str(row.get('consume_count') or '0').split(',')[0]),
                          currency[0], currency[1],
                          cap('dayPurchaseMaxNum'), cap('weekPurchaseMaxNum'), cap('purchaseMaxNum')))
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


def _item_count(info, item_id):
    bag = info.get('bag') or {}
    rows = bag.get('item') or {}
    return sum(int(rec.get('count') or 0) for key, rec in rows.items()
               if str(rec.get('id', key)) == str(item_id))


def wallet(info):
    """当前存档余额：乱斗币、灵魂、兽印。"""
    return {'petBtlMoney': int(info.get('petBtlM') or 0),
            'spirit': int(info.get('spirit') or 0),
            '101724001': _item_count(info, '101724001')}


def remaining(day_cap, week_cap, total_cap, total_used, week_used, day_used):
    limits = []
    if day_cap >= 0:
        limits.append(max(0, day_cap - day_used))
    if week_cap >= 0:
        limits.append(max(0, week_cap - week_used))
    if total_cap >= 0:
        limits.append(max(0, total_cap - total_used))
    return min(limits) if limits else None


def fmt_remaining(day_cap, week_cap, total_cap, total_used, week_used, day_used):
    parts = []
    for label, cap, used in (('日限', day_cap, day_used), ('周限', week_cap, week_used),
                             ('总限', total_cap, total_used)):
        if cap >= 0:
            parts.append('%s%d，已购%d，剩%d' % (label, cap, used, max(0, cap - used)))
    return '；'.join(parts) or '不限购'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slot', type=int)
    parser.add_argument('--tab', type=int, choices=sorted(TAB_NAMES), default=1,
                        help='1=乱斗商店 2=符箓商店 3=天赋商店')
    parser.add_argument('--password', default='', help='二级密码；仅在账号已设置时填写')
    parser.add_argument('--status', action='store_true', help='查询余额与限购')
    parser.add_argument('--buy', action='append', default=[], metavar='ID:数量')
    parser.add_argument('--apply', action='store_true', help='真正发送购买请求')
    args = parser.parse_args()

    from teacher_trial import connect, enter, checked

    label = TAB_NAMES[args.tab]
    rows = active_items(args.tab)
    catalog = {row[0]: row[1:] for row in rows}
    jobs = []
    for raw in args.buy:
        try:
            sid, count = (int(x) for x in raw.split(':'))
        except ValueError:
            raise ValueError('购买参数须为 ID:数量，例如 42838:1')
        if sid not in catalog:
            raise ValueError('商品 %d 不在当前在售的%s配置中' % (sid, label))
        if count < 1:
            raise ValueError('数量必须大于 0')
        jobs.append((sid, count))

    account = json.loads((ROOT / 'account.local.json').read_text(encoding='utf-8-sig'))
    slot = args.slot if args.slot is not None else int(account.get('record_index', 0))
    flow = None
    try:
        flow, info = connect(account, slot)
        money = wallet(info)
        print('[%s] 槽%d 角色 %s，%s' % (label, slot, info.get('name'), _wallet_text(money, args.tab)), flush=True)
        for sid, name, cost, cur_key, cur_name, day_cap, week_cap, total_cap in rows:
            total_used, week_used, day_used = used_counts(info, sid)
            print('[%s] %d %s · %d%s · %s' %
                  (label, sid, name, cost, cur_name,
                   fmt_remaining(day_cap, week_cap, total_cap, total_used, week_used, day_used)), flush=True)
        if not jobs:
            return
        for sid, count in jobs:
            name, cost, cur_key, cur_name, day_cap, week_cap, total_cap = catalog[sid]
            total_used, week_used, day_used = used_counts(info, sid)
            left = remaining(day_cap, week_cap, total_cap, total_used, week_used, day_used)
            if left is not None:
                if left <= 0:
                    print('[%s] %d %s 已达限购，跳过' % (label, sid, name), flush=True)
                    continue
                if count > left:
                    print('[%s] %d %s 填写 %d 件，但只剩 %d 件限购，按 %d 件购买'
                          % (label, sid, name, count, left, left), flush=True)
                    count = left
            balance = money.get(cur_key, 0)
            need = cost * count
            if balance < need:
                affordable = balance // cost
                if affordable <= 0:
                    print('[%s] %d %s %s不足（单价%d，余%d），跳过'
                          % (label, sid, name, cur_name, cost, balance), flush=True)
                    continue
                print('[%s] %d %s %s不足：需要%d，余%d，本次购买%d件'
                      % (label, sid, name, cur_name, need, balance, affordable), flush=True)
                count = affordable
            if not args.apply:
                print('[%s] 预览：%d %s × %d，共 %d%s；未下单'
                      % (label, sid, name, count, cost * count, cur_name), flush=True)
                continue
            params = {'shopId': sid, 'count': count}
            if args.password:
                params['password'] = args.password
            reply = flow.request('scene.shopHandler.buy', params)
            print('[%s] %d %s × %d 回复：%s'
                  % (label, sid, name, count, json.dumps(reply, ensure_ascii=False)), flush=True)
            if isinstance(reply, dict) and reply.get('code') == 502:
                print('[%s] 该账号需要正确的二级密码，请在界面填写后重试；本次未扣费' % label
                      if not args.password else
                      '[%s] 二级密码错误，已在首个请求后停止；本次未扣费' % label, flush=True)
                break
            if not isinstance(reply, dict) or reply.get('code') != 200:
                break
            money[cur_key] = balance - cost * count
    finally:
        if flow is not None:
            try:
                latest = enter(flow, slot)
                print('[%s] 结束余额：%s' % (label, _wallet_text(wallet(latest), args.tab)), flush=True)
            except Exception as exc:
                print('[%s] 结束状态读取失败：%s' % (label, exc), flush=True)
            flow.disconnect()


def _wallet_text(money, tab):
    if tab == 1:
        return '乱斗币 %d' % money.get('petBtlMoney', 0)
    return '灵魂 %d，兽印 %d' % (money.get('spirit', 0), money.get('101724001', 0))


if __name__ == '__main__':
    main()
