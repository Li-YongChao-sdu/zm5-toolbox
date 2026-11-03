"""九灵元圣：按最大血量的固定分钟占比控制联盟 Boss 伤害。"""

import argparse
import os
import json
import random
import sys
import threading
import time
from pathlib import Path

def _connect():
    from main_farm import _connect as connect
    return connect()


def _entry(flow):
    from main_farm import _entry as entry
    return entry(flow)


CATALOG = json.loads((Path(__file__).parent / "boss_catalog.json").read_text(encoding="utf-8"))
LEVELS = {row["level"]: row for row in CATALOG["union"]}


def damage_per_second(hp_max, percent_per_minute=0.2):
    return hp_max * percent_per_minute / 100 / 60


def sample_expected_hurt(expected_dps):
    if expected_dps <= 0:
        raise ValueError("每秒期望伤害须大于0")
    return random.uniform(expected_dps / 4, expected_dps * 7 / 4)

def finish_window_rate(hp, seconds_left, participants):
    if hp < 0 or participants < 1:
        raise ValueError('无效的剩余血量或参与人数')
    return hp / max(1.0, seconds_left) / participants

def paced_finish_rate(hp, hp_max, seconds_left, duration, participants, power=2):
    """只补足下一秒计划血线；全场进度超前时保持0伤害。"""
    elapsed=max(0.0,duration-seconds_left)
    progress=min(1.0,(elapsed+1)/duration)**power
    wanted_hp=hp_max*(1-progress)
    return max(0.0,hp-wanted_hp)/max(1,participants)


def minute_packets(hp_max, percent_per_minute=0.2, interval=5):
    """随机分配一分钟的总额；12 次请求合计约为血量的 0.2%。"""
    count = round(60 / interval)
    weights = [random.uniform(0.8, 1.2) for _ in range(count)]
    total = hp_max * percent_per_minute / 100
    scale = total / sum(weights)
    amounts = [round(weight * scale, 2) for weight in weights]
    amounts[-1] = round(total - sum(amounts[:-1]), 2)
    return amounts


def run(level, percent_per_minute=0.2, max_seconds=0,
        expected_dps=None, target_percent=0.2, idle_only=False,
        attack_to_target=True, idle_mode=False, connector=None, entry=None,
        label=None, finish_at_end=False, participant_count=None, finish_margin=5,
        finish_power=1, real_damage=True):
    def log(*args, **kwargs):
        print(('[' + label + '] ') if label else '', *args, **kwargs)
    if level != 0 and level not in LEVELS:
        raise ValueError("九灵元圣仅有 1–14 阶；0 表示自动识别")
    if percent_per_minute <= 0 or percent_per_minute > 1:
        raise ValueError("每分钟伤害比例须在 0–1% 之间")
    if expected_dps is not None and expected_dps <= 0:
        raise ValueError("每秒期望伤害须大于0")
    if not 0 < target_percent <= 100:
        raise ValueError("目标伤害占比须在0–100%之间")
    flow = (connector or _connect)()
    state = {"hit": 0.0, "hp": None, "finished": None, "kicked": False, 'target_clock':None}
    done = threading.Event()
    joined = False
    try:
        def on_hit(data):
            if isinstance(data, dict) and data.get("hit") is not None:
                state["hit"] = float(data["hit"])
                log("[联盟Boss] 服务器累计伤害 %.2f" % state["hit"], flush=True)

        def on_hp(data):
            if isinstance(data, dict) and data.get("hp") is not None:
                state["hp"] = float(data["hp"])
                if finish_at_end and isinstance(data.get('endTime'),(int,float)):
                    state['target_clock'] = time.monotonic()+float(data['endTime'])/1000-finish_margin

        def on_finish(data):
            state["finished"] = data
            log("[联盟Boss] 结算推送：%s" %
                  json.dumps(data, ensure_ascii=False, default=str)[:2400], flush=True)
            done.set()

        def on_kick():
            state["kicked"] = True
            log("[联盟Boss] 服务器踢出连接", flush=True)
            done.set()

        flow.on("onBossCopySelfHit", on_hit)
        flow.on("onLeagueBossHpChange", on_hp)
        flow.on("onFinishLeagueBossCopy", on_finish)
        flow.game.set_kicked_callback(on_kick)
        info = (entry or _entry)(flow)
        league = info.get("league") or {}
        if not league.get("leagueId"):
            raise RuntimeError("当前存档未加入联盟")
        log("[联盟Boss] 联盟：%s；选择九灵元圣 %s" %
              (league.get("leagueName") or league["leagueId"],
               ("自动识别" if level == 0 else "%s 阶" % level)), flush=True)
        response = flow.request("league.leagueHandler.challengeBoss", {"pNum": 0})
        if not isinstance(response, dict) or response.get("code") != 200 or response.get("error"):
            raise RuntimeError("进入联盟 Boss 失败：%s" % response)
        joined = True
        dungeon_id = int(response.get("dungeonId") or 0)
        actual_level = dungeon_id - 800100
        if actual_level not in LEVELS:
            raise RuntimeError("服务器返回的关卡 %s 不是九灵元圣 1–14 阶" % dungeon_id)
        expected = LEVELS[actual_level]
        if level == 0:
            level = actual_level
            log("[联盟Boss] 服务器当前为 %s 阶" % level, flush=True)
        if dungeon_id != expected["dungeonId"]:
            raise RuntimeError("当前联盟 Boss 是关卡 %s，与配置不符" % dungeon_id)
        if level != actual_level:
            raise RuntimeError("当前联盟 Boss 是 %s 阶，与选择的 %s 阶不符" %
                               (actual_level, level))
        boss = response.get("Boss") or response.get("boss") or {}
        server_hp_max = float(boss.get("hpMax") or expected["hpMax"])
        if abs(server_hp_max - expected["hpMax"]) > 1:
            raise RuntimeError("服务器最大血量 %.0f 与配置 %.0f 不符" %
                               (server_hp_max, expected["hpMax"]))
        rate = expected_dps if expected_dps is not None else damage_per_second(server_hp_max, percent_per_minute)
        goal = server_hp_max * target_percent / 100
        model = None
        model_state = None
        if real_damage and not finish_at_end:
            try:
                from world_boss_model import WorldBossModel, _table
                monster = _table('Monster').get(str(expected['monsterId'])) or {}
                boss_data = {
                    'name': '九灵元圣',
                    'level': monster.get('level'),
                    'hpMax': server_hp_max,
                    'phyDef': monster.get('phyDef'),
                    'atk': monster.get('atk'),
                    'toughness': monster.get('toughness'),
                    'guardian': monster.get('guardian'),
                }
                model = WorldBossModel(info, 0, boss=boss_data, cd_field='cd')
                model_state = {
                    'pending': 0.0,
                    'next_report': time.monotonic() + model.REPORT_INTERVAL,
                    'alive_until': time.monotonic() + model.alive_seconds(),
                    'revive_at': 0.0,
                    'model_time': 0.0,
                }
                log('[联盟Boss] 真实模型：面板攻击 %.0f，Boss等级 %s，暴击 %.0f%%，爆伤 %.2f，预计存活 %.0f 秒' % (
                    model.panel.get('atk') or 0, model.boss_level,
                    model.crit_rate * 100, model.crit_mult, model.alive_seconds()), flush=True)
            except Exception as exc:
                model = None
                model_state = None
                log('[联盟Boss] 真实模型不可用（%s），改用每秒期望伤害' % exc, flush=True)

        def advance_model(now):
            """按真实技能/CD/蓝耗推进一秒，每 2 秒返回累计伤害。"""
            if model_state['revive_at']:
                if now < model_state['revive_at']:
                    return 0.0
                model_state['revive_at'] = 0.0
                model.reset_after_revive()
                model_state['model_time'] = 0.0
                model_state['alive_until'] = now + model.alive_seconds()
                log('[联盟Boss] 复活，满蓝继续输出', flush=True)
            if now >= model_state['alive_until']:
                amount = model_state['pending']
                model_state['pending'] = 0.0
                model_state['revive_at'] = now + random.uniform(30, 33)
                log('[联盟Boss] 模拟死亡，%.0f 秒后满蓝复活' %
                      (model_state['revive_at'] - now), flush=True)
                return amount
            limit = model_state['model_time'] + 1.0
            t = model_state['model_time']
            while t < limit:
                skill_id = model.choose(t)
                if skill_id is None:
                    t += 0.15
                    continue
                damage, gap = model.cast(skill_id, t)
                model_state['pending'] += damage
                t += max(gap, 0.15)
            model_state['model_time'] = t
            if now >= model_state['next_report']:
                amount = model_state['pending']
                model_state['pending'] = 0.0
                model_state['next_report'] = now + model.REPORT_INTERVAL
                return amount
            return 0.0
        log("[联盟Boss] 已入场；最大血量 %.0f，每秒期望 %.2f，目标累计伤害 %.0f" %
              (server_hp_max, rate, goal), flush=True)
        end_seconds = max(0, float(response.get("endTime") or 0) / 1000 - time.time())
        wait_seconds = max_seconds if max_seconds > 0 else (end_seconds + 60 if end_seconds else 1800)
        deadline = time.monotonic() + wait_seconds
        if finish_at_end:
            server_now=float(response.get('serverTime') or time.time()*1000)
            seconds_to_end=(float(response.get('endTime') or 0)-server_now)/1000
            if seconds_to_end<=finish_margin:raise RuntimeError('服务器结束时间未知或已临近，停止定时击杀测试')
            if state['target_clock'] is None:state['target_clock']=time.monotonic()+seconds_to_end-finish_margin
            schedule_duration=(float(response['endTime'])-float(response['startTime']))/1000-finish_margin
            if schedule_duration<=0:raise RuntimeError('无效的服务器战斗时长')
            if max_seconds<=0:deadline=time.monotonic()+seconds_to_end+60
            log('[定时击杀] 以服务器结束前%s秒为目标；按剩余血量和在线测试账号数分摊伤害' % finish_margin,flush=True)
        start_seconds = max(0, float(response.get("startTime") or 0) / 1000 - time.time())
        if start_seconds:
            log("[联盟Boss] 等待开战约 %.0f 秒" % start_seconds, flush=True)
            done.wait(min(start_seconds, wait_seconds))
        sent = 0
        next_tick = time.monotonic()
        idle = idle_only or (idle_mode and not attack_to_target)
        target_reached = False
        next_finish_log=0
        while time.monotonic() < deadline and not done.is_set():
            if not flow.game._running:
                log("[联盟Boss] 连接已断开", flush=True)
                break
            if state["hp"] is not None and state["hp"] <= 0:
                done.wait(min(1, max(0, deadline - time.monotonic())))
                continue
            if attack_to_target and not target_reached and state["hit"] >= goal:
                target_reached = True
                if idle_mode:
                    idle = True
                    log("[联盟Boss] 已达目标，进入挂机模式", flush=True)
                else:
                    log("[联盟Boss] 已达目标，继续按期望伤害上报", flush=True)
            if finish_at_end:
                if state['hp'] is None:
                    hurt=0
                else:
                    seconds_left=state['target_clock']-time.monotonic()
                    count=max(1,int(participant_count() if participant_count else 1))
                    control_path=os.environ.get('ZM5_UNION_CONTROL_FILE')
                    current_power=finish_power
                    if control_path:
                        try:
                            control=json.loads(Path(control_path).read_text(encoding='utf-8'))
                            candidate=float(control.get('finish_power',finish_power))
                            if 1<=candidate<=4:current_power=candidate
                        except (OSError,ValueError,TypeError):pass
                    rate=(paced_finish_rate(state['hp'],server_hp_max,seconds_left,schedule_duration,count,finish_power)
                          if current_power>1 else finish_window_rate(state['hp'],seconds_left,count))
                    hurt=(random.uniform(state['hp'],state['hp']*1.05) if seconds_left<=0
                          else min(state['hp'],sample_expected_hurt(rate)) if rate>0
                          else min(state['hp'],random.uniform(0,10000)))
                    if time.monotonic()>=next_finish_log:
                        log('[定时击杀] 剩余血量%.0f，距目标%.1f秒，测试账号%d，每秒期望%.2f' % (state['hp'],seconds_left,count,rate),flush=True)
                        next_finish_log=time.monotonic()+30
            else:
                if model and not idle:
                    hurt = advance_model(time.monotonic())
                else:
                    hurt = random.uniform(0, 10000) if idle else sample_expected_hurt(rate)
            result = flow.request("scene.leagueHandler.attackBossCopy", {"hurt": hurt})
            if not isinstance(result, dict) or result.get("code") != 200 or result.get("error"):
                log("[联盟Boss] 伤害上报停止：%s" % result, flush=True)
                break
            sent += 1
            next_tick += 1
            done.wait(max(0, min(next_tick - time.monotonic(), deadline - time.monotonic())))
        log("[联盟Boss] 已上报 %s 次，服务器计伤 %.2f；等待结算" %
              (sent, state["hit"]), flush=True)
        if not done.is_set() and flow.game._running:
            done.wait(max(0, deadline - time.monotonic()))
        if state["finished"] is None:
            log("[联盟Boss] 尚未收到结算推送", flush=True)
        if state["finished"] is not None and flow.game._running:
            exited = flow.request("scene.leagueHandler.exitLeagueCopy", {})
            log("[联盟Boss] 结算后退出：%s" % exited.get("code"), flush=True)
        return bool(isinstance(state["finished"], dict)
                    and state["finished"].get("success"))
    finally:
        if joined and state["finished"] is None and flow.game and flow.game._running:
            try:
                flow.request("scene.leagueHandler.exitLeagueCopy", {})
            except Exception:
                pass
        flow.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", type=int, default=0)
    parser.add_argument("--percent-per-minute", type=float, default=0.2)
    parser.add_argument("--max-seconds", type=int, default=0)
    parser.add_argument("--expected-dps", type=float, default=None,
                        help="每秒期望伤害；缺省按当前阶数的0.2%%/分钟计算")
    parser.add_argument("--target-percent", type=float, default=0.2)
    parser.add_argument("--idle-only", action="store_true")
    parser.add_argument("--no-target", action="store_true")
    parser.add_argument("--idle-mode", action="store_true")
    parser.add_argument("--mock-damage", action="store_true",
                        help="不启用真实面板/技能模型，沿用每分钟比例控伤")
    parser.add_argument("--batch-file", help="多账号列表文件")
    options = parser.parse_args()
    if options.batch_file:
        from union_boss_batch import run_batch
        sys.exit(0 if run_batch(options) else 1)
    sys.exit(0 if run(options.level, options.percent_per_minute,
                      options.max_seconds, options.expected_dps,
                      options.target_percent, options.idle_only,
                      not options.no_target, options.idle_mode,
                      real_damage=not options.mock_damage) else 1)
