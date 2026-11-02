"""通天河抢船：10 秒刷新候选；海舰优先；首分钟等待；战斗中短间隔重试。"""

import argparse
import json
import time
from pathlib import Path


FIRST_AREA_SECONDS = 60
PROTECTION_MARGIN_SECONDS = 0.1
LAST_AREA_SECONDS = 240
LIST_INTERVAL_SECONDS = 10
BUSY_RETRY_SECONDS = 0.2
ROBBED_MAX = 2
DAILY_MAX = 4
ESCORT_MAX = 3
FREE_REFRESH_MAX = 5
BATTLE_WAIT_SECONDS = 25
SHIP_NAMES = {1: "木舟", 2: "宝船", 3: "银帆", 4: "海舰"}

from functools import lru_cache

@lru_cache(maxsize=2)
def qi_cargo_ids(item_id):
    root = Path(__file__).resolve().parent
    folders = sorted(root.glob('cg_config_out_cg1_*'), reverse=True)
    path = next((p/'TongtianRiverEscortTarget.json' for p in folders
                 if (p/'TongtianRiverEscortTarget.json').is_file()), None)
    if path is None:
        raise RuntimeError('缺少通天河货物配置，无法确认天清气/地浊气船')
    rows = json.loads(path.read_text(encoding='utf-8-sig'))
    return {int(k) for k,v in rows.items() if int(k)%1000 == 4
            and item_id in set(str(v.get('target_subType','')).split(';'))}

def qi_ship_ids():
    return qi_cargo_ids('101042005') | qi_cargo_ids('101042006')

class RiverClosed(RuntimeError):
    pass


def _error(response):
    if not isinstance(response, dict):
        return str(response)
    if response.get("error"):
        return str(response["error"])
    if response.get("code") not in (None, 200):
        return str(response.get("message") or response.get("code"))
    return ""


def _is_busy(response):
    detail = json.dumps(response, ensure_ascii=False) if isinstance(response, dict) else str(response)
    return "战斗" in detail or "交战" in detail or "busy" in detail.lower()


def _ships(response, level, power, own_uid, full_reward_only=False):
    from tongtian_reward_filter import rates,full_reward
    reward_rates=rates() if full_reward_only else None
    now_ms = int(response.get("serverTime") or time.time() * 1000)
    candidates = []
    for raw in response.get("list") or []:
        try:
            ship = json.loads(raw) if isinstance(raw, str) else raw
            uid = int(ship["uid"])
            user = ship["userdata"]
            other_level = int(user["level"])
            other_power = float(user["fightPower"])
            if str(uid) == str(own_uid) or abs(level - other_level) > 10 or other_power <= 0:
                continue
            if full_reward_only and not full_reward(level,other_level,reward_rates):continue
            if min(power, other_power) / max(power, other_power) < 0.6:
                continue
            start_ms = int(ship["startTime"])
            end_ms = int(ship["endTime"])
            if end_ms - now_ms <= LAST_AREA_SECONDS * 1000:
                continue
            robbed = ship.get("robEvents") or []
            if isinstance(robbed, str):
                robbed = json.loads(robbed)
            if len(robbed) >= ROBBED_MAX:
                continue
            candidates.append({"uid": uid, "good_id": int(ship["goodId"]), "tier": int(ship["goodId"]) % 1000,
                               "robbed": len(robbed), "start_ms": start_ms,
                               "end_ms": end_ms, "now_ms": now_ms,
                               "server_offset_ms": now_ms - time.time()*1000,"level":other_level})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    # 大船优先；同档优先完整的两次被抢机会；再选最早脱离保护期的船。
    candidates.sort(key=lambda x: (-x["tier"], x["robbed"], x["start_ms"]))
    return candidates


def _wait_until_ready(ship, deadline):
    ready_at = ship["start_ms"] / 1000 + FIRST_AREA_SECONDS + PROTECTION_MARGIN_SECONDS
    server_offset = ship["now_ms"] / 1000 - time.time()
    wait = ready_at - (time.time() + server_offset)
    if wait > 0:
        print("[%s档] 首分钟保护中，等待约 %.1f 秒" % (ship["tier"], wait), flush=True)
        time.sleep(min(wait, max(0, deadline - time.monotonic())))


def voyage_key(ship):
    return (ship['uid'], ship['start_ms'])


def merge_candidates(pool, incoming, rejected):
    """保留刷新未返回的旧船及其追抢状态，仅补充新航次。"""
    added = []
    for ship in incoming:
        if voyage_key(ship) in rejected:
            continue
        previous = next((v for v in pool if v['uid']==ship['uid']), None)
        if previous is not None:
            if ship['start_ms'] <= previous['start_ms']:
                continue
            pool.remove(previous)
            rejected.add(voyage_key(previous))
        pool.append(ship)
        added.append(ship)
    return added


def scheduled_targets(pool):
    """每步只调度一艘，避免整批网络请求拖过其他船的解保时点。"""
    now = time.monotonic()
    ready = []
    imminent = False
    for ship in pool:
        offset = ship.setdefault('server_offset_ms', ship['now_ms']-time.time()*1000)
        server_now = time.time()*1000+offset
        until_ready = (ship['start_ms']+(FIRST_AREA_SECONDS+PROTECTION_MARGIN_SECONDS)*1000-server_now)/1000
        if server_now >= ship['end_ms']-LAST_AREA_SECONDS*1000:
            return [ship]  # 交给_attack移除过期航次。
        if until_ready > 0:
            if now >= ship.get('next_wait_log',0):
                print('[目标%s调度] 保护还剩%.1f秒，保留候选' % (ship['uid'],until_ready),flush=True)
                ship['next_wait_log']=now+10
            if until_ready <= 1:
                imminent = True
            continue
        if now < ship.get('next_attempt',0):
            continue
        # 原船连抢、刚解保首发优先；其他目标按下次尝试时间公平轮转。
        priority = 0 if ship.get('chain_retry') else 1 if not ship.get('attempts') and until_ready >= -2 else 2
        ready.append((priority,ship.get('next_attempt',0),ship))
    ready.sort(key=lambda row:(row[0],row[1]))
    if ready and (not imminent or ready[0][0] < 2):
        return [ready[0][2]]
    # 有船即将解保时，不先发另一个普通目标的慢请求。
    return []


def _attack(flow, ship, deadline):
    """单目标只尝试一步：True成功、False移除、None保留供下一轮。"""
    if time.monotonic() >= deadline:
        return None
    offset = ship.setdefault('server_offset_ms', ship['now_ms'] - time.time()*1000)
    now_ms = time.time()*1000 + offset
    if now_ms >= ship['end_ms'] - LAST_AREA_SECONDS*1000:
        print('[目标%s] 进入末段保护区，移出队列' % ship['uid'], flush=True)
        return False
    ready_ms = ship['start_ms'] + (FIRST_AREA_SECONDS + PROTECTION_MARGIN_SECONDS)*1000
    if now_ms < ready_ms:
        if time.monotonic() >= ship.get('next_wait_log', 0):
            print('[目标%s] 首分钟保护还剩%.1f秒，先轮询其他船' %
                  (ship['uid'], (ready_ms-now_ms)/1000), flush=True)
            ship['next_wait_log'] = time.monotonic()+10
        return None
    if time.monotonic() < ship.get('next_attempt', 0):
        return None
    if time.monotonic() >= ship.setdefault('next_check', time.monotonic()+LIST_INTERVAL_SECONDS):
        state = flow.request('scene.tongtianHandler.getRobEvent', {'targetId':ship['uid']})
        detail = _error(state)
        if detail:
            print('[目标%s记录] %s；移出队列' % (ship['uid'], detail), flush=True)
            return False
        events = state.get('event') if isinstance(state, dict) else None
        if isinstance(events, str):
            try: events = json.loads(events)
            except ValueError: events = None
        if isinstance(events, list):
            ship['robbed'] = len(events)
            if ship['robbed'] >= ROBBED_MAX:
                print('[目标%s记录] 已被抢满，移出队列' % ship['uid'], flush=True)
                return False
        print('[目标%s记录] 已知被抢%d/2，已尝试%d次' %
              (ship['uid'], ship['robbed'], ship.get('attempts',0)), flush=True)
        ship['next_check'] = time.monotonic()+LIST_INTERVAL_SECONDS
    if time.monotonic() >= deadline:
        return None
    response = flow.request('scene.tongtianHandler.beginAttack', {'targetId':ship['uid']})
    ship['attempts'] = ship.get('attempts',0)+1
    ship['next_attempt'] = time.monotonic()+BUSY_RETRY_SECONDS
    error = _error(response)
    if '暂未开放' in error or '未开启' in error:
        raise RiverClosed(error)
    if not error and isinstance(response, dict) and response.get('escortData'):
        rid = response['escortData'].get('uid') or ship['uid']
        print('[目标%s] 已进入抢船战斗，暂停其他候选；等待结算' % ship['uid'], flush=True)
        wait_seconds = getattr(flow, '_tongtian_battle_wait', BATTLE_WAIT_SECONDS)
        print('[抢船] 本次结算等待%.1f秒' % wait_seconds, flush=True)
        time.sleep(wait_seconds)
        finish = flow.request('scene.tongtianHandler.endAttack', {'targetId':rid,'win':1})
        print('[抢船结算] code=%s error=%s' % ((finish or {}).get('code'),(finish or {}).get('error')), flush=True)
        if isinstance(finish, dict) and finish.get('give'):
            print('[抢船奖励] %s' % json.dumps(finish['give'],ensure_ascii=False), flush=True)
        if _error(finish):
            raise RuntimeError('已入场但结算失败，停止其他候选，需核对实际状态')
        return True
    if ship.get('last_error') != error:
        print('[目标%s抢船请求] %s' % (ship['uid'], error or response), flush=True)
        ship['last_error'] = error
    if _is_busy(response) and ship['robbed'] == 0:
        return None
    print('[目标%s] 不再追抢，移出队列' % ship['uid'], flush=True)
    return False


def _active_escort(info):
    escort = (info.get("tongtianRiver") or {}).get("escortData")
    if isinstance(escort, str):
        escort = json.loads(escort)
    return escort if isinstance(escort, dict) and escort.get("uid") else None


def _single_action(flow, info, action, slot):
    if not (info.get("p1") or {}).get("level"):
        print("[槽%d] 没有可用角色，停止" % slot, flush=True)
        return
    daily = info.get("everyDaySetting") or {}
    active = _active_escort(info)
    ship_state = info.get("tongtianRiver") or {}
    tier = int(ship_state.get("goodId") or 1)
    good_type = int(ship_state.get("goodType") or 0)
    used_refresh = int(daily.get("tongtianRiverEscortRefreshNum") or 0)
    if action == "status":
        print("[槽%d 船档] 材料组 %d，当前 %s（%d档）；今日免费刷新剩余 %d/%d，发船剩余 %d/%d" %
              (slot, good_type, SHIP_NAMES.get(tier, "未知"), tier,
               max(0, FREE_REFRESH_MAX - used_refresh), FREE_REFRESH_MAX,
               max(0, ESCORT_MAX - int(daily.get("tongtianRiverEscortNum") or 0)), ESCORT_MAX),
              flush=True)
        if active:
            state = flow.request("scene.tongtianHandler.getEscortList", {})
            server_ms = int(state.get("serverTime") or time.time() * 1000)
            remaining = max(0, round((int(active.get("endTime") or 0) - server_ms) / 1000))
            print("[槽%d 护送] %s，约剩 %d 秒%s" %
                  (slot, SHIP_NAMES.get(int(active.get("goodId") or 0) % 1000, "船"), remaining,
                   "，可以领奖" if remaining == 0 else ""), flush=True)
        return
    if action in ("refresh", "upgrade"):
        if active:
            print("[槽%d 刷新] 已有正在护送或待领奖的船，停止" % slot, flush=True)
            return
        while used_refresh < FREE_REFRESH_MAX and tier < 4:
            result = flow.request("scene.tongtianHandler.freshEscortGood", {})
            if _error(result):
                print("[槽%d 刷新] 停止：%s" % (slot, _error(result)), flush=True)
                return
            updated = result.get("tongtianRiver") or {}
            if "goodId" not in updated:
                print("[槽%d 刷新] 回包缺少新船档，停止" % slot, flush=True)
                return
            tier = int(updated["goodId"])
            updated_daily = result.get("everyDaySetting") or {}
            used_refresh = int(updated_daily.get("tongtianRiverEscortRefreshNum") or (used_refresh + 1))
            print("[槽%d 刷新] 当前 %s（%d档），今日免费刷新剩余 %d/%d" %
                  (slot, SHIP_NAMES.get(tier, "未知"), tier,
                   max(0, FREE_REFRESH_MAX - used_refresh), FREE_REFRESH_MAX), flush=True)
            if action == "refresh":
                return
        if tier >= 4:
            print("[槽%d 刷新] 已达海舰最高档" % slot, flush=True)
        else:
            print("[槽%d 刷新] 今日免费次数已用完" % slot, flush=True)
        return
    if action == "escort":
        if int(daily.get("tongtianRiverEscortNum") or 0) >= ESCORT_MAX:
            print("[槽%d 发船] 今日护送次数已用完" % slot, flush=True)
            return
        if active:
            print("[槽%d 发船] 已有待领取或正在护送的船，请先领奖" % slot, flush=True)
            return
        result = flow.request("scene.tongtianHandler.escort", {})
    elif action == "reward":
        if not active:
            print("[槽%d 领奖] 当前没有待领取的船" % slot, flush=True)
            return
        state = flow.request("scene.tongtianHandler.getEscortList", {})
        server_ms = int(state.get("serverTime") or time.time() * 1000)
        remaining = (int(active.get("endTime") or 0) - server_ms) / 1000
        if remaining > 0:
            print("[槽%d 领奖] 船还需约%d秒到达" % (slot, round(remaining)), flush=True)
            return
        result = flow.request("scene.tongtianHandler.getReward", {})
    else:
        raise ValueError(action)
    result = result if isinstance(result, dict) else {"error": str(result)}
    print("[槽%d %s] code=%s error=%s" %
          (slot, "发船" if action == "escort" else "领奖",
           result.get("code"), result.get("error")), flush=True)
    if result.get("give"):
        print("[到账] %s" % json.dumps(result["give"], ensure_ascii=False), flush=True)


def run(max_wait_seconds=600, action="rob", slot=None, sea_only=False, qi_only=False,
        battle_wait_seconds=25, chain_twice=True, qi_kinds=None, escort_strategy="direct", full_reward_only=True):
    try:
        battle_wait = float(battle_wait_seconds)
    except (TypeError, ValueError):
        raise ValueError('结算等待时间须为1至30秒整数')
    if not battle_wait.is_integer() or not 1 <= battle_wait <= 30:
        raise ValueError('结算等待时间须为1至30秒整数')
    import daily_auto
    if qi_only and qi_kinds is not None and (not qi_kinds or not set(qi_kinds)<= {'heaven','earth'}):
        raise ValueError('货物筛选至少选择天清气或地浊气一种')
    allowed_goods = (qi_ship_ids() if qi_kinds is None else set().union(*[
        qi_cargo_ids('101042005' if kind=='heaven' else '101042006') for kind in qi_kinds
    ])) if action == 'rob' and qi_only else None
    chosen_slot = daily_auto.RECORD_INDEX if slot is None else slot
    if action in ('status','refresh','upgrade','escort'):
        from tongtian_auto_slot import connect_auto
        try:flow,info,chosen_slot,_=connect_auto()
        except (ValueError,RuntimeError,OSError) as exc:
            print('__TTR_ESCORT_ABORT__'+json.dumps({'message':str(exc)},ensure_ascii=False),flush=True)
            raise
    else:
        flow, info = daily_auto.login(record_index=chosen_slot)
    flow._tongtian_battle_wait = int(battle_wait)
    try:
        if action != "rob":
            if action=='escort' and escort_strategy!='direct':
                from tongtian_escort_strategy import run as escort_run
                from teacher_trial import enter
                try:
                    escort_run(flow,info,chosen_slot,escort_strategy,lambda:enter(flow,chosen_slot))
                except (ValueError,RuntimeError,OSError) as exc:
                    print('__TTR_ESCORT_ABORT__'+json.dumps({'message':str(exc)},ensure_ascii=False),flush=True)
                    raise
            else:
                _single_action(flow, info, action, chosen_slot)
            return
        player = info.get("p1") or {}
        if not player.get("level") or not player.get("fightPower"):
            print("[槽%d 抢船] 没有可用角色或战力，停止" % chosen_slot, flush=True)
            return
        level = int(player["level"])
        if full_reward_only:
            from tongtian_reward_filter import target_range
            low,high=target_range(level)
            print('[抢船等级筛选] 自身%s级，仅选%s～%s级船主，维持正常可抢奖励比例'%(level,low,high),flush=True)
        power = float(player["fightPower"])
        own_uid = info.get("uid") or player.get("uid")
        used = int((info.get("everyDaySetting") or {}).get("tongtianRiverRobNum") or 0)
        if used >= DAILY_MAX:
            print("[槽%d 抢船] 今日 4 次已用完" % chosen_slot, flush=True)
            return
        deadline = time.monotonic() + max_wait_seconds
        rejected = set()
        pool = []
        next_list = 0
        initial_used = used
        while time.monotonic() < deadline:
            # 刚成功后的原船第二抢优先，避免被列表刷新延迟。
            chain_pending = any(v.get('chain_retry') for v in pool)
            release_pending = any(not v.get('attempts') and -2 <= (
                v['start_ms']+(FIRST_AREA_SECONDS+PROTECTION_MARGIN_SECONDS)*1000
                -(time.time()*1000+v.get('server_offset_ms',0)))/1000 <= 1 for v in pool)
            if time.monotonic() >= next_list and not chain_pending and not release_pending:
                response = flow.request('scene.tongtianHandler.getEscortList', {})
                next_list = time.monotonic()+LIST_INTERVAL_SECONDS
                error = _error(response)
                if error:
                    print('[刷新列表] %s' % error, flush=True)
                    if '暂未开放' in error or '未开启' in error: return
                incoming = [] if error else [v for v in _ships(response,level,power,own_uid,full_reward_only=full_reward_only)
                        if (not sea_only or v['tier']==4)
                        and (allowed_goods is None or v['good_id'] in allowed_goods)]
                added = merge_candidates(pool,incoming,rejected)
                print('[候选队列] 本次新增%d艘，保留共%d艘；旧船未在新列表中出现也继续追踪' % (len(added),len(pool)), flush=True)
                for i,v in enumerate(added,1):
                    cargo = '天清气' if v['good_id'] in qi_cargo_ids('101042005') else '地浊气' if v['good_id'] in qi_cargo_ids('101042006') else '其他货物'
                    print('[候选%d] 目标%s，%s，%s，已被抢%d/2' %
                          (i,v['uid'],SHIP_NAMES.get(v['tier'],'未知船档'),cargo,v['robbed']), flush=True)
            for target in scheduled_targets(pool):
                if time.monotonic() >= deadline: break
                try: result = _attack(flow,target,deadline)
                except RiverClosed as exc:
                    print('[抢船] %s，停止本轮' % exc, flush=True)
                    return
                if result is True:
                    refreshed = flow.request('connector.entryHandler.entry', {
                        'index':chosen_slot,'userAgent':flow.user_agent})
                    if _error(refreshed) or not isinstance(refreshed.get('info'),dict):
                        raise RuntimeError('抢船成功后无法核对剩余次数，停止')
                    fresh_used = (refreshed['info'].get('everyDaySetting') or {}).get('tongtianRiverRobNum')
                    if fresh_used is None or int(fresh_used)<=used:
                        raise RuntimeError('抢船结算后次数未确认增加，停止')
                    used = int(fresh_used)
                    print('[抢船] 今日已用%d/4' % used, flush=True)
                    if used>=DAILY_MAX: return
                    target['own_successes'] = target.get('own_successes', 0)+1
                    if chain_twice and target['tier']==4 and target['own_successes']<2:
                        target['next_check']=0
                        target['next_attempt']=0
                        target['last_error']=None
                        target['chain_retry']=True
                        pool.remove(target);pool.insert(0,target)
                        print('[连抢] 暂不刷新列表，优先核对并再次尝试原海舰%s；失败则换船' % target['uid'], flush=True)
                        break
                    pool.remove(target);rejected.add(voyage_key(target));next_list=0
                    print('[抢船] 原船策略执行完成，刷新补充下一批', flush=True)
                    break
                if result is False:
                    pool.remove(target);rejected.add(voyage_key(target))
                    if target.get('chain_retry'):
                        next_list=0
                        print('[连抢] 原海舰无法继续抢，刷新下一批', flush=True)
            time.sleep(min(0.05,max(0,deadline-time.monotonic())))
        print('[抢船] 等待时间已到，本轮成功%d次' % (used-initial_used), flush=True)
    finally:
        flow.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("status", "refresh", "upgrade", "escort", "reward", "rob"), default="rob")
    parser.add_argument("--slot", type=int, choices=range(8))
    parser.add_argument("--max-wait", type=int, default=600)
    parser.add_argument("--sea-only", action="store_true")
    parser.add_argument("--qi-only", action="store_true", help='仅抢天清气/地浊气海舰')
    parser.add_argument('--qi-kind', action='append', choices=('heaven','earth'), help='筛选天清气heaven或地浊气earth，可重复指定；省略时两种都要')
    parser.add_argument('--battle-wait', type=int, choices=range(1,31), default=25, metavar='1-30', help='入场后结算等待秒数，1至30整数，默认25秒')
    parser.add_argument('--no-chain', action='store_true', help='关闭原海舰优先连抢两次策略')
    parser.add_argument('--escort-strategy',choices=('direct','spirit_buyer','free'),default='direct')
    parser.add_argument('--allow-reduced-reward',action='store_true',help='允许抢取等级奖励折扣目标；默认仅满额奖励范围')
    args = parser.parse_args()
    run(max_wait_seconds=args.max_wait, action=args.action, slot=args.slot,
        sea_only=args.sea_only, qi_only=args.qi_only, battle_wait_seconds=args.battle_wait,
        chain_twice=not args.no_chain, qi_kinds=args.qi_kind, escort_strategy=args.escort_strategy, full_reward_only=not args.allow_reduced_reward)
