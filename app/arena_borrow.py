"""只读借用未报名存档的推荐列表；出战时只用已确认的快照。"""
from datetime import datetime, timezone

from arena_targets import checked, detail
from arena_target_confirm import identity, description


def enrollment(home, entry, handler):
    weekly = dict(entry.get('everyWeekSetting') or {})
    weekly.update(home.get('everyWeekSetting') or {})
    field = 'applyForArenaTime' if handler == 'arena' else 'applyForPetArenaTime'
    rank = (home.get('self') or {}).get('rank')
    applied = weekly.get(field) or 0
    if rank is None:
        raise ValueError('无法确认报名状态')
    return int(rank), float(applied)


def role_names(entry):
    return '＋'.join(str((entry.get(key) or {}).get('name')) for key in ('p1', 'p2')
                    if (entry.get(key) or {}).get('name'))


def query_list(actor, actor_slot, source, source_slot, handler, connect_fn=None, progress=None):
    if connect_fn is None:
        from teacher_trial import connect as connect_fn
    log = progress if progress is not None else lambda _message: None
    flow = None
    try:
        # 同账号不同存档也先断开B，再连接A；绝不写当前账号文件或调用报名接口。
        log('正在连接小存档B，读取报名状态和推荐列表……')
        flow, entry = connect_fn(source, source_slot)
        home = checked(flow.request('scene.%sHandler.getArenaInfo' % handler, {}), '读取小存档推荐列表')
        rank, applied = enrollment(home, entry, handler)
        if rank != -1 or applied != 0:
            raise ValueError('提供列表的小存档B必须处于未报名、未上榜状态')
        source_rid = (home.get('self') or {}).get('rid')
        if not source_rid:
            raise ValueError('小存档缺少实际存档ID')
        rows = [row for row in home.get('recommend') or [] if row.get('rid')]
        if not rows:
            raise ValueError('小存档当前没有推荐对手')
        log('已确认B未报名；推荐列表包含%d名对手。' % len(rows))
        source_summary = '%s，槽%d，%s（未报名）' % (
            source.get('username') or source['uid'], source_slot, role_names(entry))
        flow.disconnect()
        flow = None
        log('已读取B的列表，正在切回出战存档A核对状态……')
        flow, entry = connect_fn(actor, actor_slot)
        actor_home = checked(flow.request('scene.%sHandler.getArenaInfo' % handler, {}), '读取出战存档状态')
        actor_rank, actor_applied = enrollment(actor_home, entry, handler)
        if actor_rank < 0 and actor_applied <= 0:
            raise ValueError('出战存档A尚未报名，请选择已报名的存档；查询不会自动报名')
        actor_rid = (actor_home.get('self') or {}).get('rid')
        if not actor_rid or actor_rid == source_rid:
            raise ValueError('出战存档A必须与提供列表的小存档B不同')
        targets, skipped, seen = [], [], set()
        for index, row in enumerate(rows, 1):
            rid = row['rid']
            if rid == actor_rid or rid in seen:
                skipped.append({'rid': rid, 'reason': '自己或重复目标'})
                log('核对%d/%d：跳过 %s（自己或重复目标）' % (index, len(rows), rid))
                continue
            seen.add(rid)
            log('正在核对%d/%d：%s' % (index, len(rows), rid))
            try:
                data = detail(flow, handler, rid)
            except RuntimeError:
                skipped.append({'rid': rid, 'reason': '对手资料查询失败'})
                log('跳过 %s：对手资料查询失败。' % rid)
                continue
            log('核对成功：%s（%s）' % (data['name'], rid))
            targets.append({'rid': rid, 'name': data['name'],
                            'identity': identity(data, handler), 'summary': description(data, handler)})
        if not targets:
            raise ValueError('借用列表中没有可核对的对手，未发起挑战')
        return {'mode': 'borrowed', 'actor_rid': actor_rid, 'source_rid': source_rid,
                'source_uid': str(source['uid']), 'source_slot': int(source_slot),
                'source_rank': rank, 'source_apply_time': applied,
                'actor_summary': '%s，槽%d，%s' % (
                    actor.get('username') or actor['uid'], actor_slot, role_names(entry)),
                'source_summary': source_summary, 'targets': targets, 'skipped': skipped,
                'queried_at': datetime.now(timezone.utc).isoformat()}
    finally:
        if flow:
            flow.disconnect()


def validate_list(approval, flow, slot, rounds, home, battle_wait, round_wait):
    expected = {'mode': 'borrowed', 'actor_uid': str(flow.uid), 'actor_slot': int(slot),
                'handler': home['handler'], 'rounds': int(rounds),
                'battle_wait': battle_wait, 'round_wait': round_wait}
    if not isinstance(approval, dict) or any(approval.get(k) != v for k, v in expected.items()):
        raise RuntimeError('借用列表尚未确认，或出战账号/槽位/次数/间隔已变更；未挑战')
    rank = (home.get('self') or {}).get('rank')
    weekly = home.get('everyWeekSetting') or {}
    field = 'applyForArenaTime' if home['handler'] == 'arena' else 'applyForPetArenaTime'
    if rank is None or (int(rank) < 0 and not weekly.get(field)):
        raise RuntimeError('出战存档A当前未报名，停止借用挑战')
    actor_rid = (home.get('self') or {}).get('rid')
    if actor_rid != approval.get('actor_rid') or actor_rid == approval.get('source_rid'):
        raise RuntimeError('实际出战存档与确认时不同，未挑战')
    if approval.get('source_rank') != -1 or approval.get('source_apply_time') != 0:
        raise RuntimeError('缺少小存档未报名的查询结果，未挑战')
    targets = approval.get('targets')
    if not isinstance(targets, list) or not targets or len(targets) > 120:
        raise RuntimeError('确认的推荐列表无效，未挑战')
    if any(not isinstance(t, dict) or not t.get('rid') or not t.get('identity')
           or t['rid'] == actor_rid for t in targets):
        raise RuntimeError('确认列表包含无效目标或自己，未挑战')
    return targets


def verified_target(flow, handler, target):
    data = detail(flow, handler, target['rid'])
    if identity(data, handler) != target['identity']:
        raise RuntimeError('借用对手%s的身份或阵容已变化，请重新查询并确认' % target['name'])
    return target['rid'], data
