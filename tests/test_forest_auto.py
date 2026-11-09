"""Forest unlock, single-step fallback and shared free quota regressions; no network."""
import ast
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1]/'app'
sys.path.insert(0,str(APP))
import forest_auto as forest
STAGES=tuple(range(300101,300113))

def denied():return {'code':500,'error':'当前战力不足，无法挑战'}

class FakeFlow:
    user_agent='test'
    def __init__(self,passed=(300111,),used=0):
        self.info={'_id':'test_r0','pMode':1,'p1':{'level':164},'sweepEnergy':100,
                   'dungeon':{str(m):{'passNum':1,'dailyCount':0} for m in passed}}
        self.info['dungeon'].setdefault('300101',{})['dailyCount']=used
        self.wallet={'ticket':0,'yuanbao':123}
        self.attempts=[];self.reject=set();self.sweep_reject=set();self.fail=None
    def request(self,route,params):
        if route=='connector.entryHandler.entry':return {'code':200,'info':copy.deepcopy(self.info)}
        if route=='connector.roleHandler.getUserInfo':return {'code':200,'user':dict(self.wallet)}
        raise AssertionError('Unexpected route '+route)
    def add(self,mid,count):
        row=self.info['dungeon'].setdefault(str(mid),{})
        row['passNum']=max(1,row.get('passNum',0))
        row['dailyCount']=row.get('dailyCount',0)+count
    def clear(self,mid,count):
        self.attempts.append(('clear',mid,count))
        if self.fail:raise self.fail
        if mid in self.reject:raise forest.ForestPowerInsufficient(mid,denied())
        self.add(mid,count);return count,{'loot':count}
    def sweep(self,mid,count):
        self.attempts.append(('sweep',mid,count))
        if mid in self.sweep_reject:raise forest.ForestPowerInsufficient(mid,denied())
        self.add(mid,count);self.info['sweepEnergy']-=10*count
        return {'loot':count}

class ForestTests(unittest.TestCase):
    def run_flow(self,flow,mode='sweep',selected=None,max_runs=4):
        return forest.run(flow,copy.deepcopy(flow.info),0,STAGES,mode,selected,
                          flow.clear,flow.sweep,max_runs=max_runs,log=lambda _:None)

    def test_level_unlock_is_independent_of_pass_record(self):
        info={'pMode':1,'p1':{'level':144},'dungeon':{}}
        self.assertEqual(forest.highest_opened(info,STAGES),300112)
        info['p1']['level']=143
        self.assertEqual(forest.highest_opened(info,STAGES),300111)

    def test_single_and_dual_player_level(self):
        info={'pMode':1,'p1':{'level':24},'p2':{'level':144}}
        self.assertEqual(forest.highest_opened(info,STAGES),300102)
        info['pMode']=2
        self.assertEqual(forest.highest_opened(info,STAGES),300112)

    def test_new_stage_success_then_only_remaining_three_sweeps(self):
        flow=FakeFlow()
        result=self.run_flow(flow)
        self.assertEqual(flow.attempts,[('clear',300112,1),('sweep',300112,3)])
        self.assertEqual(result['completed'],4)
        self.assertEqual(result['drops'],{'loot':4})

    def test_power_rejection_of_new_stage_falls_back_one(self):
        flow=FakeFlow();flow.reject.add(300112)
        result=self.run_flow(flow)
        self.assertEqual(flow.attempts,[('clear',300112,1),('sweep',300111,4)])
        self.assertEqual((result['fallback_from'],result['mid'],result['completed']),(300112,300111,4))

    def test_already_passed_stage_sweep_power_rejection_falls_back(self):
        flow=FakeFlow(passed=(300111,300112));flow.sweep_reject.add(300112)
        result=self.run_flow(flow)
        self.assertEqual(flow.attempts,[('sweep',300112,4),('sweep',300111,4)])
        self.assertEqual(result['completed'],4)

    def test_previous_stage_uncleared_is_cleared_before_sweep(self):
        flow=FakeFlow(passed=(300110,));flow.reject.add(300112)
        result=self.run_flow(flow)
        self.assertEqual(flow.attempts,[('clear',300112,1),('clear',300111,1),('sweep',300111,3)])
        self.assertEqual(result['completed'],4)

    def test_second_power_failure_stops_without_further_descent(self):
        flow=FakeFlow();flow.reject.add(300112);flow.sweep_reject.add(300111)
        result=self.run_flow(flow)
        self.assertEqual(len(flow.attempts),2)
        self.assertEqual(result['status'],'power_insufficient')

    def test_explicit_target_not_changed(self):
        flow=FakeFlow(passed=(300111,300112));flow.sweep_reject.add(300112)
        result=self.run_flow(flow,selected=300112)
        self.assertEqual(flow.attempts,[('sweep',300112,4)])
        self.assertEqual(result['status'],'power_insufficient')

    def test_explicit_uncleared_sweep_does_not_auto_start_battle(self):
        flow=FakeFlow()
        result=self.run_flow(flow,selected=300112)
        self.assertFalse(flow.attempts)
        self.assertEqual(result['status'],'uncleared')

    def test_non_power_or_timeout_never_falls_back(self):
        for failure in (TimeoutError('unknown outcome'),RuntimeError('背包已满')):
            flow=FakeFlow();flow.fail=failure
            with self.assertRaises(type(failure)):self.run_flow(flow)
            self.assertEqual(flow.attempts,[('clear',300112,1)])

    def test_rejected_request_cannot_have_changed_quota_or_wallet(self):
        for changed in ('quota','wallet'):
            flow=FakeFlow()
            def clear(mid,count):
                flow.attempts.append(('clear',mid,count))
                if changed=='quota':flow.add(mid,1)
                else:flow.wallet['yuanbao']-=1
                raise forest.ForestPowerInsufficient(mid,denied())
            flow.clear=clear
            with self.assertRaises(RuntimeError):self.run_flow(flow)
            self.assertEqual(len(flow.attempts),1)

    def test_only_one_remaining_shared_chance(self):
        flow=FakeFlow(used=3)
        result=self.run_flow(flow)
        self.assertEqual(flow.attempts,[('clear',300112,1)])
        self.assertEqual(result['completed'],1)

    def test_no_remaining_chances_no_probe(self):
        flow=FakeFlow(used=4)
        self.assertEqual(self.run_flow(flow)['status'],'daily_limit')
        self.assertFalse(flow.attempts)

    def test_manual_mode_respects_total_round_limit(self):
        flow=FakeFlow()
        result=self.run_flow(flow,mode='manual',max_runs=2)
        self.assertEqual(flow.attempts,[('clear',300112,1),('clear',300112,1)])
        self.assertEqual(result['completed'],2)

    def test_only_definite_power_rejection_is_eligible(self):
        self.assertTrue(forest.is_power_rejection(denied()))
        for reply in ({'code':500,'error':'请求太频繁'},dict(denied(),rnd=123),
                      dict(denied(),consume=[{'subType':'ticket','count':1}]),
                      {'code':500,'error':'次数不足，当前战力正常'},None):
            self.assertFalse(forest.is_power_rejection(reply))

    def test_source_create_surfaces_power_error_without_finish_or_pickup(self):
        tree=ast.parse((APP/'daily_auto.py').read_text(encoding='utf-8-sig'))
        func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='clear_dungeon')
        from collections import defaultdict
        import random
        ns={'_NINE_POOL':[],'ELITE_STAGES':[],'MAX_TIMES':4,'defaultdict':defaultdict,
            'quota_remain':lambda *a:4,'random':random}
        exec(compile(ast.Module(body=[func],type_ignores=[]),'clear_source','exec'),ns)
        calls=[]
        class Flow:
            def request(self,route,params):calls.append((route,params));return denied()
        with self.assertRaises(forest.ForestPowerInsufficient):
            ns['clear_dungeon'](Flow(),{},300112,'forest',raise_forest_power=True)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1]['costGem'],0)

if __name__=='__main__':unittest.main()
