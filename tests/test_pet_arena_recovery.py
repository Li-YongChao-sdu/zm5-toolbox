"""斗宠找回离线回归：整批计价、逐局计数、未知请求恢复和GUI绑定。"""
import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
import pet_arena_recovery_data as data
import pet_arena_recovery as worker
import category_spend_guard as guard


def initial():
    return dict(uid='100', rid='100_r9', date='2026-11-06', day=5, reset=123, period=2,
                week={'1': 5, '2': 5, '5': 5}, limits=[10, 5, 5, 5, 5, 10, 10],
                used=5, limit=10, remaining=5, money=10, arenaMoney=30,
                ticket=1000, yuanbao=77, wins=0)


class Flow:
    def __init__(self, s=None, fail=None):
        self.s = copy.deepcopy(s or initial())
        self.calls = []; self.fail = fail; self.failed = False

    def request(self, route, params):
        self.calls.append((route, copy.deepcopy(params)))
        s = self.s
        if route == data.BEGIN:
            s['used'] += 1; s['remaining'] -= 1
            s['week'][str(s['day'])] = s['used']
        elif route == data.END:
            s['wins'] += 1; s['money'] += 100 + s['wins']  # 每局奖励不固定。
        elif route == data.RECOVER:
            batch = data.plan(s, str(params['day']), 20)['days'][0]
            s['week'][str(batch['day'])] = s['limits'][batch['day']]
            s['ticket'] -= batch['cost']; s['used'] -= batch['count']
            s['remaining'] += batch['count']; s['week'][str(s['day'])] = s['used']
        else:
            raise AssertionError('不允许未知路由：'+route)
        if route == self.fail and not self.failed:
            self.failed = True
            raise TimeoutError('simulated lost reply')
        return {'code': 200}


def report(s):
    return dict(uid=s['uid'], slot=6, target='200_r3', target_fp='test',
                plan=data.plan(s, 'all', 20), initial=copy.deepcopy(s), latest=copy.deepcopy(s),
                requests=[], pending=None, completed=0, spent=0, recovered_days=[],
                battle_wait=2, round_wait=8, status='prepared')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'job.json'
        self.price = patch.object(data, 'unit_price', return_value=20)
        self.price.start(); self.addCleanup(self.price.stop)

    def make_job(self, flow, r=None):
        return worker.Job(r or report(flow.s), self.path, flow,
                          lambda: copy.deepcopy(flow.s), 'private-password', sleep=lambda _: None,
                          log=lambda _: None)

    def test_plan_quotes_missing_days_and_current_separately(self):
        p = data.plan(initial(), price=20)
        self.assertEqual(p['days'], [{'day':3,'count':5,'cost':100}, {'day':4,'count':5,'cost':100}])
        self.assertEqual((p['cost'], p['rounds'], p['existing']), (200, 15, 5))

    def test_never_recovers_today_or_future(self):
        for day in ('0','5','6','7','bad'):
            with self.subTest(day=day), self.assertRaises(ValueError):
                data.plan(initial(), day, 20)

    def test_sunday_uses_index_zero_but_recovers_mon_to_sat(self):
        s = initial(); s.update(day=0,used=10,remaining=0)
        s['week']['0'] = 10
        p = data.plan(s, price=20)
        self.assertEqual([d['day'] for d in p['days']], [3,4,5,6])
        self.assertNotIn(0, [d['day'] for d in p['days']])

    def test_already_consumed_chance_is_not_refundable(self):
        s = initial(); s['week'].update({'3':5,'4':5,'5':10}); s.update(used=10,remaining=0)
        self.assertEqual(data.plan(s, price=20)['cost'], 0)

    def test_full_run_uses_free_begin_and_recovers_each_day_once(self):
        flow = Flow(); job = self.make_job(flow)
        with patch.object(worker.time, 'sleep', side_effect=AssertionError('real sleep')):
            job.execute(copy.deepcopy(flow.s))
        self.assertEqual(job.r['status'], 'complete')
        self.assertEqual((job.r['completed'], job.r['spent'], flow.s['ticket']), (15,200,800))
        routes = [r for r, p in flow.calls]
        self.assertEqual(routes.count(data.BEGIN), 15)
        self.assertEqual(routes.count(data.END), 15)
        self.assertEqual(routes.count(data.RECOVER), 2)
        self.assertFalse(any('WithTicket' in r for r in routes))
        self.assertEqual(routes[:10], [data.BEGIN,data.END]*5)
        self.assertNotIn('private-password', self.path.read_text(encoding='utf8'))
        self.assertEqual(flow.s['yuanbao'], 77)

    def test_begin_reply_lost_resumes_first_end_without_second_begin(self):
        flow = Flow(fail=data.BEGIN); job = self.make_job(flow)
        with self.assertRaises(TimeoutError): job.execute(copy.deepcopy(flow.s))
        job = self.make_job(flow, json.loads(self.path.read_text(encoding='utf8')))
        job.execute(copy.deepcopy(flow.s))
        self.assertEqual(sum(r==data.BEGIN for r,p in flow.calls),15)
        self.assertEqual(sum(r==data.END for r,p in flow.calls),15)

    def test_end_reply_lost_does_not_duplicate_settlement(self):
        flow = Flow(fail=data.END); job = self.make_job(flow)
        with self.assertRaises(TimeoutError): job.execute(copy.deepcopy(flow.s))
        self.make_job(flow, json.loads(self.path.read_text(encoding='utf8'))).execute(copy.deepcopy(flow.s))
        self.assertEqual(sum(r==data.END for r,p in flow.calls),15)

    def test_recovery_reply_lost_does_not_charge_again(self):
        flow = Flow(fail=data.RECOVER); job = self.make_job(flow)
        with self.assertRaises(TimeoutError): job.execute(copy.deepcopy(flow.s))
        r = json.loads(self.path.read_text(encoding='utf8'))
        self.assertEqual(worker.remaining_cost(r,flow.s),100)
        resumed = self.make_job(flow,r); resumed.execute(copy.deepcopy(flow.s))
        self.assertEqual(resumed.r['spent'],200)
        self.assertEqual(sum(r==data.RECOVER for r,p in flow.calls),2)

    def test_unknown_charge_without_proof_stops_without_retry(self):
        flow = Flow(); r = report(flow.s)
        r['pending'] = {'kind':'recover','before':copy.deepcopy(flow.s),'batch':r['plan']['days'][0]}
        job = self.make_job(flow,r)
        with self.assertRaises(ValueError):job.execute(copy.deepcopy(flow.s))
        self.assertEqual(flow.calls,[])

    def test_unknown_settlement_not_credited_is_not_repeated(self):
        flow = Flow(); before = copy.deepcopy(flow.s)
        flow.request(data.BEGIN, {'targetId':'200_r3'})
        r = report(before); r['pending']={'kind':'end','before':before}
        with self.assertRaises(ValueError):self.make_job(flow,r).execute(copy.deepcopy(flow.s))
        self.assertEqual(len(flow.calls),1)

    def test_external_money_or_period_change_stops_before_begin(self):
        for key in ('date','period','money','ticket','rid'):
            flow = Flow(); job = self.make_job(flow)
            flow.s[key] = str(flow.s[key])+'changed'
            with self.subTest(key=key), self.assertRaises(ValueError):job.execute(copy.deepcopy(flow.s))
            self.assertEqual(flow.calls,[])

    def test_between_matches_gap_includes_recovery_batch_boundary(self):
        flow = Flow(); waits = []; clock = [0]
        def sleep(n):waits.append(n);clock[0]+=n
        job = self.make_job(flow);job.sleep=sleep;job.clock=lambda:clock[0]
        job.execute(copy.deepcopy(flow.s))
        self.assertEqual(waits.count(2),15)
        self.assertEqual(waits.count(8),14)

    def test_wrong_actual_opponent_cannot_resume_settlement(self):
        flow = Flow(); r = report(flow.s)
        r['pending']={'kind':'begin','before':copy.deepcopy(flow.s),'blocked':True}
        with self.assertRaises(ValueError):self.make_job(flow,r).execute(copy.deepcopy(flow.s))
        self.assertEqual(flow.calls,[])

    def test_authorization_is_bound_to_uid_slot_budget_and_101(self):
        good={'token':'test','uid':'100','slot':6,'permissions':{'daily':{'bits':'101','budget':200}}}
        with patch.object(guard,'context',return_value=good):worker.authorize({'uid':'100'},6,200)
        for mutate in (lambda x:x.update(uid='101'),lambda x:x.update(slot=7),
                       lambda x:x['permissions']['daily'].update(bits='001'),
                       lambda x:x['permissions']['daily'].update(budget=199)):
            ctx=copy.deepcopy(good);mutate(ctx)
            with patch.object(guard,'context',return_value=ctx),self.assertRaises(ValueError):
                worker.authorize({'uid':'100'},6,200)

    def test_quote_fingerprint_rejects_stale_balance_or_target(self):
        s=initial();p=data.plan(s,price=20);q=data.digest(s,p,'target')
        s['ticket']-=1
        self.assertNotEqual(q,data.digest(s,p,'target'))
        self.assertNotEqual(q,data.digest(initial(),p,'changed'))

    def test_guard_dynamic_whole_day_quote_and_redacted_audit(self):
        s=initial();s.update(used=10,remaining=0);s['week']['5']=10
        info={'uid':s['uid'],'_id':s['rid'],'everyDaySetting':{},
              'everyWeekSetting':{'resetTime':s['reset'],'petArenaWinNumCurr':s['wins'],
                                  'petArenaSetting':{'week':s['week']}},
              'petArenaMoney':s['money'],'arenaMoney':s['arenaMoney']}
        home={'self':{'rid':s['rid'],'rank':2},'index':s['period'],
              'jjcChallengeNum':';'.join(map(str,s['limits']))}
        user={k:s[k] for k in ('ticket','yuanbao')}
        def raw(_flow,route,_params):
            if route.endswith('getUserInfo'):return {'code':200,'user':copy.deepcopy(user)}
            if route.endswith('entry'):return {'code':200,'info':copy.deepcopy(info)}
            return dict(code=200,**copy.deepcopy(home))
        ctx={'token':'audit-test','uid':'100','slot':6,'permissions':{'daily':{'bits':'101','budget':100}}}
        f=SimpleNamespace(uid='100',_category_slot=6,user_agent='test',
                          _pet_recovery_quote={'state':s,'batch':{'day':3,'count':5,'cost':100}})
        at=datetime(2026,11,6,12,tzinfo=data.TZ)
        with patch.object(guard,'ROOT',Path(self.tmp.name)),patch.object(guard,'context',return_value=ctx),\
             patch.object(guard,'raw',side_effect=raw),patch.object(data,'now',return_value=at):
            ctx['permissions']['daily']['budget']=99
            with self.assertRaises(RuntimeError):guard.before(f,data.RECOVER,{'day':3})
            ctx['permissions']['daily']['budget']=100
            f._pet_recovery_quote['batch']['cost']=20
            with self.assertRaises(RuntimeError):guard.before(f,data.RECOVER,{'day':3})
            f._pet_recovery_quote['batch']['cost']=100
            q=guard.before(f,data.RECOVER,{'day':3,'password':'private-password'})
            self.assertEqual(q['cost'],100)
            self.assertNotIn('private-password',Path(q['_path']).read_text(encoding='utf8'))
            user['ticket']-=100
            info['everyWeekSetting']['petArenaSetting']['week']=dict(s['week'],**{'3':5,'5':5})
            guard.after(f,data.RECOVER,{}, {'code':200},q)
            self.assertEqual(q['actual_cost'],100)
        guard._spent.pop(('audit-test','daily'),None)


class RecoveryUiTests(unittest.TestCase):
    def test_nested_visibility_and_secret_transport(self):
        import tkinter as tk
        from tkinter import ttk
        import pet_arena_paid_ui as ui
        import pet_arena_recovery_ui as recovery_ui
        from category_spend_ui import CategoryPermissions
        root=tk.Tk();root.withdraw();self.addCleanup(root.destroy)
        calls=[]
        app=SimpleNamespace(root=root,running=False,_save_selected_slot=lambda:True,
                            _launch=lambda args,**kw:calls.append((args,kw)))
        app.cmb_slot=ttk.Combobox(root,values=['6','7']);app.cmb_slot.set('6')
        app.spend_permissions=CategoryPermissions(app)
        panel=ui.PaidPetArenaPanel(app,root);child=panel.recovery
        root.update_idletasks()
        self.assertEqual(child.box.winfo_manager(),'pack')
        panel.kind.set('点券竞技场');self.assertEqual(child.box.winfo_manager(),'pack')
        panel.kind.set('点券斗宠大会')
        self.assertEqual(tuple(panel.target_combo['values']),('默认对手',))
        app.spend_permissions.variables['dungeons'][2].set(True)
        self.assertIn('自定义RID',panel.target_combo['values'])
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'account.local.json').write_text(json.dumps({'username':'tester'}),encoding='utf8')
            s=initial();p=data.plan(s,price=20)
            d=dict(account='tester',slot=6,target=panel.selected_rid(),scope='all',
                   target_label='默认对手',state=s,plan=p,quote='quote',resume=None)
            with patch.object(recovery_ui,'ROOT',Path(folder)),patch.object(recovery_ui.messagebox,'askyesno',return_value=True),\
                 patch.object(recovery_ui.messagebox,'showerror') as error:
                child.render(d)
                self.assertIn('200点券',child.summary.get())
                for v,b in zip(app.spend_permissions.variables['daily'],(True,False,True)):v.set(b)
                app.spend_permissions.budgets['daily'].set('200')
                child.password.set('private-password');child.launch('run')
                self.assertFalse(error.called)
                args,kw=calls[-1]
                self.assertEqual(args[args.index('--quote')+1],'quote')
                self.assertNotIn('private-password',args)
                self.assertEqual(kw['extra_env']['ZM5_PET_RECOVERY_PASSWORD'],'private-password')
                self.assertEqual(child.password.get(),'')
                child.render(d);app.cmb_slot.set('7');child.launch('run')
                self.assertTrue(error.called)
                self.assertEqual(len(calls),1)
                # 即使新账号重新查询完成，也不会复用旧账号尚未清空的密码。
                app.cmb_slot.set('6');child.password.set('old-secret')
                Path(folder,'account.local.json').write_text(json.dumps({'username':'other'}),encoding='utf8')
                changed=dict(d,account='other');child.render(changed);child.launch('run')
                self.assertEqual(child.password.get(),'')
                self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()


class ArenaRecoveryTests(unittest.TestCase):
    def test_arena_uses_own_counts_currency_and_price(self):
        at=datetime(2026,11,6,12,tzinfo=data.TZ)
        info={'uid':'100','_id':'100_r9','everyWeekSetting':{'resetTime':123,'arenaSetting':{'week':{'5':10}},'arenaWinNumCurr':3},'arenaMoney':77,'petArenaMoney':99}
        home={'self':{'rid':'100_r9','rank':1},'index':1,'jjcChallengeNum':'10;5;5;5;5;10;10'}
        s=data.state(info,{'ticket':1000,'yuanbao':8},home,at,handler='arena')
        self.assertEqual((s['money'],s['arenaMoney'],s['wins'],s['remaining']),(77,99,3,0))
        with patch.object(data,'unit_price',return_value=20) as price:
            data.plan(s);price.assert_called_once_with('arena')
    def test_arena_job_sends_only_arena_routes(self):
        class ArenaFlow(Flow):
            def request(self,route,params):
                if '.petArenaHandler.' in route:raise AssertionError('wrong handler')
                return super().request(route.replace('.arenaHandler.','.petArenaHandler.'),params)
        flow=ArenaFlow();r=report(flow.s);r['handler']='arena'
        with tempfile.TemporaryDirectory() as folder,patch.object(data,'unit_price',return_value=20):
            worker.Job(r,Path(folder)/'job.json',flow,lambda:copy.deepcopy(flow.s),sleep=lambda _:None,log=lambda _:None).execute(copy.deepcopy(flow.s))
        self.assertEqual(r['status'],'complete');self.assertEqual(r['spent'],200)
    def test_arena_buy_has_dynamic_budget_quote(self):
        self.assertEqual(guard.quote('scene.arenaHandler.buyArenaCount',{'day':2})['kind'],'pet_recovery')
