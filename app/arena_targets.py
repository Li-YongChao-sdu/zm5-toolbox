"""竞技场/斗宠跨榜选人、指定存档及有间隔的结算。"""
import json
import math
import re
import random
import time
from datetime import datetime, timezone, timedelta


def checked(reply, action):
    if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
        raise RuntimeError('%s失败：%s' % (action, reply.get('error') if isinstance(reply, dict) else reply))
    return reply


def wait_seconds(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError('等待时间必须是非负秒数')
    if not math.isfinite(value) or value < 0:
        raise ValueError('等待时间必须是有限的非负秒数')
    return value


def target_id(uid, slot):
    uid, slot = str(uid).strip(), str(slot).strip()
    if not re.fullmatch(r'[0-9]+', uid) or int(uid) <= 0:
        raise ValueError('对手 UID 必须是正整数')
    if not re.fullmatch(r'[0-9]+', slot):
        raise ValueError('对手存档槽位必须是非负整数')
    return '%s_r%d' % (uid, int(slot))


def power(row, handler):
    if handler == 'petArena':
        pets = row.get('pets') or []
        if not pets or any(p.get('fightPower') is None for p in pets):
            raise ValueError('榜单缺少宠物战力')
        values = [float(p['fightPower']) for p in pets]
    else:
        player = row.get('p1') if int(row.get('index', 0)) == 0 else row.get('p2')
        if not player or player.get('fightPower') is None:
            raise ValueError('榜单缺少出战角色战力')
        values = [float(player['fightPower'])]
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('榜单战力无效')
    return sum(values)


def pet_identity(pets, detail=False):
    return [(str(p['id']), p.get('nickName') if detail else p.get('name'),
             p.get('level'), p.get('sex')) for p in pets]


def detail(flow, handler, rid):
    suffix = 'getArenaUserData' if handler == 'petArena' else 'getArenaTargetInfo'
    reply = checked(flow.request('scene.%sHandler.%s' % (handler, suffix), {'targetId': rid}), '查询对手')
    data = reply.get('data') if handler == 'petArena' else reply.get('userData')
    if not isinstance(data, dict) or data.get('rid') != rid or not data.get('name'):
        raise RuntimeError('目标资料缺少身份信息或存档 ID 不符')
    return data


def matches(row, data, handler):
    if row.get('name') != data.get('name'):
        return False
    if handler == 'petArena':
        return (str(row.get('charId')) == str(data.get('charId')) and
                pet_identity(row['pets']) == pet_identity(data.get('pets') or [], True))
    index = int(row.get('index', 0))
    expected = row.get('p1' if index == 0 else 'p2') or {}
    actual = data.get('p1' if index == 0 else 'p2') or {}
    char_id = actual.get('charId', data.get('charId'))
    return str(expected.get('charId')) == str(char_id) and int(data.get('index', index)) == index


def top_n_value(value):
    text = str(value).strip()
    if not re.fullmatch(r'[0-9]+', text) or not 10 <= int(text) <= 100:
        raise ValueError('随机挑战的N必须是10～100的整数')
    return int(text)


def rank_rows(flow, handler, home, sleep=time.sleep):
    rows = {}
    for page in range(20):
        reply = checked(flow.request('scene.%sHandler.getArenaRank' % handler,
                                    {'index': home['index'], 'page': page}), '读取排行榜')
        for row in reply.get('rows') or []:
            rank = int(row['rank'])
            if 0 <= rank < 120:
                rows[rank] = row
        if len(rows) == 120:
            break
        if not reply.get('rows'):
            break
        sleep(1)
    if len(rows) != 120:
        raise RuntimeError('未完整读取排行榜前120名，停止选人')
    return [row for _, row in sorted(rows.items())]


def top_power_rows(rows, handler, n):
    n = top_n_value(n)
    return sorted(rows, key=lambda row: (-power(row, handler), int(row['rank'])))[:n]


class RankResolver:
    def __init__(self, flow, handler, sleep=time.sleep):
        self.flow, self.handler, self.sleep = flow, handler, sleep
        self.role_rows = {}

    def resolve(self, row, exclude_rid=None):
        if self.handler == 'petArena':
            char_id = row['charId']
        else:
            char_id = row['p1' if int(row.get('index', 0)) == 0 else 'p2']['charId']
        role = int(char_id) % 10
        if role not in self.role_rows:
            items = []
            for page in range(1, 16):
                reply = checked(self.flow.request('scene.rankHandler.getRank',
                                            {'type': role, 'page': page, 'index': 0}), '读取角色战力榜')
                batch = reply.get('rows') or []
                items.extend(json.loads(raw) if isinstance(raw, str) else raw for raw in batch)
                if not batch:
                    break
                self.sleep(1)
            self.role_rows[role] = items
        candidates = set()
        for item in self.role_rows[role]:
            if item.get('name') != row['name']:
                continue
            match = re.fullmatch(r'([0-9]+_r[0-9]+)_c[01]', str(item.get('id', '')))
            if match and match.group(1) != exclude_rid:
                candidates.add(match.group(1))
        verified = []
        for rid in sorted(candidates):
            try:
                data = detail(self.flow, self.handler, rid)
            except RuntimeError:
                print('[排行榜] %s 的目标资料查询未通过，跳过该存档' % row['name'], flush=True)
                continue
            if matches(row, data, self.handler):
                verified.append((rid, data))
        if len(verified) != 1:
            return None
        return verified[0]


def prepare_rank_pool(rows, resolver, exclude_rid=None):
    pool = []
    seen = set()
    for index, row in enumerate(rows, 1):
        result = resolver.resolve(row, exclude_rid)
        if result is None:
            print('[排行榜随机] %d/%d：%s 无法唯一核对或为自己，跳过' %
                  (index, len(rows), row['name']), flush=True)
        else:
            rid, data = result
            if rid not in seen:
                pool.append((row, rid, data))
                seen.add(rid)
            print('[排行榜随机] %d/%d：已核对 %s (%s)' %
                  (index, len(rows), data['name'], rid), flush=True)
        resolver.sleep(1)
    if not pool:
        raise RuntimeError('战力前N名内无可唯一核对的目标，未扩大候选范围')
    return pool


def random_rank_target(pool, resolver, exclude_rid=None, rng=random):
    remaining = list(pool)
    while remaining:
        candidate = rng.choice(remaining)
        remaining.remove(candidate)
        row, rid, _ = candidate
        if rid == exclude_rid:
            continue
        try:
            data = detail(resolver.flow, resolver.handler, rid)
        except RuntimeError:
            print('[排行榜随机] %s 的资料已不可查询，本局跳过' % row['name'], flush=True)
            continue
        if not matches(row, data, resolver.handler):
            print('[排行榜随机] %s 的身份或阵容已变化，本局跳过' % row['name'], flush=True)
            continue
        print('[排行榜随机] 战力=%s；竞技排名=%d；目标=%s；ID=%s' %
              (power(row, resolver.handler), int(row['rank']) + 1, data['name'], rid), flush=True)
        return rid, data
    raise RuntimeError('战力前N名内无可唯一核对的目标，未扩大候选范围')


def rank_target(flow, handler, home, sleep=time.sleep):
    rows = rank_rows(flow, handler, home, sleep)
    top_power = max(power(row, handler) for row in rows)
    resolver = RankResolver(flow, handler, sleep)
    for row in rows:
        if power(row, handler) != top_power:
            continue
        result = resolver.resolve(row)
        if result is not None:
            rid, data = result
            print('[排行榜] 前120名最高战力=%s；排名=%d；目标=%s；ID=%s' %
                  (top_power, int(row['rank']) + 1, data['name'], rid), flush=True)
            return result
    raise RuntimeError('最高战力目标无法唯一匹配角色 ID，未替换为其他战力目标')


def snapshot(flow, handler, slot):
    entry = checked(flow.request('connector.entryHandler.entry',
                                {'index': slot, 'userAgent': flow.user_agent}), '刷新存档')['info']
    user = checked(flow.request('connector.roleHandler.getUserInfo', {}), '读取点券')['user']
    home = checked(flow.request('scene.%sHandler.getArenaInfo' % handler, {}), '读取挑战状态')
    weekly = dict(entry.get('everyWeekSetting') or {})
    weekly.update(home.get('everyWeekSetting') or {})
    home = dict(home, everyWeekSetting=weekly)
    day = (datetime.now(timezone(timedelta(hours=8))).weekday() + 1) % 7
    limit = int(home['jjcChallengeNum'].split(';')[day])
    used = int(((weekly.get(handler + 'Setting') or {}).get('week') or {}).get(str(day), 0))
    money = entry.get(handler + 'Money')
    if money is None or user.get('ticket') is None:
        raise RuntimeError('无法确认竞技币/斗宠币或点券余额')
    return {'used': used, 'limit': limit, 'money': int(money), 'ticket': int(user['ticket'])}, home


def run(flow, handler, slot, mode, uid='', target_slot='0', rounds=5,
        sleep=time.sleep, confirmation=None, top_n=20, battle_wait=22, round_wait=22,
        target_input='slot', explicit_rid=''):
    battle_wait, round_wait = wait_seconds(battle_wait), wait_seconds(round_wait)
    rounds = int(rounds)
    if rounds not in (5, 10):
        raise ValueError('连续挑战次数只能选择5或10')
    if mode == 'rank_random':
        top_n = top_n_value(top_n)
    if mode == 'specified':
        from arena_slot_mapping import confirmed_rid
        rid = confirmed_rid(confirmation, target_input, uid, target_slot, explicit_rid)
    before, home = snapshot(flow, handler, slot)
    if before['used'] >= before['limit']:
        print('[%s] 今日免费次数已用尽，不使用点券' % handler, flush=True)
        return
    if mode == 'specified':
        if rid == (home.get('self') or {}).get('rid'):
            raise RuntimeError('不能挑战当前出战存档本人；同账号可选择其他存档')
        data = detail(flow, handler, rid)
        from arena_target_confirm import validate
        validate(confirmation, flow, slot, rid, rounds, data, handler, battle_wait, round_wait)
    elif mode == 'borrowed':
        from arena_borrow import validate_list, verified_target
        borrowed = validate_list(confirmation, flow, slot, rounds,
                                 dict(home, handler=handler), battle_wait, round_wait)
        print('[%s] 使用已确认的小存档列表，共%d人，按顺序循环，最多%d局' %
              (handler, len(borrowed), rounds), flush=True)
    elif mode == 'rank_highest':
        rid, data = rank_target(flow, handler, home, sleep)
    elif mode == 'rank_random':
        rows = top_power_rows(rank_rows(flow, handler, home, sleep), handler, top_n)
        resolver = RankResolver(flow, handler, sleep)
        pool = prepare_rank_pool(rows, resolver, (home.get('self') or {}).get('rid'))
        print('[%s] 战力前%d名核对后可用%d人；每局随机选人，最多%d局免费挑战' %
              (handler, top_n, len(pool), rounds), flush=True)
    else:
        raise ValueError('未知挑战方式')
    if mode not in ('rank_random', 'borrowed'):
        print('[%s] 指定目标 %s (%s)，最多%d局' %
              (handler, data['name'], rid, rounds), flush=True)
    print('[%s] 每局等待%g秒；局间等待%g秒' % (handler, battle_wait, round_wait), flush=True)
    for index in range(rounds):
        pre, pre_home = snapshot(flow, handler, slot)
        is_paid = pre['used'] >= pre['limit']
        if is_paid:
            print('[%s] 今日免费次数已用尽；已完成%d/%d局，不使用点券' %
                  (handler, index, rounds), flush=True)
            break
        if mode == 'rank_random':
            rid, data = random_rank_target(pool, resolver, (home.get('self') or {}).get('rid'))
        if mode == 'borrowed':
            validate_list(confirmation, flow, slot, rounds, dict(pre_home, handler=handler),
                          battle_wait, round_wait)
            rid, data = verified_target(flow, handler, borrowed[index % len(borrowed)])
            print('[%s] 借用列表第%d人：%s (%s)' %
                  (handler, index % len(borrowed) + 1, data['name'], rid), flush=True)
        suffix = 'beginArenaBattle'
        # 开战和结算请求都只发一次；超时或未知结果停止，避免重复扣次数。
        begin = checked(flow.request('scene.%sHandler.%s' % (handler, suffix), {'targetId': rid}), '创建战斗')
        actual = (begin.get('userData') or {}).get('rid') or (begin.get('data') or {}).get('rid') or begin.get('rid')
        if actual and actual != rid:
            raise RuntimeError('服务器返回的实际对手不符，停止')
        if not actual:
            print('[%s] 开战回包未提供实际对手 ID；本局按指定 ID 结算' % handler, flush=True)
        sleep(battle_wait)
        checked(flow.request('scene.%sHandler.endArenaBattle' % handler,
                             {'targetId': rid, 'win': 1}), '胜利结算')
        post, _ = snapshot(flow, handler, slot)
        delta = post['money'] - pre['money']
        print('[%s] 第%d/%d局：币 %d→%d (%+d)；点券 %d→%d；免费次数 %d/%d' %
              (handler, index + 1, rounds, pre['money'], post['money'], delta,
               pre['ticket'], post['ticket'], post['used'], post['limit']), flush=True)
        if delta <= 0:
            raise RuntimeError('结算后币余额未增加，停止')
        if post['ticket'] != pre['ticket'] - (20 if is_paid else 0):
            raise RuntimeError('点券变化与预期不符，停止')
        if not is_paid and post['used'] != pre['used'] + 1:
            raise RuntimeError('免费次数变化与预期不符，停止')
        if index < rounds - 1:
            sleep(round_wait)
