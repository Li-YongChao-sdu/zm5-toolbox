"""不联网：覆盖补测前恢复的领奖和异常保护、模型时间、显示顺序。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP))
import arena_registration as registration
import my_daily_policy as policy
import my_daily_ui
import union_boss
import pet_arena_reward


class RepairsTests(unittest.TestCase):
    def test_duplicate_request_does_not_mean_enrolled(self):
        class Flow:
            def request(self, *_):
                return {'code': 500, 'error': '重复请求，请稍后再试'}
        with patch.object(registration, 'registration_open', return_value=True), \
             patch.object(registration, '_merge_home', side_effect=lambda f, h, i: i), \
             patch.object(registration, 'entry_info', return_value={}), \
             patch.object(registration, 'enrolled', return_value=False):
            self.assertFalse(registration.ensure(Flow(), 'arena', info={}))

    def test_duplicate_with_verified_state_can_succeed(self):
        class Flow:
            def request(self, *_):
                return {'code': 500, 'error': '已报名'}
        with patch.object(registration, 'registration_open', return_value=True), \
             patch.object(registration, '_merge_home', side_effect=lambda f, h, i: i), \
             patch.object(registration, 'entry_info', return_value={'enrolled': True}), \
             patch.object(registration, 'enrolled', side_effect=lambda i,h:bool(i.get('enrolled'))):
            self.assertTrue(registration.ensure(Flow(), 'arena', info={}))

    def test_mutating_get_timeout_halts(self):
        class Flow:
            def request(self, *_a, **_k):
                raise TimeoutError('unknown')
        for route in ('scene.teacherHandler.getBuffer', 'scene.giftHandler.getGift',
                      'scene.mailHandler.getAndRemoveMail', 'scene.copyHandler.getDungeonTreasureDrop'):
            with self.subTest(route=route):
                flow = policy.FreeDailyFlow(Flow(), {})
                with self.assertRaises(TimeoutError):
                    flow.request(route, {})
                self.assertTrue(flow.halted)
                with self.assertRaises(RuntimeError):
                    flow.request('scene.questHandler.getQuestList', {})

    def test_real_query_timeout_does_not_mark_consumption_unknown(self):
        class Flow:
            def request(self, *_):
                raise TimeoutError('read')
        flow = policy.FreeDailyFlow(Flow(), {})
        with self.assertRaises(TimeoutError):
            flow.request('scene.arenaHandler.getArenaInfo', {})
        self.assertFalse(flow.halted)

    def test_long_cast_does_not_speed_up_simulation_time(self):
        class Model:
            def __init__(self): self.times = []
            def choose(self, _): return 1
            def cast(self, _, tick): self.times.append(tick); return 10, 2.25
        model = Model()
        state = {'model_time': 0.0, 'pending': 0.0}
        for elapsed in (1.0, 2.0, 3.0, 4.0):
            union_boss.advance_model_actions(model, state, elapsed)
            self.assertTrue(all(t < elapsed for t in model.times))
        self.assertEqual(model.times, [0.0, 2.25])
        self.assertEqual(state['pending'], 20)

    def test_liveness_last_display(self):
        keys = ['RUN_LIVENESS', 'RUN_CELEBRATION_ONLINE', 'RUN_ELITE',
                'RUN_FLUSHOU', 'RUN_WEEKEND_BUFF', 'RUN_GROWTH_BUFF']
        ordered = my_daily_ui.ordered_favorites(keys)
        self.assertEqual(ordered[:3], ['RUN_FLUSHOU', 'RUN_GROWTH_BUFF', 'RUN_WEEKEND_BUFF'])
        self.assertEqual(ordered[-1], 'RUN_LIVENESS')

    def test_restored_pet_reward_verifies_coins_items_and_flag(self):
        class Flow:
            user_agent = 'test'
            def __init__(self): self.claimed = False
            def request(self, route, _):
                setting = {'rewardTime': 1 if self.claimed else 0}
                if route == 'connector.entryHandler.entry':
                    return {'code': 200, 'info': {'petArenaMoney': 200 if self.claimed else 100,
                            'everyWeekSetting': {'petArenaSetting': setting},
                            'bag': {'item': {'101005001': {'count': 2}} if self.claimed else {}}}}
                if route == 'connector.roleHandler.getUserInfo':
                    return {'code': 200, 'user': {'ticket': 7, 'yuanbao': 9}}
                if route.endswith('getArenaInfo'):
                    return {'code': 200, 'everyWeekSetting': {'petArenaSetting': setting}}
                if route == 'scene.petArenaHandler.getReward':
                    self.claimed = True
                    return {'code': 200, 'give': [{'type': 'coin', 'subType': 'petArenaMoney', 'count': 100},
                                                 {'type': 'item', 'subType': '101005001', 'count': 2}]}
                raise AssertionError(route)
        directory = Path(r'C:\Users\huawei\Documents\Codex\2026-10-25\no-module-named-requests\work\continuous_tests_20261106')
        with tempfile.TemporaryDirectory(dir=directory) as temp:
            ok, _, report = pet_arena_reward.do_claim(Flow(), {}, slot=0, report_dir=temp)
        self.assertTrue(ok)
        self.assertEqual(report['phase'], 'verified')


if __name__ == '__main__':
    unittest.main()

class RuneKeepRegression(unittest.TestCase):
    def test_keep_sends_no_confirmation(self):
        import wash_api,wash_data
        class NoRequest:
            def request(self,*a,**kw):raise AssertionError('Must not confirm replacement')
        self.assertEqual(wash_data.confirm_call('rune','eid',False),(None,None))
        ok,msg,raw=wash_api.confirm_wash(NoRequest(),'rune','eid','',False)
        self.assertTrue(ok)
        self.assertIn('保留旧',msg)
        self.assertIsNone(raw)
    def test_save_still_uses_empty_payload(self):
        import wash_data
        self.assertEqual(wash_data.confirm_call('rune','eid',True),('scene.magicWeaponHandler.confirmResetRuneAttr',{}))

class GrowthReadyRegression(unittest.TestCase):
    def test_ready_task_claims_without_composing(self):
        import daily_auto as da
        from unittest.mock import patch
        class NoRequest:
            def request(self,*args,**kwargs):raise AssertionError('Ready task must not consume materials')
        with patch.object(da,'_load_cfg',return_value={}), patch.object(da,'_growth_pick',return_value=[(831039,[], '一品丹药')]), patch.object(da,'_growth_quest_status',return_value={831039:{'status':2}}), patch.object(da,'_growth_commit') as claim:
            da.claim_growth_dan_tasks(NoRequest(),{})
            claim.assert_called_once()

class TimeEnergyCapacityRegression(unittest.TestCase):
    def test_full_equipment_bag_stops_before_target_or_exchange(self):
        import time_energy_run as ter
        with self.assertRaisesRegex(ValueError,'装备背包已满'):
            ter.preflight(None,{'bag':{'equipBagMax':1,'equip':{'e1':{}}}},2,None,0)
    def test_missing_equipment_capacity_is_not_assumed_empty(self):
        import time_energy_run as ter
        with self.assertRaisesRegex(ValueError,'无法确认'):
            ter.preflight(None,{},3,None,0)
