"""不联网：斗神准备时序、业务心跳与结算/断线清理。"""
import sys
import queue
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
import pvp_idle as pvp


class Team:
    def __init__(self):
        self.handlers = {};self.notifications = [];self.disconnected = False
    def on(self, name, callback):self.handlers[name] = callback
    def set_close_callback(self, cb):self.close_callback = cb
    def set_kicked_callback(self, cb):self.kick_callback = cb
    def notify(self, route, params):self.notifications.append((route, params))
    def disconnect(self):self.disconnected = True;self.close_callback()


class KeepaliveTests(unittest.TestCase):
    def setUp(self):
        self.time = 0;self.team = Team()
        self.battle = pvp.BattleKeepalive(self.team, 1, clock=lambda:self.time)

    def load(self):self.team.handlers['onAllLoadComplete']({});self.battle.tick()

    def test_ready_waits_for_server_and_uses_seat_once(self):
        self.battle.tick();self.assertEqual(self.team.notifications, [])
        self.load();self.team.handlers['onAllLoadComplete']({});self.battle.tick()
        self.assertEqual(self.team.notifications, [('copy.copyHandler.keyOperation',
                         {'keys':[84],'objs':[{'ready':True,'uid':1,'teamPs':1}]})])

    def test_ping_every_ten_seconds_then_reports_roundtrip(self):
        self.load();self.team.handlers['onSendFrame']({})
        def echo(_team, route, params, timeout):
            self.assertEqual(route,'copy.copyHandler.ping');self.assertEqual(timeout,5)
            self.time += .025
            return {'code':200,'time':params['time']}
        with patch.object(pvp,'_request',side_effect=echo) as request:
            self.time=9.9;self.battle.tick();request.assert_not_called()
            self.time=10;self.battle.tick();self.assertEqual(request.call_count,1)
            obj=self.team.notifications[-1][1]['objs'][0]
            self.assertTrue(obj['ping']);self.assertEqual(obj['teamPs'],1)
            self.assertGreaterEqual(obj['pingTime'],24)
            self.time=20;self.battle.tick();self.assertEqual(request.call_count,1)
            self.time=20.025;self.battle.tick();self.assertEqual(request.call_count,2)

    def test_missing_load_or_frames_stops_instead_of_silent_hang(self):
        self.time=30
        with self.assertRaisesRegex(RuntimeError,'加载'):self.battle.tick()
        self.time=0;self.load();self.time=30
        with self.assertRaisesRegex(RuntimeError,'战斗帧'):self.battle.tick()

    def test_bad_ping_is_not_retried_or_reported_as_success(self):
        for reply in ({'code':500,'error':'closed'},{'code':200},{'time':-1}):
            with self.subTest(reply=reply):
                self.setUp();self.load();self.team.handlers['onSendFrame']({});self.time=10
                with patch.object(pvp,'_request',return_value=reply) as request:
                    with self.assertRaisesRegex(RuntimeError,'心跳'):self.battle.tick()
                    self.assertEqual(request.call_count,1)
                    self.assertEqual(len(self.team.notifications),1)

    def test_live_ping_echo_with_code_500_matches_original_client(self):
        self.load();self.team.handlers['onSendFrame']({});self.time=10
        def echo(_team,route,params,timeout):
            return {'code':500,'time':params['time'],
                    'serverTime':params['time']+581,'__route__':route}
        with patch.object(pvp,'_request',side_effect=echo):self.battle.tick()
        self.assertTrue(self.team.notifications[-1][1]['objs'][0]['ping'])
        self.assertEqual(self.team.notifications[-1][1]['objs'][0]['teamPs'],1)

    def test_stopped_session_sends_nothing_even_with_late_callbacks(self):
        self.battle.stop();self.time=100;self.team.handlers['onAllLoadComplete']({})
        with patch.object(pvp,'_request',side_effect=AssertionError('No request after stop')):
            self.battle.tick()
        self.assertEqual(self.team.notifications,[])

    def test_closed_battle_has_small_settlement_grace_then_stops(self):
        self.load();self.team.close_callback();self.battle.tick()
        self.time=2
        with self.assertRaisesRegex(RuntimeError,'断开'):self.battle.tick()
        self.assertEqual(len(self.team.notifications),1)

    def test_main_loop_consumes_load_push_before_confirm_and_disconnects(self):
        events=queue.Queue();online={'ip':'test','port':1,'instId':'test','password':'test',
                                    'playerInfos':[{'uid':'other'},{'uid':'100'}]}
        events.put(('onCreateOnlineCopy',online))
        team=Team()
        def notify(route,params):
            team.notifications.append((route,params))
            if route.endswith('loadComplete'):team.handlers['onAllLoadComplete']({})
            elif params.get('objs',[{}])[0].get('ready'):
                team.handlers['onSendFrame']({});events.put(('onPVPFinish',{}))
        team.notify=notify
        flow=SimpleNamespace(uid='100',request=lambda *_:{'code':200})
        with patch.object(pvp,'team_connect',return_value=team),patch.object(pvp,'_request',return_value={'code':200}),\
             patch.object(pvp,'_confirm_match',return_value=True):
            self.assertTrue(pvp._one_match(flow,events,0,0,90,600))
        self.assertEqual([r for r,_ in team.notifications],['copy.copyHandler.loadComplete','copy.copyHandler.keyOperation'])
        self.assertTrue(team.disconnected)

    def test_prepare_notify_failure_disconnects_and_does_not_rematch(self):
        events=queue.Queue();events.put(('onCreateOnlineCopy',{'ip':'t','port':1,'instId':'i','password':'p','playerInfos':[{'uid':'100'}]}))
        team=Team()
        def notify(route,params):
            if route.endswith('loadComplete'):team.handlers['onAllLoadComplete']({})
            else:raise ConnectionError('closed')
        team.notify=notify
        calls=[]
        flow=SimpleNamespace(uid='100',request=lambda r,p:(calls.append(r) or {'code':200}))
        with patch.object(pvp,'team_connect',return_value=team),patch.object(pvp,'_request',return_value={'code':200}):
            with self.assertRaises(ConnectionError):pvp._one_match(flow,events,0,0,90,600)
        self.assertEqual(calls.count('scene.pvpHandler.matchStart'),1)
        self.assertTrue(team.disconnected)

    def test_escape_increase_stops_a_multi_match_job(self):
        flow=SimpleNamespace(disconnect=lambda:None)
        before={'pvpSeason':{'pvpNum':[7,0],'escape':3,'totalEscape':3}}
        after={'pvpSeason':{'pvpNum':[8,0],'escape':4,'totalEscape':4}}
        with patch.object(sys,'argv',['pvp_idle.py','--matches','3']),\
             patch.object(Path,'open',mock_open(read_data='{"record_index":0}')),\
             patch.object(pvp,'connect',return_value=(flow,before)),\
             patch.object(pvp,'enter',return_value=after),\
             patch.object(pvp,'_one_match',return_value=True) as one:
            flow.on=lambda *_:None
            self.assertEqual(pvp.main(),1)
            self.assertEqual(one.call_count,1)

    def test_robot_branch_does_not_create_or_ping_a_real_battle_room(self):
        calls=[]
        def request(route,params):
            calls.append(route)
            if route.endswith('matchStart'):
                return {'code':200,'robot':{'name':'test','entityId':'test'}}
            return {'code':200,'data':{'winType':1}}
        flow=SimpleNamespace(request=request)
        with patch.object(pvp,'_confirm_match',return_value=True),\
             patch.object(pvp,'team_connect',side_effect=AssertionError('No real room')):
            self.assertTrue(pvp._one_match(flow,queue.Queue(),0,0,90,600))
        self.assertEqual(calls,['scene.pvpHandler.matchStart','scene.pvpHandler.robotPVPFinish'])


if __name__=='__main__':unittest.main()
