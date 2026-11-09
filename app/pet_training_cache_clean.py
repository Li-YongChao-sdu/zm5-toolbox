# -*- coding: utf-8 -*-
"""刷益灵花旧缓存清理：已完成批次/轮次归档；未确认放生先核对背包，绝不重发请求。"""
import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCHES = ROOT / 'pet_training_batches'
CYCLES = ROOT / 'pet_training_cycles'
ARCHIVE = ROOT / 'pet_training_cache_archive'
ACCOUNTS = ROOT / 'accounts'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, data):
    from pet_training_storage import atomic_json
    atomic_json(path, data)


def pends(data):
    items = []
    if data.get('pending'):
        items.append(('capture', data['pending']))
    harvest = data.get('harvest') or {}
    if harvest.get('pending'):
        items.append(('harvest', harvest['pending']))
    leveling = data.get('leveling') or {}
    if leveling.get('pending'):
        items.append(('leveling', leveling['pending']))
    finalize = data.get('finalize') or {}
    if finalize.get('pending'):
        items.append(('finalize', finalize['pending']))
    return items


def account_for(binding):
    for path in ACCOUNTS.glob('*.json'):
        try:
            account = load(path)
        except (OSError, ValueError):
            continue
        if str(account.get('uid')) == str(binding.get('uid')) and account.get('username') == binding.get('username'):
            return account
    return None


class Sessions:
    def __init__(self):
        self.flows = {}
        self.pets_cache = {}

    def pets(self, binding):
        key = (str(binding.get('uid')), binding.get('username'), int(binding.get('slot')))
        if key in self.pets_cache:
            return self.pets_cache[key]
        account = account_for(binding)
        if not account:
            raise RuntimeError('找不到账号文件，无法核对背包')
        from teacher_trial import connect
        flow, info = connect(account, int(binding['slot']))
        self.flows[key] = flow
        pets = dict((info.get('bag') or {}).get('pet') or {})
        for name in ('p1', 'p2'):
            pet = (((info.get(name) or {}).get('equipments') or {}).get('pet') or {})
            if pet.get('entityId'):
                pets[pet['entityId']] = pet
        self.pets_cache[key] = pets
        return pets

    def close(self):
        for flow in list(self.flows.values()):
            try:
                flow.disconnect()
            except Exception:
                pass


def recorded_ids(finalize):
    ids = set()
    for item in finalize.get('released') or []:
        if item.get('entityId'):
            ids.add(item['entityId'])
    for item in finalize.get('retained') or []:
        if item.get('entityId'):
            ids.add(item['entityId'])
    return ids


def batch_state(path, data):
    finalize = data.get('finalize') or {}
    pending = pends(data)
    if pending:
        return '待修复', '有未确认请求：' + '、'.join(name for name, _ in pending)
    if data.get('status') == 'stale':
        return '可归档', data.get('stale_reason') or '已标记过期'
    if data.get('status') != 'complete':
        if not (data.get('kept') or []):
            return '可归档', '第一步未完成且无保留宠物'
        return '保留', '第一步抓宠未完成'
    if finalize.get('status') != 'complete':
        return '保留', '收尾未完成'
    missing = [p.get('entityId') for p in data.get('kept') or [] if p.get('entityId') not in recorded_ids(finalize)]
    if missing:
        return '保留', '有宠物未记录去向：' + '、'.join(missing[:3])
    return '可归档', ''


def resolve_finalize(path, data, sessions):
    finalize = data['finalize']
    pending = finalize['pending']
    before = pending.get('before') or {}
    eid = before.get('entityId') or (pending.get('params') or {}).get('entityId')
    if not eid:
        return '待确认记录缺少 entityId，保留', False
    pets = sessions.pets(data.get('account') or {})
    if eid in pets:
        return '宠物仍在背包，保留 pending，不重发放生', False
    released = finalize.setdefault('released', [])
    if not any(item.get('entityId') == eid for item in released):
        released.append(before)
    finalize['pending'] = None
    kept = data.get('kept') or []
    missing = [p for p in kept if p.get('entityId') not in pets and p.get('entityId') not in recorded_ids(finalize)]
    if all(p.get('entityId') not in pets for p in kept):
        for item in missing:
            released.append(item)
        finalize['status'] = 'complete'
        save(path, data)
        return '已补记录 %s，且全部批次宠物已不在背包，标记收尾完成' % eid, True
    save(path, data)
    return '已补记录 %s；仍有批次宠物在背包，保留收尾待后续处理' % eid, False


def resolve_pending_free(path, data, sessions):
    """抓宠阶段的待解放生：只核对背包；已消失才补记录，仍存在则保留。"""
    pending = data.get('pending') or {}
    if pending.get('route') != 'scene.petHandler.free':
        return '', False
    eid = (pending.get('params') or {}).get('entityId')
    if not eid:
        return '待确认放生缺少 entityId，保留', False
    pets = sessions.pets(data.get('account') or {})
    if eid in pets:
        return '放生结果仍未确认（宠物仍在背包），保留', False
    released = data.setdefault('released', [])
    if not any(item.get('entityId') == eid for item in released):
        released.append({'entityId': eid, 'resolution': 'pending_free_confirmed_missing'})
    data['pending'] = None
    save(path, data)
    return '放生请求 %s 已确认不在背包，补记录并清除待确认' % eid, True


def resolve_leveling_pending(path, data, sessions):
    """升级阶段的未确认战斗：只核对背包/出战栏和实际等级，不重发战斗。"""
    leveling = data.get('leveling') or {}
    pending = leveling.get('pending')
    if not pending:
        return '', False
    eids = [eid for eid in (pending.get('pets') or {}).values() if eid]
    if not eids:
        leveling['pending'] = None
        save(path, data)
        return '升级待确认记录没有宠物ID，已清除', True
    pets = sessions.pets(data.get('account') or {})
    actual = [{
        'entityId': eid,
        'name': (pets[eid] or {}).get('name'),
        'level': (pets[eid] or {}).get('level'),
        'petEXP': (pets[eid] or {}).get('petEXP'),
        'passivity': ((pets[eid] or {}).get('skill') or {}).get('passivity'),
    } for eid in eids if eid in pets]
    missing = [eid for eid in eids if eid not in pets]
    kept = {p.get('entityId') for p in (data.get('kept') or [])}
    if missing and set(eids) <= set(missing) and not (set(eids) & kept):
        leveling['pending'] = None
        leveling.setdefault('recoveries', []).append({
            'uncertain': pending,
            'actual': [],
            'note': '待确认战斗的宠物均不在背包/出战栏且不在保留清单，按已离开处理；未重发',
        })
        early = leveling.get('early') or {}
        if leveling.get('status') in ('running', 'failed'):
            if all(p.get('entityId') in early for p in (data.get('kept') or [])):
                leveling['status'] = 'complete'
            else:
                leveling['status'] = 'running'
        save(path, data)
        return '升级待确认的 %d 只宠物均已不在背包且不在保留清单，清除待确认' % len(missing), True
    leveling['pending'] = None
    leveling.setdefault('recoveries', []).append({
        'uncertain': pending,
        'actual': actual,
        'missing': missing,
        'note': '按服务器实际等级/经验核对，未重发战斗；超时局不计为确认完整结算局',
    })
    if leveling.get('status') == 'failed':
        leveling['status'] = 'running'
    save(path, data)
    return '升级待确认已核对：在场%d只、缺失%d只；未重发战斗' % (len(actual), len(missing)), True


def reconcile(path, data, sessions, release_missing):
    """不重发任何请求；只按实际背包/出战栏修正清单。release_missing 仅移除清单记录。"""
    leveling = data.get('leveling') or {}
    if leveling.get('pending'):
        note, changed = resolve_leveling_pending(path, data, sessions)
        if note:
            if not changed:
                return note, False
            leveling = data.get('leveling') or {}
    if pends(data):
        return '', False
    kept = data.get('kept') or []
    if not kept:
        if data.get('status') == 'failed':
            data['status'] = 'stale'
            data['stale_reason'] = '第一步抓宠失败且无保留宠物'
            save(path, data)
            return '第一步失败且无保留宠物，标记为过期', True
        if data.get('status') == 'complete' and (data.get('finalize') or {}).get('status') != 'complete':
            data.setdefault('finalize', {})['status'] = 'complete'
            save(path, data)
            return '没有保留宠物，收尾标记完成', True
        return '', False
    pets = sessions.pets(data.get('account') or {})
    missing = [p for p in kept if p.get('entityId') not in pets]
    if not missing:
        return '', False
    if not release_missing:
        return '清单宠物缺失：%s（可加 --release-missing 按已放生处理）' % '、'.join(
            p.get('entityId', '?') for p in missing[:5]), False
    finalize = data.setdefault('finalize', {})
    released = finalize.setdefault('released', [])
    for item in missing:
        eid = item.get('entityId')
        if eid and not any(x.get('entityId') == eid for x in released):
            released.append(dict(item, resolution='manifest_missing_confirmed'))
    data['kept'] = [p for p in kept if p.get('entityId') in pets]
    if not data['kept']:
        finalize['status'] = 'complete'
        data['status'] = 'complete'
        leveling = data.get('leveling') or {}
        if leveling:
            leveling['status'] = 'complete'
    save(path, data)
    return '已按确认把缺失宠物记为放生：%s；剩余%d只' % (
        '、'.join(p.get('entityId', '?') for p in missing[:5]), len(data['kept'])), True


def cycle_state(path, data):
    if data.get('status') == 'stale':
        return '可归档', data.get('stale_reason') or '已标记过期'
    if data.get('status') not in ('complete', 'stopped', 'failed'):
        return '保留', '轮次仍在运行或状态未知'
    active = data.get('active_manifest')
    if active and Path(active).exists():
        try:
            batch = load(active)
        except (OSError, ValueError):
            return '保留', '活动批次清单不可读'
        if pends(batch):
            return '保留', '活动批次有未确认请求'
        if (batch.get('finalize') or {}).get('status') != 'complete':
            return '保留', '活动批次未收尾'
    return '可归档', ''


def move_to_archive(path, run_dir, kind):
    target = run_dir / kind / path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(target.name + '_' + datetime.now().strftime('%H%M%S%f'))
    shutil.move(str(path), str(target))
    return target


def main():
    parser = argparse.ArgumentParser(description='刷益灵花旧缓存清理')
    parser.add_argument('--apply', action='store_true', help='执行归档和已核实 pending 的补记录')
    parser.add_argument('--release-missing', action='store_true',
                        help='把背包和出战栏都找不到的清单宠物按已放生处理；只改清单，不发送放生请求')
    args = parser.parse_args()
    run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = ARCHIVE / run_id
    sessions = Sessions()
    archive_batches = []
    keep_batches = []
    archive_cycles = []
    keep_cycles = []
    fixed = []
    unresolved = []
    try:
        for folder in sorted(BATCHES.glob('*')):
            manifest = folder / 'manifest.json'
            if not manifest.exists():
                continue
            try:
                data = load(manifest)
            except (OSError, ValueError) as exc:
                keep_batches.append((folder.name, '清单不可读：%s' % exc))
                continue
            if args.apply and data.get('pending'):
                try:
                    note, ok = resolve_pending_free(manifest, data, sessions)
                    if note:
                        fixed.append((folder.name, note))
                        if not ok:
                            unresolved.append((folder.name, note))
                except Exception as exc:
                    unresolved.append((folder.name, '核对失败：%s' % exc))
                    continue
            if args.apply and (data.get('finalize') or {}).get('pending'):
                try:
                    note, ok = resolve_finalize(manifest, data, sessions)
                    fixed.append((folder.name, note))
                    if not ok:
                        unresolved.append((folder.name, note))
                except Exception as exc:
                    unresolved.append((folder.name, '核对失败：%s' % exc))
                    continue
            if args.apply:
                try:
                    note, changed = reconcile(manifest, data, sessions, args.release_missing)
                    if note:
                        (fixed if changed else unresolved).append((folder.name, note))
                except Exception as exc:
                    unresolved.append((folder.name, '核对失败：%s' % exc))
                    continue
            state, reason = batch_state(manifest, data)
            if state == '可归档':
                archive_batches.append(folder)
            else:
                keep_batches.append((folder.name, reason))
        for folder in sorted(CYCLES.glob('*')):
            cycle = folder / 'cycle.json'
            if not cycle.exists():
                continue
            try:
                data = load(cycle)
            except (OSError, ValueError) as exc:
                keep_cycles.append((folder.name, '记录不可读：%s' % exc))
                continue
            if args.apply and data.get('status') == 'running' and time.time() - cycle.stat().st_mtime >= 600:
                data['status'] = 'stale'
                data['stale_reason'] = '轮次进程已不在运行（记录超过10分钟未更新）'
                save(cycle, data)
                fixed.append((folder.name, '运行中的轮次记录已超10分钟未更新，标记为过期'))
            state, reason = cycle_state(cycle, data)
            if state == '可归档':
                archive_cycles.append(folder)
            else:
                keep_cycles.append((folder.name, reason))
        if args.apply:
            for folder in archive_batches:
                move_to_archive(folder, run_dir, 'batches')
            for folder in archive_cycles:
                move_to_archive(folder, run_dir, 'cycles')
    finally:
        sessions.close()

    print('模式：%s' % ('执行' if args.apply else '预览'))
    print('批次：可归档 %d，保留 %d' % (len(archive_batches), len(keep_batches)))
    print('轮次：可归档 %d，保留 %d' % (len(archive_cycles), len(keep_cycles)))
    for name, note in fixed:
        print('[补记录] %s：%s' % (name, note))
    for name, reason in keep_batches:
        print('[保留批次] %s：%s' % (name, reason))
    for name, reason in keep_cycles:
        print('[保留轮次] %s：%s' % (name, reason))
    if args.apply:
        print('归档目录：%s' % run_dir)
        print('已归档批次 %d 个、轮次 %d 个；未删除任何文件。' % (len(archive_batches), len(archive_cycles)))
    else:
        print('预览未改动任何文件；确认无误后加 --apply 执行。')
    if unresolved:
        print('仍有 %d 个未确认批次需人工核对：' % len(unresolved))
        for name, note in unresolved:
            print('  %s：%s' % (name, note))
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
