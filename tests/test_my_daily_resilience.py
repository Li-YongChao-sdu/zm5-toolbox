"""不联网：日常失败隔离、共享连接、排序和未知消耗停止。"""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import my_daily_execution as ex
import my_daily_runner as runner
from my_daily_queue import ModuleQueue

class Raw:
    user_agent='test'
    def __init__(self):self.closed=0;self.calls=[];self.error=None;self.reply={'code':200}
    def request(self,route,data=None,*a,**kw):
        self.calls.append((route,data))
        if route=='connector.entryHandler.entry':return {'code':200,'info':{'uid':'u','_id':'u_r11'}}
        if self.error:raise self.error
        return self.reply
    def disconnect(self):self.closed+=1

class TaskTests(unittest.TestCase):
    def test_middle_failure_continues_and_liveness_is_last(self):
        seen=[]
        def execute(k):
            seen.append(k)
            if k=='bad':raise ValueError('bad setting')
        r=ex.run_tasks(['RUN_LIVENESS','good','bad','later','RUN_FLUSHOU'],execute,log=lambda s:None)
        self.assertEqual(seen,['RUN_FLUSHOU','good','bad','later','RUN_LIVENESS'])
        self.assertEqual(r['status'],'complete_with_failures');self.assertEqual(r['tasks'][2]['status'],'failed')
    def test_fatal_preserves_remaining(self):
        def execute(k):raise ex.BatchFatal('unknown result')
        r=ex.run_tasks(['a','b'],execute,log=lambda s:None)
        self.assertEqual(r['status'],'stopped');self.assertEqual(r['unexecuted'],['b'])
    def test_prepare_order(self):
        self.assertEqual(ex.ordered_tasks(['RUN_LIVENESS','x','RUN_WEEKEND_BUFF','RUN_GROWTH_BUFF','RUN_FLUSHOU']),['RUN_FLUSHOU','RUN_GROWTH_BUFF','RUN_WEEKEND_BUFF','x','RUN_LIVENESS'])
    def test_query_timeout_not_fatal(self):
        raw=Raw();raw.error=TimeoutError('read');flow=ex.TaskFlow(raw,{},'u')
        with self.assertRaises(TimeoutError):flow.request('scene.test.getInfo',{})
        self.assertFalse(flow.halted)
    def test_write_timeout_is_fatal(self):
        raw=Raw();raw.error=TimeoutError('write');flow=ex.TaskFlow(raw,{},'u')
        with self.assertRaises(ex.BatchFatal):flow.request('scene.test.claimReward',{})
        self.assertTrue(flow.halted)
    def test_known_rejection_not_fatal(self):
        raw=Raw();raw.reply={'code':500,'error':'次数已用完'};flow=ex.TaskFlow(raw,{},'u')
        flow.request('scene.test.claimReward',{});self.assertFalse(flow.halted);self.assertFalse(flow.errors);self.assertTrue(flow.skips)
    def test_paid_request_blocks_before_send(self):
        raw=Raw();flow=ex.TaskFlow(raw,{},'u')
        with self.assertRaises(ex.BatchFatal):flow.request('scene.arenaHandler.beginArenaBattleWithTicket',{})
        self.assertEqual(raw.calls,[])
    def test_invalid_write_reply_stops(self):
        raw=Raw();raw.reply=None;flow=ex.TaskFlow(raw,{},'u')
        with self.assertRaises(ex.BatchFatal):flow.request('scene.test.claimReward',{})
    def test_identity_changed_stops(self):
        raw=Raw();flow=ex.TaskFlow(raw,{},'other')
        with self.assertRaises(ex.BatchFatal):flow.request('connector.entryHandler.entry',{'index':6})
    def test_disconnect_is_deferred(self):
        raw=Raw();flow=ex.TaskFlow(raw,{},'u');flow.disconnect();self.assertEqual(raw.closed,0);flow.close();self.assertEqual(raw.closed,1)
    def test_runner_reuses_login_and_continues_after_failed_task(self):
        raw=Raw();logins=[];seen=[]
        da=SimpleNamespace(UID='u',RECORD_INDEX=6,RUN_FIRST=False,RUN_BAD=False,RUN_LAST=False,RUN_MY_DAILY_FUN=False,MAIN_CUSTOM_MID=999)
        def login():logins.append(1);return raw,{}
        da.login=login
        def main():
            f,i=da.login();key=next(k for k in ['RUN_FIRST','RUN_BAD','RUN_LAST'] if getattr(da,k))
            seen.append(key);self.assertEqual(da.MAIN_CUSTOM_MID,0)
            if key=='RUN_BAD':raise ValueError('local validation failed before sending')
            f.request('scene.test.claimReward',{});f.disconnect()
        da.main=main;catalog=[(k,k,False,False,'') for k in ['RUN_FIRST','RUN_BAD','RUN_LAST']]
        with tempfile.TemporaryDirectory() as folder,patch.object(ex,'load_shops',return_value={}),patch.object(runner,'load_shops',return_value={}),patch('activity_availability.disabled_reason',return_value=None):
            r=runner.run_selected(da,['RUN_FIRST','RUN_BAD','RUN_LAST'],catalog,report_dir=folder)
        self.assertEqual(seen,['RUN_FIRST','RUN_BAD','RUN_LAST']);self.assertEqual(len(logins),1);self.assertEqual(raw.closed,1);self.assertEqual(r['status'],'complete_with_failures')

class QueueTests(unittest.TestCase):
    def make(self,code):
        calls=[];logs=[];root=SimpleNamespace(after=lambda ms,fn:calls.append(fn),after_idle=lambda fn:calls.append(fn))
        app=SimpleNamespace(root=root,running=False,execution_gate=SimpleNamespace(busy=False),_my_daily_result=code,_append_log=logs.append)
        q=ModuleQueue.__new__(ModuleQueue);q.app=app;q.active=True;q.pending=[('next',lambda:None)];q.results=[];q.current_label='current';q.binding=('u','name','6');q.identity=lambda:q.binding;app._personal_queue=q
        return q,calls,logs
    def test_failed_process_continues(self):
        q,calls,_=self.make(1);q.poll();self.assertTrue(q.active);self.assertTrue(calls);self.assertEqual(q.results[0]['status'],'failed')
    def test_failed_start_continues(self):
        q,calls,_=self.make(0);q.pending=[('bad',lambda:(_ for _ in ()).throw(ValueError('setting'))),('next',lambda:None)];q.next()
        self.assertTrue(q.active);self.assertEqual(len(q.pending),1);self.assertEqual(q.results[0]['status'],'failed');self.assertTrue(calls)
    def test_not_started_is_skip(self):
        q,calls,_=self.make(0);q.next();self.assertTrue(q.active);self.assertEqual(q.results[0]['status'],'skipped');self.assertTrue(calls)
    def test_fatal_process_stops(self):
        q,calls,_=self.make(20);q.poll();self.assertFalse(q.active);self.assertEqual(q.unexecuted,['next']);self.assertFalse(calls)
    def test_skipped_process_continues(self):
        q,calls,_=self.make(3);q.poll();self.assertTrue(q.active);self.assertEqual(q.results[0]['status'],'skipped');self.assertTrue(calls)
    def test_missing_process_result_stops(self):
        q,calls,_=self.make(None);q.poll();self.assertFalse(q.active)
    def test_identity_change_stops(self):
        q,calls,_=self.make(0);q.identity=lambda:('other','name','6');q.poll();self.assertFalse(q.active)

class ScriptTests(unittest.TestCase):
    def run_script(self,error=None,reply=...):
        import my_daily_script as script
        from pypomelo.flow import GameLoginFlow
        def original(flow,route,params=None,*a,**kw):
            if error:raise error
            return {'code':500,'error':'明确业务拒绝'} if reply is ... else reply
        def fake_run(*a,**kw):GameLoginFlow.__new__(GameLoginFlow).request('scene.test.claimReward',{})
        argv=['wrapper',str(script.ROOT/'dummy_test_module.py')]
        with patch.object(GameLoginFlow,'request',original),patch.object(script.runpy,'run_path',side_effect=fake_run),patch.object(sys,'argv',argv),patch.object(ex,'load_shops',return_value={}):
            with self.assertRaises(SystemExit) as caught:script.main()
        return caught.exception.code
    def test_known_rejection_exit_is_ordinary(self):self.assertEqual(self.run_script(),1)
    def test_write_timeout_exit_is_fatal(self):self.assertEqual(self.run_script(TimeoutError('unknown')),20)
    def test_expected_skip_is_not_failure(self):self.assertEqual(self.run_script(reply={'code':500,'error':'该奖励已领取'}),3)
    def test_invalid_mutation_reply_is_fatal(self):self.assertEqual(self.run_script(reply=None),20)


class RunnerBoundaryTests(unittest.TestCase):
    def run_case(self,keys,login,action):
        da=SimpleNamespace(UID='u',RECORD_INDEX=6,login=login,RUN_MY_DAILY_FUN=False)
        for key in keys:setattr(da,key,False)
        da.main=lambda:action(da)
        tasks=[(k,k,False,False,'') for k in keys]
        with tempfile.TemporaryDirectory() as folder,patch.object(runner,'load_shops',return_value={}),patch('activity_availability.disabled_reason',return_value=None):
            return runner.run_selected(da,keys,tasks,report_dir=folder)
    def test_read_refresh_reconnects_once(self):
        class ReadFailure(Raw):
            def request(self,route,data=None,*a,**kw):raise TimeoutError('read failed')
        bad,good=ReadFailure(),Raw();calls=[]
        def login():
            calls.append(1);return (bad if len(calls)==1 else good),{}
        def action(da):
            f,i=da.login();f.request('scene.test.claimReward',{});f.disconnect()
        result=self.run_case(['RUN_TEST'],login,action)
        self.assertEqual(result['status'],'complete');self.assertEqual(len(calls),2);self.assertEqual(bad.closed,1);self.assertEqual(good.closed,1)
    def test_login_systemexit_is_fatal(self):
        def login():raise SystemExit('login failed')
        result=self.run_case(['RUN_TEST','RUN_LATER'],login,lambda da:da.login())
        self.assertEqual(result['status'],'stopped');self.assertEqual(result['unexecuted'],['RUN_LATER'])
    def test_internal_logged_failure_is_not_success(self):
        raw=Raw()
        def action(da):
            f,i=da.login();print('[测试] 操作异常：已停止本项');f.disconnect()
        result=self.run_case(['RUN_TEST'],lambda:(raw,{}),action)
        self.assertEqual(result['tasks'][0]['status'],'failed')
    def test_reconnect_cannot_change_actual_rid(self):
        class LaterFailure(Raw):
            def __init__(self):super().__init__();self.entries=0
            def request(self,route,data=None,*a,**kw):
                if route=='connector.entryHandler.entry':
                    self.entries+=1
                    if self.entries>1:raise TimeoutError('read failed')
                return super().request(route,data,*a,**kw)
        class OtherRecord(Raw):
            def request(self,route,data=None,*a,**kw):return {'code':200,'info':{'uid':'u','_id':'u_r99'}}
        first,second=LaterFailure(),OtherRecord();calls=[]
        def login():calls.append(1);return (first if len(calls)==1 else second),{}
        def action(da):f,i=da.login();f.request('scene.test.claimReward',{});f.disconnect()
        result=self.run_case(['RUN_FIRST','RUN_NEXT','RUN_LAST'],login,action)
        self.assertEqual(result['status'],'stopped');self.assertEqual(result['tasks'][-1]['status'],'fatal');self.assertEqual(result['unexecuted'],['RUN_LAST'])


class FunPlanIsolationTests(unittest.TestCase):
    def test_one_missing_setting_keeps_other_plan(self):
        from my_daily_catalog import build_plan,prepare_plan
        def build(labels,account,slot):
            if labels==['幻兽喂养']:raise ValueError('未选择幻兽')
            return {'uid':'u','slot':6,'jobs':[{'label':'黑市灵魂日常','kind':'black','args':{}}]}
        app=SimpleNamespace(fun_batch_page=SimpleNamespace(build=build))
        keys=['RUN_FUN_BLACK_MARKET','RUN_FUN_FAIRY_FEED']
        plan=build_plan(app,keys,{'uid':'u'},6);jobs,errors=prepare_plan(keys,plan,'u',6)
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['kind'],'black');self.assertIn('RUN_FUN_FAIRY_FEED',errors)
    def test_other_account_plan_is_not_used(self):
        from my_daily_catalog import prepare_plan
        jobs,errors=prepare_plan(['RUN_FUN_BLACK_MARKET'],{'uid':'other','slot':6,'jobs':[{'label':'黑市灵魂日常','kind':'black','args':{}}]},'u',6)
        self.assertEqual(jobs,[]);self.assertIn('RUN_FUN_BLACK_MARKET',errors)

if __name__=='__main__':unittest.main()


class MysteryGuardTests(unittest.TestCase):
    def flow(self):
        raw=Raw();raw.reply={'code':200,'mysteryShop':{'stall':{'1':101077}}}
        return raw,ex.TaskFlow(raw,{},'u')
    def test_without_query_denied(self):
        raw,f=self.flow()
        with self.assertRaises(ex.BatchFatal):f.request('scene.shopHandler.buyMysteryShop',{'stallNum':1})
        self.assertFalse(raw.calls)
    def test_spirit_purchase_requires_new_query_each_time(self):
        raw,f=self.flow();f.request('scene.shopHandler.getMysteryShop',{})
        f.request('scene.shopHandler.buyMysteryShop',{'stallNum':1})
        with self.assertRaises(ex.BatchFatal):f.request('scene.shopHandler.buyMysteryShop',{'stallNum':1})
        self.assertEqual(len(raw.calls),2)
    def test_other_stall_denied(self):
        raw,f=self.flow();f.request('scene.shopHandler.getMysteryShop',{})
        with self.assertRaises(ex.BatchFatal):f.request('scene.shopHandler.buyMysteryShop',{'stallNum':5})
        self.assertEqual(len(raw.calls),1)
    def test_paid_or_unknown_config_denied(self):
        import json
        for currency in ['ticket','gem','unknown']:
            raw,f=self.flow();f.request('scene.shopHandler.getMysteryShop',{})
            with tempfile.TemporaryDirectory() as d:
                Path(d,'MysteryShop.json').write_text(json.dumps({'101077':{'stallNum':1,'consume_type':'coin','consume_subType':currency,'consume_count':500}}),encoding='utf8')
                with patch('game_version.latest_config_folder',return_value=Path(d)):
                    with self.assertRaises(ex.BatchFatal):f.request('scene.shopHandler.buyMysteryShop',{'stallNum':1})
            self.assertEqual(len(raw.calls),1)
    def test_contribution_limit_is_skip(self):
        self.assertTrue(ex.is_expected_skip('已达每日贡献次数上限'))


class SharedPasswordTests(unittest.TestCase):
    def test_password_goes_only_to_child_environment(self):
        from my_daily_password import prepare_launch,PASSWORD_KEYS
        args=['my_daily_runner.py','--tasks','[]'];original={'OTHER':'value','ZM5_ELITE_SELL_PASSWORD':'old'}
        out,env=prepare_launch(args,original,'test-secret')
        self.assertEqual(args,out);self.assertNotIn('test-secret',str(out))
        self.assertTrue(all(env[k]=='test-secret' for k in PASSWORD_KEYS))
        self.assertEqual(original['ZM5_ELITE_SELL_PASSWORD'],'old')
    def test_union_password_removed_from_command_line(self):
        from my_daily_password import prepare_launch
        args=['wrapper.py','C:/app/union_warehouse.py','--buy','--password','page-secret']
        out,env=prepare_launch(args,{},'batch-secret')
        self.assertNotIn('--password',out);self.assertNotIn('page-secret',out)
        self.assertEqual(env['ZM5_UNION_WAREHOUSE_PASSWORD'],'batch-secret')
    def test_empty_batch_password_preserves_page_settings(self):
        from my_daily_password import prepare_launch
        args,env=prepare_launch(['module.py'],{'ZM5_ELITE_SELL_PASSWORD':'page'},'')
        self.assertEqual(env,{'ZM5_ELITE_SELL_PASSWORD':'page'})
    def test_queue_clears_password_on_finish_or_stop(self):
        q=ModuleQueue.__new__(ModuleQueue);q.active=False;q.pending=[];q.results=[];q._password='test-secret'
        q.app=SimpleNamespace(_append_log=lambda s:None,_personal_queue=q)
        q.cancel('done');self.assertEqual(q._password,'')
    def test_daily_start_routes_core_tasks_through_password_queue(self):
        from my_daily_ui import MyDailyWindow
        seen=[];v=SimpleNamespace(get=lambda:'test-secret',set=lambda a:seen.append(('clear',a)))
        q=SimpleNamespace(start=lambda keys,**kw:seen.append((keys,kw)))
        app=SimpleNamespace(running=False,execution_gate=SimpleNamespace(busy=False))
        window=SimpleNamespace(app=app,entry_visible=lambda k:True,secondary_password=v,module_queue=q)
        MyDailyWindow.start(window,['RUN_FOREST'])
        self.assertEqual(seen,[(['RUN_FOREST'],{'password':'test-secret'}),('clear','')])
