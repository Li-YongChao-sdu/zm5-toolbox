"""不联网：周箱优先、严格最高档、续接地图、限次换图及收尾重置。"""
import copy
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
import star_maze as maze


def info(earned=0, claimed=0, stock=0):
    return {'uid':'100','_id':'100_r9','everyWeekSetting':{'resetTime':100,
            'mazeCnt':earned,'rewardMazeCnt':claimed,'mazeReward':{'5270':stock,'5094':9,'5137':9}},
            'bag':{'item':{}}}


def map_data(chapter=2, passed=False, strength=100, pos=None):
    return {'chapter':chapter,'chapterPassed':passed,'pos':pos,
            'createTime':1000,'serverTime':181001,'mazeItem':{'101':{'count':strength}},
            'map':[[[0]], [[]]], 'event':[[[201,1]],[[203,1]]]}


class Flow:
    user_agent='test'
    def __init__(self, state=None, data=None):
        self.info=copy.deepcopy(state or info());self.data=copy.deepcopy(data or map_data())
        self.calls=[];self.moves=[];self.block=set();self.lost_claim=False;self.bad_claim=False
        self.bad_reward_counter=False;self.return_claim_error=False;self.bad_reset=False
    def request(self, route, params):
        self.calls.append((route,copy.deepcopy(params)))
        if route=='connector.entryHandler.entry':return {'code':200,'info':copy.deepcopy(self.info)}
        if route.endswith('getMapData'):return {'code':200,'data':copy.deepcopy(self.data)}
        if route.endswith('getFinishRewardFree'):
            assert params=={'type':0,'rewardId':5270},'Never claim lower-tier boxes'
            if self.return_claim_error:return {'code':500,'error':'背包不足'}
            w=self.info['everyWeekSetting'];w['rewardMazeCnt']+=1;w['mazeReward']['5270']-=1
            self.info['bag']['item'].setdefault('stone',{'id':101035002,'count':0})['count']+=4
            if self.lost_claim:raise TimeoutError('lost reward reply')
            if self.bad_reward_counter:w['rewardMazeCnt']-=1
            return {'code':500} if self.bad_claim else {'code':200,'give':[{'type':'item','subType':101035002,'count':4}]}
        if route.endswith('goto'):
            move=(params['x'],params['y']);self.moves.append(move)
            if move in self.block:return {'code':500,'error':'道具数量不足'}
            self.data['pos']={'x':params['x'],'y':params['y']}
            return {'code':200,'event':0}
        if route.endswith('nextChapter'):
            self.data['chapter']+=1;self.data['chapterPassed']=False;self.data['pos']=None
            return {'code':200}
        if route.endswith('reset'):
            if not self.bad_reset:
                self.data=map_data(chapter=1);self.data['createTime']+=1
            return {'code':200}
        raise AssertionError('Unexpected route: '+route)


class StarMazeTests(unittest.TestCase):
    def run_maze(self, f, handle=None):
        # 节点战斗与走图策略已有实现；此处模拟服务器通关，核对新增流程的时序。
        def finish_node(*_):
            f.data['chapterPassed']=True
            if f.data['chapter']==3:
                w=f.info['everyWeekSetting'];w['mazeCnt']+=1;w['mazeReward']['5270']+=1
            return 'ok',None
        with patch.object(maze,'_handle_node',side_effect=handle or finish_node),\
             patch.object(maze.time,'sleep',return_value=None),patch('builtins.open',mock_open()),redirect_stdout(io.StringIO()):
            return maze.run_star_maze(f,copy.deepcopy(f.info),6)

    def routes(self,f):return [r.rsplit('.',1)[-1] for r,p in f.calls]

    def test_claim_existing_first_then_skip_if_weekly_full_without_touching_map(self):
        f=Flow(info(3,2,1),map_data(2))
        done,bag=self.run_maze(f)
        self.assertEqual(done,0);self.assertEqual(bag,{'101035002':4})
        self.assertEqual(self.routes(f),['entry','getFinishRewardFree','entry','getMapData'])

    def test_already_full_skips_even_if_old_map_not_finished(self):
        f=Flow(info(3,3,0),map_data(2))
        self.assertEqual(self.run_maze(f),(0,{}))
        self.assertEqual(self.routes(f),['entry'])

    def test_claims_existing_highest_boxes_only_until_shared_weekly_cap(self):
        f=Flow(info(5,0,4))
        self.run_maze(f)
        self.assertEqual(self.routes(f).count('getFinishRewardFree'),3)
        self.assertEqual(f.info['everyWeekSetting']['mazeReward']['5270'],1)
        self.assertNotIn('reset',self.routes(f))
        self.assertNotIn('goto',self.routes(f))

    def test_existing_claim_fills_cap_and_finishes_completed_map_cleanup(self):
        f=Flow(info(3,2,1),map_data(3,True))
        done,_=self.run_maze(f)
        names=self.routes(f)
        self.assertEqual(done,3)
        self.assertEqual(names.count('reset'),1)
        self.assertLess(names.index('getFinishRewardFree'),names.index('reset'))
        self.assertNotIn('goto',names)

    def test_never_substitutes_lower_boxes_when_highest_stock_zero(self):
        f=Flow(info(3,0,0),map_data(3,True))
        maze._claim_emerald(f,6,f.info,{},lambda _:None)
        self.assertNotIn('getFinishRewardFree',self.routes(f))

    def test_old_completed_map_without_highest_box_starts_one_needed_new_run(self):
        f=Flow(info(3,1,0),map_data(3,True))
        done,_=self.run_maze(f)
        names=self.routes(f)
        self.assertEqual(done,3)
        self.assertEqual(names.count('reset'),2)  # 旧图无下一步，重开一次；新通关后收尾一次
        self.assertLess(names.index('reset'),names.index('goto'))
        self.assertEqual(names.count('getFinishRewardFree'),1)

    def test_resume_second_layer_then_claim_and_reset_exactly_once(self):
        f=Flow(info(2,2,0),map_data(2))
        done,bag=self.run_maze(f)
        names=self.routes(f)
        self.assertEqual(done,3);self.assertEqual(bag,{'101035002':4})
        self.assertLess(names.index('goto'),names.index('reset'))
        self.assertEqual(names.count('nextChapter'),1)
        self.assertEqual(names.count('reset'),1)
        self.assertLess(names.index('getFinishRewardFree'),names.index('reset'))
        self.assertEqual(names[-2:],['reset','getMapData'])
        self.assertEqual(f.data['chapter'],1)

    def test_resume_third_layer_has_no_advance_or_startup_reset(self):
        f=Flow(info(2,2,0),map_data(3))
        self.assertEqual(self.run_maze(f)[0],3)
        names=self.routes(f)
        self.assertNotIn('nextChapter',names);self.assertEqual(names.count('reset'),1)
        self.assertLess(names.index('goto'),names.index('reset'))

    def test_existing_boxes_claimed_before_following_current_map(self):
        f=Flow(info(2,1,1),map_data(3))
        self.run_maze(f)
        names=self.routes(f)
        self.assertEqual(names.count('getFinishRewardFree'),2)
        self.assertLess(names.index('getFinishRewardFree'),names.index('getMapData'))

    def test_completed_map_is_not_replayed_before_cleanup(self):
        f=Flow(info(2,1,1),map_data(3,True))
        self.run_maze(f)
        names=self.routes(f)
        self.assertNotIn('goto',names);self.assertNotIn('nextChapter',names)
        self.assertEqual(names.count('reset'),1)

    def test_claim_rejection_or_bad_counter_preserves_progress_without_reset(self):
        for attr in ('return_claim_error','bad_claim','bad_reward_counter'):
            with self.subTest(attr=attr):
                f=Flow(info(3,2,1));setattr(f,attr,True);self.run_maze(f)
                names=self.routes(f)
                self.assertEqual(names.count('getFinishRewardFree'),1)
                self.assertNotIn('reset',names);self.assertNotIn('goto',names)

    def test_unknown_claim_result_not_retried_and_does_not_reset(self):
        f=Flow(info(3,2,1));f.lost_claim=True
        with self.assertRaises(TimeoutError):self.run_maze(f)
        self.assertEqual(self.routes(f).count('getFinishRewardFree'),1)
        self.assertNotIn('reset',self.routes(f))

    def test_final_claim_failure_preserves_completed_map(self):
        f=Flow(info(2,2,0),map_data(3));f.return_claim_error=True
        self.run_maze(f)
        self.assertTrue(f.data['chapterPassed'])
        self.assertNotIn('reset',self.routes(f))

    def test_pending_current_boss_is_completed_without_repeating_goto(self):
        f=Flow(info(2,2,0),map_data(3,pos={'x':1,'y':0}))
        done,_=self.run_maze(f)
        self.assertEqual(done,3)
        self.assertNotIn('goto',self.routes(f))
        self.assertEqual(self.routes(f).count('reset'),1)

    def test_missing_weekly_fields_stops_without_map_or_mutation(self):
        f=Flow();f.info['everyWeekSetting'].pop('mazeCnt')
        self.run_maze(f);self.assertEqual(self.routes(f),['entry'])

    def test_fresh_week_all_zero_fields_omitted_uses_proven_client_defaults(self):
        f=Flow();f.info['everyWeekSetting']={'resetTime':100};f.info['serverTime']=1000
        normalized,q=maze._weekly_info(f,6,f.info)
        self.assertEqual(q['mazeCnt'],0);self.assertEqual(q['rewardMazeCnt'],0)
        self.assertEqual(q['weekly_left'],3);self.assertEqual(q['rewardStock'],{})
        self.assertEqual(f.info['everyWeekSetting'],{'resetTime':100})

    def test_unknown_goto_rejection_does_not_trigger_reset(self):
        f=Flow(info(2,2,0));original=f.request
        def request(route,params):
            if route.endswith('goto'):
                f.calls.append((route,params));return {'code':500,'error':'重复请求，请稍后'}
            return original(route,params)
        f.request=request;self.run_maze(f)
        self.assertNotIn('reset',self.routes(f))

    def test_known_blocked_route_tries_alternative_before_reset(self):
        f=Flow(info(2,2,0),map_data(3))
        f.data['map']=[[[0],[0]],[[]]];f.data['event']=[[[201,1],[201,1]],[[203,1]]]
        f.block={(0,0)}
        self.run_maze(f)
        self.assertEqual(f.moves,[(0,0),(0,1)])
        self.assertEqual(self.routes(f).count('reset'),1)  # 只有通关后的收尾重置

    def test_truly_no_path_has_bounded_global_recovery_reset_budget(self):
        f=Flow(info(0,0,0));f.data['map']=[[[]]];f.data['event']=[[[201,1]]]
        original=f.request
        def request(route,params):
            result=original(route,params)
            if route.endswith('reset'):
                f.data['map']=[[[]]];f.data['event']=[[[201,1]]]
            return result
        f.request=request;self.run_maze(f)
        self.assertEqual(self.routes(f).count('reset'),maze.MAX_RECOVERY_RESETS)
        self.assertNotIn('goto',self.routes(f))

    def test_reset_success_without_fresh_map_confirmation_stops(self):
        f=Flow(info(2,2,0),map_data(3));f.bad_reset=True
        self.run_maze(f)
        self.assertEqual(self.routes(f).count('reset'),1)

    def test_waits_remaining_180s_before_advance_without_repeated_request(self):
        f=Flow(info(2,2,0),map_data(1,True));f.data['serverTime']=31000
        waits=[]
        def wait(n,log):waits.append(n);f.data['serverTime']=181001
        with patch.object(maze,'_wait_cooldown',side_effect=wait):
            maze._next_chapter(f,copy.deepcopy(f.data),lambda _:None)
        self.assertEqual(waits,[150])
        self.assertEqual(self.routes(f).count('nextChapter'),1)
        self.assertNotIn('reset',self.routes(f))

    def test_progress_changed_during_cooldown_is_not_overwritten(self):
        f=Flow(info(2,2,0),map_data(1,True));f.data['serverTime']=31000
        def change(*_):f.data['pos']={'x':1,'y':0}
        with patch.object(maze,'_wait_cooldown',side_effect=change),self.assertRaises(RuntimeError):
            maze._reset_run(f,copy.deepcopy(f.data),lambda _:None,'test')
        self.assertNotIn('reset',self.routes(f))

    def test_missing_cooldown_state_does_not_guess_or_reset(self):
        f=Flow();f.data.pop('serverTime')
        with self.assertRaises(RuntimeError):maze._reset_run(f,f.data,lambda _:None,'test')
        self.assertNotIn('reset',self.routes(f))

    def test_unknown_reset_and_advance_results_are_not_repeated(self):
        for name in ('reset','nextChapter'):
            with self.subTest(name=name):
                f=Flow(info(2,2,0),map_data(2,True));original=f.request
                def request(route,params):
                    reply=original(route,params)
                    if route.endswith(name):raise TimeoutError('response lost after applying')
                    return reply
                f.request=request
                with self.assertRaises(TimeoutError):
                    if name=='reset':maze._reset_run(f,f.data,lambda _:None,'test')
                    else:maze._next_chapter(f,f.data,lambda _:None)
                self.assertEqual(self.routes(f).count(name),1)

    def test_reward_inventory_mismatch_stops_before_next_claim_or_reset(self):
        f=Flow(info(3,0,3));original=f.request
        def request(route,params):
            reply=original(route,params)
            if route.endswith('getFinishRewardFree'):f.info['bag']['item']['stone']['count']-=1
            return reply
        f.request=request;self.run_maze(f)
        self.assertEqual(self.routes(f).count('getFinishRewardFree'),1)
        self.assertNotIn('reset',self.routes(f))

    def test_first_boss_finish_rejected_does_not_send_victory(self):
        class Reject:
            def __init__(self):self.calls=[]
            def request(self,r,p):self.calls.append(r);return {'code':500}
        f=Reject();result,_=maze._handle_node(f,203,{},lambda _:None)
        self.assertEqual(result,'fail')
        self.assertEqual(f.calls,['scene.mazeHandler.enterDungeon'])


if __name__=='__main__':unittest.main()
