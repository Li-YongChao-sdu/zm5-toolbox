"""斗宠找回并挑战。先用现有次数，再逐日整批找回；未知写结果不重发。"""
import argparse
import copy
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

from pet_arena_paid import PRESETS, checked, fingerprint, parse_rid
from pet_arena_recovery_data import (BEGIN, END, RECOVER, state, plan, digest,
                                     unchanged, battle_started, battle_won, recovered, redact)

ROOT = Path(__file__).resolve().parent
PASSWORD_ENV = 'ZM5_PET_RECOVERY_PASSWORD'


def read_state(flow, slot, handler='petArena'):
    info = copy.deepcopy(checked(flow.request('connector.entryHandler.entry',
                                {'index': slot, 'userAgent': flow.user_agent}))['info'])
    home = checked(flow.request('scene.%sHandler.getArenaInfo'%handler, {}))
    user = checked(flow.request('connector.roleHandler.getUserInfo', {}))['user']
    return state(info, user, home, handler=handler)


def authorize(account, slot, cost):
    from category_spend_guard import context, matched
    ctx = context() or {}
    permission = (ctx.get('permissions') or {}).get('daily') or {}
    if (not matched('daily', permission.get('bits')) or
            str(ctx.get('uid')) != str(account['uid']) or ctx.get('slot') != slot or
            int(permission.get('budget', 0)) < max(1, cost)):
        raise ValueError('请开启本页独立点券权限，并设置足够的本次预算')


def unfinished(folder, uid, slot):
    for path in sorted(folder.glob('*.json'), reverse=True):
        r = json.loads(path.read_text(encoding='utf-8'))
        if r.get('uid') == uid and r.get('slot') == slot and r.get('status') != 'complete':
            return path, r
    return None, None


def remaining_cost(r, current=None):
    cost = sum(d['cost'] for d in r['plan']['days'] if d['day'] not in r['recovered_days'])
    pending = r.get('pending')
    if current is not None and pending and pending['kind'] == 'recover':
        try:
            recovered(pending['before'], current, pending['batch'])
        except ValueError:
            pass
        else:
            cost -= pending['batch']['cost']
    return cost


class Job:
    def __init__(self, report, path, flow, read, password='', sleep=time.sleep,
                 clock=time.time, log=print, check_target=None):
        self.r, self.path, self.flow, self.read = report, Path(path), flow, read
        self.password, self.sleep, self.clock, self.log = password, sleep, clock, log
        self.check_target = check_target or (lambda: None)

    def save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(redact(self.r), ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(self.path)

    def request(self, route, params, pending):
        self.r['pending'] = copy.deepcopy(pending)
        row = {'route': route, 'params': redact(params), 'phase': 'pending'}
        self.r['requests'].append(row)
        self.save()  # 在发包前落盘；崩溃也不会把未知请求当作未发送。
        try:
            reply = self.flow.request(route, params)
        except Exception as exc:
            row.update(phase='uncertain',error=type(exc).__name__)
            self.save()
            raise
        row.update(phase='returned', reply=redact(reply))
        self.save()
        return checked(reply)

    def finish_win(self, before, current):
        battle_won(before, current)
        self.r['completed'] += 1
        self.r.update(pending=None, latest=copy.deepcopy(current), last_end=self.clock())
        self.save()
        if self.r['completed'] % 10 == 0:
            self.log('[次数找回] 已完成%s局｜奖励币%s｜点券%s' %
                     (self.r['completed'], current['money'], current['ticket']))

    def settle(self, before):
        self.sleep(self.r['battle_wait'])
        self.request(END.replace('petArena',self.r.get('handler','petArena')), {'targetId': self.r['target'], 'win': 1},
                     {'kind': 'end', 'before': before})
        current = self.read()
        self.finish_win(before, current)
        return current

    def reconcile(self, current):
        pending = self.r.get('pending')
        if not pending:
            unchanged(self.r['latest'], current)
            return current
        if pending.get('blocked'):
            raise ValueError('开局对手不符，需人工核查，不能自动补结算')
        before = pending['before']
        last_reply = self.r['requests'][-1].get('reply') if self.r['requests'] else None
        if (pending['kind'] in ('begin', 'recover') and isinstance(last_reply, dict)
                and (last_reply.get('code') != 200 or last_reply.get('error'))):
            # 明确拒绝且状态完全未变，只有用户再次确认继续后才允许新请求。
            unchanged(before, current)
            self.r.update(pending=None, latest=copy.deepcopy(current))
            self.save()
            return current
        if pending['kind'] == 'recover':
            recovered(before, current, pending['batch'])
            self.r['recovered_days'].append(pending['batch']['day'])
            self.r['spent'] += pending['batch']['cost']
            self.r.update(pending=None, latest=copy.deepcopy(current))
            self.save()
            return current
        if pending['kind'] == 'end':
            # 已发过结算，只认可服务器到账；不把未到账视为可再次结算。
            self.finish_win(before, current)
            return current
        if pending['kind'] == 'begin':
            battle_started(before, current)
            # 此任务从未发过end，允许补发第一次结算，禁止重复begin。
            return self.settle(before)
        raise ValueError('未知断点类型，停止')

    def execute(self, current):
        r = self.r
        current = self.reconcile(current)
        self.check_target()
        r['status'] = 'running'
        self.save()
        while True:
            # 每次写操作前读回完整计数，阻止跨日、期次切换或其它窗口干扰。
            fresh = self.read()
            unchanged(current, fresh)
            current = fresh
            if current['remaining']:
                gap = self.r.get('last_end')
                if gap is not None:
                    self.sleep(max(0, r['round_wait'] - (self.clock() - gap)))
                self.check_target()
                before = copy.deepcopy(current)
                reply = self.request(BEGIN.replace('petArena',r.get('handler','petArena')), {'targetId': r['target']},
                                     {'kind': 'begin', 'before': before})
                actual = ((reply.get('data') or {}).get('rid') or
                          (reply.get('userData') or {}).get('rid') or reply.get('rid'))
                if actual and actual != r['target']:
                    self.r['pending']['blocked'] = True
                    self.save()
                    raise ValueError('开局返回对手与确认目标不同')
                # 确认只消耗一次挑战机会，点券和其它资源未变化。
                battle_started(before, self.read())
                current = self.settle(before)
                continue
            batch = next((d for d in r['plan']['days'] if d['day'] not in r['recovered_days']), None)
            if batch is None:
                if r['completed'] != r['plan']['rounds']:
                    raise ValueError('累计完成场数与最初确认的计划不符')
                r.update(status='complete', latest=current)
                self.save()
                self.log('[次数找回] 完成%s局｜找回%s日｜花费%s点券｜奖励币增加%s' %
                         (r['completed'], len(r['recovered_days']), r['spent'], current['money']-r['initial']['money']))
                return
            latest = plan(current, str(batch['day']))['days']
            if latest != [batch] or current['ticket'] < batch['cost']:
                raise ValueError('找回批次数量、价格或余额已变化，请重新核查')
            self.flow._pet_recovery_quote = {'state': copy.deepcopy(current), 'batch': copy.deepcopy(batch)}
            try:
                self.request(RECOVER.replace('petArena',r.get('handler','petArena')), {'day': batch['day'], 'password': self.password},
                             {'kind': 'recover', 'before': current, 'batch': batch})
            finally:
                self.flow._pet_recovery_quote = None
            after = self.read()
            recovered(current, after, batch)
            r['recovered_days'].append(batch['day'])
            r['spent'] += batch['cost']
            r.update(pending=None, latest=copy.deepcopy(after))
            self.save()
            self.log('[次数找回] 周%s已找回%s次，扣%s点券，开始挑战' %
                     (batch['day'], batch['count'], batch['cost']))
            current = after


def main():
    from teacher_trial import connect
    from arena_targets import detail
    p = argparse.ArgumentParser()
    p.add_argument('--handler',choices=('arena','petArena'),default='petArena')
    p.add_argument('--action', choices=('query', 'run', 'resume'), default='query')
    p.add_argument('--target', type=parse_rid, default=PRESETS['默认对手'])
    p.add_argument('--scope', default='all')
    p.add_argument('--account'); p.add_argument('--slot', type=int); p.add_argument('--quote')
    p.add_argument('--battle-wait', type=float, default=2)
    p.add_argument('--round-wait', type=float, default=8)
    args = p.parse_args()
    password = os.environ.pop(PASSWORD_ENV, '')
    flow = job = None
    try:
        account = json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
        name, slot, uid = str(account.get('username', '')), int(account['record_index']), str(account['uid'])
        if args.action != 'query' and (args.account != name or args.slot != slot):
            raise ValueError('账号或槽位已改变，请重新查询')
        if not all(math.isfinite(v) and low <= v <= 3600 for v, low in
                   ((args.battle_wait, 2), (args.round_wait, 8))):
            raise ValueError('局内最低2秒、局间最低8秒，最长3600秒')
        flow, _ = connect(account, slot)
        current = read_state(flow, slot, args.handler)
        if current['uid'] != uid or current['rid'] == args.target:
            raise ValueError('实际出战身份不符或目标为自身')
        target_fp = fingerprint(detail(flow, args.handler, args.target))
        current_plan = plan(current, args.scope)
        folder = ROOT/('arena_recovery_reports' if args.handler=='arena' else 'pet_arena_recovery_reports')
        old_path, old = unfinished(folder, uid, slot)
        need = remaining_cost(old, current) if old else current_plan['cost']
        data = dict(handler=args.handler, account=name, slot=slot, target=args.target, scope=args.scope,
                    target_label=next((k for k, v in PRESETS.items() if v == args.target), '自定义对手'),
                    state=current, plan=current_plan, quote=digest(current, current_plan, target_fp),
                    resume=dict(completed=old['completed'], rounds=old['plan']['rounds'], cost=need,
                                target=old['target'], scope=old['plan']['scope']) if old else None)
        print('__PET_ARENA_RECOVERY_STATE__'+json.dumps(data, ensure_ascii=False), flush=True)
        if args.action == 'query':
            return
        if args.quote != data['quote']:
            raise ValueError('计数、余额、对手或报价已变化，请重新查询确认')
        if args.action == 'run':
            if old:
                raise ValueError('该存档存在未完成找回任务，请核查并继续，不能另开任务')
            if not current_plan['days']:
                raise ValueError('所选历史日没有可找回次数，不开局、不扣费')
            r = dict(handler=args.handler, uid=uid, slot=slot, target=args.target, target_fp=target_fp, plan=current_plan,
                     initial=current, latest=current, requests=[], pending=None, completed=0,
                     spent=0, recovered_days=[], battle_wait=args.battle_wait,
                     round_wait=args.round_wait, status='prepared')
            path = folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
        else:
            if not old or old['target'] != args.target or old['plan']['scope'] != args.scope:
                raise ValueError('没有匹配当前对手和历史日选择的断点')
            if old['target_fp'] != target_fp or any(old['initial'][k] != current[k]
                    for k in ('uid', 'rid', 'date', 'reset', 'period')):
                raise ValueError('存档、日期、期次或对手阵容变化，不自动续打')
            r, path = old, old_path
            r.update(battle_wait=args.battle_wait, round_wait=args.round_wait)
        authorize(account, slot, need)
        if current['ticket'] < need:
            raise ValueError('当前点券不足已确认的剩余找回费用')
        # 空密码也允许发送：部分存档未设置二级密码，由服务器验证。
        def check_target():
            if fingerprint(detail(flow, args.handler, args.target)) != target_fp:
                raise ValueError('对手资料已变化，暂停等待重新核查')
        folder.mkdir(exist_ok=True)
        job = Job(r, path, flow, lambda: read_state(flow, slot, args.handler), password,
                  log=lambda text: print(text, flush=True), check_target=check_target)
        job.save()
        job.execute(current)
        print('[次数找回] 记录：'+str(path), flush=True)
    except Exception as exc:
        # 不输出网络异常正文，避免包含认证字段。
        error = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        if job:
            job.r.update(status='paused', error=error)
            job.save()
        print('[次数找回] 已停止，未盲目重发：'+error, flush=True)
    finally:
        password = ''
        if flow:
            flow.disconnect()


if __name__ == '__main__':
    main()
