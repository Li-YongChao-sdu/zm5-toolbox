"""Online task timing regressions use synthetic clocks and replies, never real waiting."""
import ast
import copy
import sys
import types
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import fashion_online as online

class FakeFlow:
    def __init__(self,stored=0,status=1):
        self.t=0.;self.date=datetime(2026,11,5,10,tzinfo=online.BEIJING)
        self.info={'_id':'dummy_r0','uid':'dummy','lastLoginTime':1}
        self.quest={'id':970002,'status':status,'progress':{'0':stored}}
        self._fashion_online_clock=online.OnlineClock(lambda:self.t,lambda:self.date)
        self._fashion_online_clock.enter(self.info)
        self._fashion_online_clock.sample(self.quest)
        self.game=types.SimpleNamespace(_running=True)
        self.calls=[];self.reject=False;self.timeout=False;self.money={'ticket':0,'yuanbao':100}
    def request(self,route,data):
        self.calls.append((route,data))
        if route=='scene.questHandler.getQuestList':return {'code':200,'quest':[copy.deepcopy(self.quest)]}
        if route=='connector.roleHandler.getUserInfo':return {'code':200,'user':dict(self.money)}
        if route=='scene.questHandler.commitQuest':
            if self.timeout:raise TimeoutError('unknown')
            if self.reject:return {'code':500,'error':'时间不足'}
            self.quest['status']=3;self.quest['progress']={'0':1200}
            return {'code':200,'give':[{'type':'coin','subType':'dailyTaskMoney','count':60}]}
        raise AssertionError(route)
    def commits(self):return [c for c in self.calls if c[0]=='scene.questHandler.commitQuest']

class FashionOnlineTests(unittest.TestCase):
    def claim(self,flow,**kwargs):
        with patch.object(online,'target_seconds',return_value=1200):
            return online.claim_online(flow,flow.info,0,output=lambda _:None,log=lambda _:None,**kwargs)
    def test_zero_saved_progress_but_twenty_minutes_live_can_claim(self):
        f=FakeFlow();f.t=1205
        result=self.claim(f)
        self.assertEqual(result['status'],'claimed')
        self.assertEqual(f.commits(),[('scene.questHandler.commitQuest',{'qId':970002})])
    def test_stored_and_current_session_are_combined(self):
        f=FakeFlow(stored=700);f.t=500
        self.assertEqual(self.claim(f)['status'],'claimed')
    def test_query_progress_does_not_double_count_same_saved_time(self):
        f=FakeFlow(stored=100);f.t=400;f.quest['progress']={'0':500}
        state=online.snapshot(f,f.info,0,f.quest,target=1200)
        self.assertEqual(state['estimated_seconds'],500)
        self.assertEqual(self.claim(f)['status'],'not_ready')
        self.assertFalse(f.commits())
    def test_status_two_can_claim_even_when_progress_missing(self):
        f=FakeFlow(status=2)
        self.assertEqual(self.claim(f)['status'],'claimed')
    def test_claimed_state_never_repeated(self):
        f=FakeFlow(stored=1200,status=3)
        self.assertEqual(self.claim(f)['status'],'already_claimed')
        self.assertFalse(f.commits())
    def test_short_session_skips_without_waiting_by_default(self):
        f=FakeFlow();f.t=100
        result=self.claim(f)
        self.assertEqual(result['status'],'not_ready')
        self.assertEqual(result['state']['remaining_seconds'],1100)
    def test_server_rejection_or_unknown_reply_not_retried(self):
        for mode in ('reject','timeout'):
            f=FakeFlow();f.t=1205;setattr(f,mode,True)
            with self.assertRaises((RuntimeError,TimeoutError)):self.claim(f)
            self.assertEqual(len(f.commits()),1)
    def test_reentry_same_login_keeps_clock_new_login_resets_it(self):
        f=FakeFlow();f.t=500
        f._fashion_online_clock.enter(f.info)
        self.assertEqual(f._fashion_online_clock.elapsed(),500)
        f._fashion_online_clock.enter(dict(f.info,lastLoginTime=2))
        self.assertEqual(f._fashion_online_clock.elapsed(),0)
        self.assertIsNone(f._fashion_online_clock.base)
    def test_switch_record_and_disconnect_do_not_inflate_time(self):
        f=FakeFlow();f.t=500
        f._fashion_online_clock.enter(dict(f.info,_id='dummy_r1'))
        self.assertEqual(f._fashion_online_clock.elapsed(),0)
        f.t=510;f._fashion_online_clock.close();f.t=900
        self.assertEqual(f._fashion_online_clock.elapsed(),10)
    def test_previous_day_elapsed_not_reused(self):
        f=FakeFlow();f.t=1500;f.date+=timedelta(days=1)
        self.assertEqual(f._fashion_online_clock.total({'progress':{'0':0}}),0)
    def test_snapshot_rejects_old_record_after_slot_switch(self):
        f=FakeFlow();f._fashion_online_clock.enter(dict(f.info,_id='dummy_r1'))
        with self.assertRaisesRegex(RuntimeError,'存档已变化'):
            online.snapshot(f,f.info,0,f.quest,target=1200)
    def test_disconnect_during_wait_never_submits_reward(self):
        f=FakeFlow(stored=1199)
        def disconnect(seconds):f.t+=seconds;f.game._running=False
        with self.assertRaisesRegex(RuntimeError,'连接已断开'):
            self.claim(f,wait=True,sleep=disconnect)
        self.assertFalse(f.commits())
    def test_optional_wait_keeps_same_connection_and_only_reads_again_at_end(self):
        f=FakeFlow(stored=1199)
        with patch.object(online,'snapshot',wraps=online.snapshot) as observed:
            result=self.claim(f,wait=True,sleep=lambda n:setattr(f,'t',f.t+n))
        self.assertEqual(result['status'],'claimed')
        self.assertFalse(any(c[0]=='connector.entryHandler.entry' for c in f.calls))
        self.assertEqual(sum(c[0]=='scene.questHandler.getQuestList' for c in f.calls),3)
        self.assertGreater(observed.call_count,1)
    def test_both_old_entrypoints_delegate_to_shared_logic(self):
        app=Path(online.__file__).parent
        tree=ast.parse((app/'daily_auto.py').read_text(encoding='utf-8-sig'))
        func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='claim_fashion_online')
        ns={'RECORD_INDEX':0,'print':lambda *a:None}
        exec(compile(ast.Module(body=[func],type_ignores=[]),'daily_online','exec'),ns)
        with patch.object(online,'claim_online',return_value={'status':'already_claimed'}) as claim:
            ns['claim_fashion_online'](object(),{})
            claim.assert_called_once()
        import new_player_rewards as rewards
        f=FakeFlow(status=3);f.info['dailyTaskSpecial']={'startTime':1,'lastSignInTime':9999999999999}
        fake_teacher=types.ModuleType('teacher_trial');fake_teacher.enter=lambda *a:copy.deepcopy(f.info)
        with patch.dict(sys.modules,{'teacher_trial':fake_teacher}),patch.object(rewards,'config',side_effect=lambda name:{'970002':{}} if name=='DailyTask' else {}),patch.object(online,'claim_online',return_value={'status':'already_claimed'}) as claim:
            rewards.run(f,f.info,0,'fashion',only_claim_ids={970002})
            claim.assert_called_once()

if __name__=='__main__':unittest.main()
