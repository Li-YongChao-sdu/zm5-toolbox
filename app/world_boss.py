"""World Boss protocol run: join, paced attacks, and reward verification."""
import argparse
import json
import random
import sys
import threading
import time
from pathlib import Path
from main_farm import _connect, _entry
import daily_auto as da


from world_boss_damage import sample_hurt, sample_expected_hurt
from world_boss_model import WorldBossModel, build_panel


def pick_boss(info, fallback=960101, ratio=1.2):
    """按合成面板战力选档：取门槛不超过战力 ratio 倍的最高 Boss。"""
    stages = json.loads((Path(__file__).with_name('world_boss_stages.json')
                         ).read_text(encoding='utf-8-sig'))
    panel = build_panel(info) or {}
    power = float(panel.get('_power') or 0)
    if power <= 0:
        return int(fallback), stages[0], 0.0
    fits = [row for row in stages
            if float(row.get('highPower') or 0) <= power * ratio]
    row = fits[-1] if fits else stages[0]
    return int(row['id']), row, power


def run(boss_id=960101, hurt_min=100000, hurt_max=500000,
        target_percent=5.05, max_seconds=0,
        keepalive_min=0, keepalive_max=10000,
        room_override=None, expected_dps=None, idle_only=False,
        attack_to_target=True, idle_mode=False, real_damage=True,
        auto_boss=False):
    if hurt_min < 0 or hurt_max < hurt_min:
        raise ValueError('伤害范围无效')
    if keepalive_min < 0 or keepalive_max < keepalive_min:
        raise ValueError('达标后伤害范围无效')
    if expected_dps is not None and expected_dps <= 0:
        raise ValueError('每秒期望伤害须大于0')
    if not 0 < target_percent <= 100:
        raise ValueError('目标伤害占比须在0–100%之间')
    flow = _connect()
    state = {'hit': 0, 'finished': None, 'hp': None, 'exited': False, 'kicked': False}
    done = threading.Event()
    try:
        def on_hit(data):
            if isinstance(data, dict) and data.get('hit') is not None:
                state['hit'] = float(data['hit'])
                print('[世界Boss] 已计伤害 %.2f' % state['hit'], flush=True)

        def on_hp(data):
            if isinstance(data, dict) and data.get('hp') is not None:
                state['hp'] = float(data['hp'])

        def on_finish(data):
            state['finished'] = data
            print('[世界Boss] 结算推送：%s' % json.dumps(data, ensure_ascii=False, default=str)[:2200], flush=True)
            done.set()

        def on_exit(data):
            if isinstance(data, dict):
                print('[世界Boss] 离房推送：%s' % str(data)[:400], flush=True)
                state['exited'] = True

        def on_kick():
            state['kicked'] = True
            print('[世界Boss] 服务器踢出连接', flush=True)
            done.set()

        flow.on('onWorldBossSelfHit', on_hit)
        flow.on('onWorldBossHpChange', on_hp)
        flow.on('onFinishWorldBossCopy', on_finish)
        flow.on('onExitWorldBossCopy', on_exit)
        flow.game.set_kicked_callback(on_kick)
        before = _entry(flow)
        count_before = int((before.get('worldBoss') or {}).get('count') or 0)
        if count_before <= 0:
            raise RuntimeError('没有世界 Boss 挑战次数')
        if auto_boss:
            picked, stage, power = pick_boss(before, boss_id)
            if power > 0:
                print('[世界Boss] 面板战力 %.0f，自动选择 %s %s（门槛 %s）' % (
                    power, picked, stage.get('name'), stage.get('highPower')), flush=True)
            else:
                print('[世界Boss] 面板战力不可用，沿用 Boss %s' % boss_id, flush=True)
            boss_id = picked
        listed = flow.request('scene.worldBossHandler.getWorldBossRoomList',
                              {'bossId': boss_id, 'type': 0})
        if listed.get('code') != 200 or listed.get('error'):
            raise RuntimeError('查询房间失败: %s' % listed)
        candidates = [r for r in listed.get('rooms') or []
                      if float((r.get('boss') or {}).get('hp') or 0) > 0]
        if not candidates:
            raise RuntimeError('当前没有存活的 Boss 房间')
        if room_override:
            room = next((r for r in candidates if r.get('roomId') == room_override), None)
            if room is None:
                raise RuntimeError('指定房间已无存活 Boss: %s' % room_override)
        else:
            room = max(candidates, key=lambda r: float(r['boss'].get('hp') or 0))
        room_id = room['roomId']
        hp_max = float(room['boss']['hpMax'])
        goal = hp_max * target_percent / 100
        print('[世界Boss] 房间 %s，当前血量 %.0f/%.0f，参战 %s 人；目标伤害 %.0f' %
              (room_id, room['boss']['hp'], hp_max, room.get('userCnt'), goal), flush=True)
        joined = flow.request('scene.worldBossHandler.joinWorldBossCopy',
                              {'bossId': boss_id, 'roomId': room_id, 'type': 0})
        if joined.get('code') != 200 or joined.get('error') or joined.get('roomId') != room_id:
            raise RuntimeError('加入房间失败: %s' % joined)
        print('[世界Boss] 已加入，挑战次数原为 %s' % count_before, flush=True)
        end_seconds = max(0, (float(joined.get('endTime') or 0) / 1000) - time.time())
        wait_seconds = max_seconds if max_seconds > 0 else end_seconds + 60
        deadline = time.monotonic() + wait_seconds
        sent = 0
        idle = idle_only or (idle_mode and not attack_to_target)
        target_reached = False
        model = None
        if real_damage and not idle:
            try:
                model = WorldBossModel(before, boss_id)
                print('[世界Boss] 真实伤害：%s' % model.summary(), flush=True)
                for line in model.skill_lines():
                    print('[世界Boss]   %s' % line, flush=True)
                print('[世界Boss] 预计存活 %.0f 秒；每 %.0f 秒累计上报' %
                      (model.alive_seconds(), model.REPORT_INTERVAL), flush=True)
            except Exception as exc:
                print('[世界Boss] 真实伤害模型不可用（%s），改用随机伤害' % exc, flush=True)
        real = model is not None
        pending = 0.0
        failures = 0
        next_report = time.monotonic()
        revive_at = 0.0
        alive_until = time.monotonic() + model.alive_seconds() if model else 0.0

        def send(amount):
            nonlocal sent, failures
            if amount <= 0:
                return True
            try:
                result = flow.request('scene.worldBossHandler.attack',
                                      {'roomId': room_id,
                                       'hurt': int(round(amount)),
                                       'bossId': boss_id})
            except Exception as exc:
                failures += 1
                print('[世界Boss] 伤害请求异常(%s/%s)：%s' % (failures, 3, exc), flush=True)
                return failures < 3
            if result.get('code') != 200 or result.get('error'):
                failures += 1
                print('[世界Boss] 伤害请求停止(%s/%s)：%s' % (failures, 3, result), flush=True)
                return failures < 3
            failures = 0
            sent += 1
            return True

        while time.monotonic() < deadline and not done.is_set():
            if not flow.game._running:
                print('[世界Boss] 连接已断开，停止上报', flush=True)
                break
            if attack_to_target and not target_reached and state['hit'] >= goal:
                target_reached = True
                if idle_mode:
                    idle = True
                    real = False
                    if pending > 0:
                        send(pending)
                        pending = 0.0
                    print('[世界Boss] 已达目标，进入挂机模式', flush=True)
                else:
                    print('[世界Boss] 已达目标，继续按真实伤害上报', flush=True)
            if state['hp'] is not None and state['hp'] <= 0:
                done.wait(min(1, max(0, deadline - time.monotonic())))
                continue
            now = time.monotonic()
            if real:
                if now >= next_report:
                    if pending > 0 and not send(pending):
                        break
                    pending = 0.0
                    next_report = now + model.REPORT_INTERVAL
                if revive_at and now < revive_at:
                    done.wait(min(1.0, revive_at - now))
                    continue
                if revive_at:
                    revive_at = 0.0
                    model.reset_after_revive()
                    alive_until = now + model.alive_seconds()
                    print('[世界Boss] 复活，满蓝继续输出', flush=True)
                if now >= alive_until:
                    if pending > 0 and not send(pending):
                        break
                    pending = 0.0
                    revive_at = now + random.uniform(30, 33)
                    print('[世界Boss] 模拟死亡，%.0f 秒后满蓝复活' %
                          (revive_at - now), flush=True)
                    continue
                skill_id = model.choose(now)
                if skill_id is None:
                    done.wait(0.15)
                    continue
                damage, gap = model.cast(skill_id, now)
                pending += damage
                wait = min(gap, 0.6)
                if next_report > now:
                    wait = min(wait, next_report - now)
                done.wait(max(0.05, wait))
                continue
            hurt = sample_hurt(keepalive_min, keepalive_max) if idle else (
                sample_expected_hurt(expected_dps) if expected_dps is not None
                else sample_hurt(hurt_min, hurt_max))
            if not send(hurt):
                break
            done.wait(1)
        if pending > 0 and flow.game._running and (
                state['hp'] is None or state['hp'] > 0):
            send(pending)
            pending = 0.0
        print('[世界Boss] 共发送 %s 次，服务器计伤 %.2f；等待本场结算' %
              (sent, state['hit']), flush=True)
        if not done.is_set():
            done.wait(max(0, deadline - time.monotonic()))
        if not done.is_set():
            print('[世界Boss] 等待超时，本次未收到结算推送', flush=True)
        if state['finished'] is not None and flow.game._running:
            exited = flow.request('scene.worldBossHandler.exitWorldBossCopy', {})
            print('[世界Boss] 结算后退出：%s' % exited.get('code'), flush=True)
        after = _entry(flow)
        print('[世界Boss] 次数 %s→%s' %
              (count_before, (after.get('worldBoss') or {}).get('count')), flush=True)
        return bool(isinstance(state['finished'], dict)
                    and state['finished'].get('success'))
    finally:
        flow.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--slot', type=int, help='存档槽位；不指定则使用账号配置')
    parser.add_argument('--boss-id', type=int, default=960101)
    parser.add_argument('--hurt-min', type=float, default=100000)
    parser.add_argument('--hurt-max', type=float, default=500000)
    parser.add_argument('--target-percent', type=float, default=5.05)
    parser.add_argument('--max-seconds', type=int, default=0,
                        help='0=等待到服务器结束时间后60秒')
    parser.add_argument('--keepalive-min', type=float, default=0)
    parser.add_argument('--keepalive-max', type=float, default=10000)
    parser.add_argument('--room-id')
    parser.add_argument('--expected-dps', type=float, default=None,
                        help='每秒期望伤害；每秒在1/4到7/4倍之间均匀取值')
    parser.add_argument('--idle-only', action='store_true',
                        help='进房后直接挂机，每秒上报0–10000伤害')
    parser.add_argument('--no-target', action='store_true',
                        help='不以目标占比作为切换点')
    parser.add_argument('--idle-mode', action='store_true',
                        help='开启挂机伤害；有目标时达标后切换，否则立即挂机')
    parser.add_argument('--mock-damage', action='store_true',
                        help='不启用真实面板/技能模型，沿用旧随机伤害')
    parser.add_argument('--auto-boss', action='store_true',
                        help='按面板战力自动选择档位（1.2倍门槛内最高档）')
    args = parser.parse_args()
    if args.slot is not None:
        da.RECORD_INDEX = args.slot
    sys.exit(0 if run(args.boss_id, args.hurt_min, args.hurt_max,
                      args.target_percent, args.max_seconds,
                      args.keepalive_min, args.keepalive_max, args.room_id,
                      args.expected_dps, args.idle_only,
                      not args.no_target, args.idle_mode,
                      not args.mock_damage, args.auto_boss) else 1)
