"""Offline guard regressions, using synthetic configuration and replies only."""
import ast
import copy
import importlib
import json
import random
import sys
import tempfile
import types
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP))
from activity_stage_selection import choose_normal_stage


class BountySelectionTests(unittest.TestCase):
    def setUp(self):
        self.stages = [dict(mid=80, probability=.5, rolelevel=20),
                       dict(mid=30800, probability=1, rolelevel=20)]
        self.table = {'80': dict(difficult=0, dailyCountMax=-1),
                      '30800': dict(difficult=1, dailyCountMax=2)}
        self.info = dict(p1=dict(level=168), dungeon={
            '80': dict(passNum=1, dailyCount=20),
            '30800': dict(passNum=1, dailyCount=0)})
        daily = types.ModuleType('daily_auto')
        daily._dungeon_rec = lambda info, mid: info.get('dungeon', {}).get(str(mid))
        self.modules = patch.dict(sys.modules, {'daily_auto': daily})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_excludes_higher_probability_elite(self):
        self.assertEqual(choose_normal_stage(self.stages, self.info, self.table)['mid'], 80)

    def test_elite_only_is_not_a_fallback(self):
        self.assertIsNone(choose_normal_stage(self.stages[1:], self.info, self.table))

    def test_exhausted_free_quota_stops(self):
        self.table['80']['dailyCountMax'] = 2
        self.assertIsNone(choose_normal_stage(self.stages, self.info, self.table))

    def test_level_and_clearance_required(self):
        for info in [dict(p1=dict(level=10), dungeon=self.info['dungeon']),
                     dict(p1=dict(level=168), dungeon={})]:
            with self.subTest(info=info):
                self.assertIsNone(choose_normal_stage(self.stages, info, self.table))


class EliteCostTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((APP / 'daily_auto.py').read_text(encoding='utf-8-sig'))
        names = {'_elite_wallet', '_check_elite_cost', 'clear_dungeon'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.ns = dict(_NINE_POOL=[], ELITE_STAGES=[30800], MAX_TIMES=2,
                       defaultdict=defaultdict, random=random, RECORD_INDEX=0, FIGHT_DELAY=0,
                       quota_remain=lambda info, pool, limit: limit-info['dungeon']['30800']['dailyCount'],
                       _dungeon_dcount=lambda info, mid: info['dungeon'][str(mid)]['dailyCount'])
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'elite_source', 'exec'), self.ns)
        self.teacher = types.ModuleType('teacher_trial')
        self.teacher.enter = lambda flow, slot: {'dungeon': {'30800': {'dailyCount': 0}}}
        self.modules = patch.dict(sys.modules, {'teacher_trial': self.teacher})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    class Flow:
        def __init__(self, consume=None, delta=0, missing=False):
            self.consume, self.delta, self.missing = consume or [], delta, missing
            self.calls, self.created = [], False

        def request(self, route, params):
            self.calls.append(route)
            if route == 'connector.roleHandler.getUserInfo':
                user = dict(ticket=100-(self.delta if self.created else 0), yuanbao=200)
                if self.missing:
                    user.pop('yuanbao')
                return dict(code=200, user=user)
            if route != 'scene.copyHandler.createSinglePlayerCopy':
                raise AssertionError('Unexpected write after stop: '+route)
            self.created = True
            return dict(code=500, error='synthetic rejection', consume=self.consume)

    def run_clear(self, flow):
        return self.ns['clear_dungeon'](flow, {}, 30800, 'elite', quota=([30800], 2))

    def test_paid_response_or_balance_change_stops_before_finish(self):
        for flow in [self.Flow(consume=[dict(subType='ticket', count=100)]),
                     self.Flow(consume=[dict(subType='yuanbao', count=1)]), self.Flow(delta=100)]:
            with self.subTest(flow=flow), self.assertRaises(RuntimeError):
                self.run_clear(flow)
            self.assertFalse(any('finish' in r or 'syncDrop' in r for r in flow.calls))

    def test_missing_wallet_stops_before_create(self):
        flow = self.Flow(missing=True)
        with self.assertRaises(RuntimeError):
            self.run_clear(flow)
        self.assertFalse(flow.created)

    def test_exhausted_quota_sends_no_request(self):
        self.teacher.enter = lambda flow, slot: {'dungeon': {'30800': {'dailyCount': 2}}}
        flow = self.Flow()
        self.assertEqual(self.run_clear(flow), (0, {}))
        self.assertFalse(flow.calls)

    def test_settlement_and_card_balance_checks(self):
        for phase in ('结算', '免费翻牌'):
            self.ns['_check_elite_cost'](self.Flow(), dict(ticket=100, yuanbao=200), {}, phase)
            with self.assertRaises(RuntimeError):
                self.ns['_check_elite_cost'](self.Flow(), dict(ticket=101, yuanbao=200), {}, phase)


class SweepTests(unittest.TestCase):
    def exercise(self, mid, *, energy=20, remain=1, uncertain=False):
        module = importlib.import_module('new_sweep')
        pve = mid == 2200106
        cost = 5 if pve else 10
        state = dict(energy=energy, remain=remain)
        writes = []
        def enter(flow, slot):
            return dict(_id='synthetic_r0', power=3000000, sweepEnergy=state['energy'],
                        dungeon={str(mid): dict(passNum=1, star=3)},
                        dungeonTreasure={'1': dict(remainCnt=state['remain'])})
        class Flow:
            uid = 'synthetic'
            def request(self, route, params):
                if route == 'connector.roleHandler.getUserInfo':
                    return dict(code=200, user=dict(ticket=100, yuanbao=200))
                if route == 'scene.petPvpHandler.getPetPVPInfo':
                    return dict(code=200, petPve=dict(copy={str(mid): 1}, count=2-state['remain']))
                writes.append((route, params))
                if uncertain:
                    raise TimeoutError('synthetic timeout')
                state['energy'] -= cost
                state['remain'] -= 1
                return dict(code=200, give=[])
        def checked(reply, label):
            if reply.get('code') != 200 or reply.get('error'):
                raise RuntimeError(label)
            return reply
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tables = {'Sweep': {str(mid): dict(consumeId=1, dungeonTreasureShareId=1,
                       star=3, powerMin=1, name='synthetic')},
                      'ConsumeConfig': {'1': dict(consume_count=cost)},
                      'PetBattleHelperPve': {'1': dict(dayNumMax=2)}}
            for key, table in tables.items():
                (root / (key+'.json')).write_text(json.dumps(table), encoding='utf-8')
            with patch.object(module, 'config_table_path', lambda key: root/(key+'.json')), \
                 patch.object(module, 'enter', enter), patch.object(module, 'checked', checked):
                if uncertain:
                    with self.assertRaises(RuntimeError):
                        module.run(Flow(), 0, mid, report_dir=root, sleep=lambda _: None)
                    with self.assertRaises(RuntimeError):
                        module.run(Flow(), 0, mid, report_dir=root, sleep=lambda _: None)
                    self.assertEqual(len(writes), 1)
                else:
                    module.run(Flow(), 0, mid, report_dir=root, sleep=lambda _: None)
            return writes

    def test_three_route_shapes_and_free_quota(self):
        for mid in (300113, 40270, 2200106):
            with self.subTest(mid=mid):
                writes = self.exercise(mid)
                self.assertEqual(len(writes), 1)
                self.assertEqual(writes[0][0], 'scene.petPvpHandler.sweepPetPve' if mid == 2200106 else 'scene.copyHandler.sweep')
                self.assertEqual(writes[0][1]['mid'], mid)

    def test_no_energy_or_quota_sends_no_write(self):
        for mid in (300113, 40270, 2200106):
            with self.subTest(mid=mid):
                self.assertFalse(self.exercise(mid, energy=0))
                self.assertFalse(self.exercise(mid, remain=0))

    def test_uncertain_result_blocks_retry(self):
        self.exercise(2200106, uncertain=True)


if __name__ == '__main__':
    unittest.main()
