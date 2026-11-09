"""Offline regression checks: no login, configuration files or game requests."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('boss_model_under_test', ROOT / 'app/world_boss_model.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)

class BossModelTests(unittest.TestCase):
    def bare_model(self):
        obj = model.WorldBossModel.__new__(model.WorldBossModel)
        obj.panel = {'atk': 100, '_pk': 'p1'}
        obj.boss_def = 0
        obj.mp_max = obj.mp = 100
        obj.re_mp = 0
        obj.ready = {}
        obj.normal_next = obj.action_ready = 0
        obj.crit_rate = 0
        obj.crit_mult = 2
        obj.normal_id = 10
        obj.bar = [11, 12]
        obj.skills = {i: {'id': i, 'hits': 1, 'fixed': 0, 'coef': 1,
                         'subs': [], 'cd': 10, 'mp': 0, 'stiff': 2,
                         'damage': True} for i in (10, 11, 12)}
        return obj

    def test_skill_bar_tracks_selected_character(self):
        obj = self.bare_model()
        obj.info = {'_id': 'sample', 'clientStore': {
            'sample-setKeyboard-0': {'skill1': 11},
            'sample-setKeyboard-1': {'skill1': 22}}}
        self.assertEqual(obj._skill_bar(), [11])
        obj.panel['_pk'] = 'p2'
        self.assertEqual(obj._skill_bar(), [22])
        del obj.info['clientStore']['sample-setKeyboard-1']
        self.assertEqual(obj._skill_bar(), [])

    def test_action_time_blocks_other_ready_skill(self):
        obj = self.bare_model()
        with patch.object(model.random, 'uniform', side_effect=lambda a, b: (a+b)/2):
            _, gap = obj.cast(11, 100)
        self.assertGreater(gap, 0.6)
        self.assertIsNone(obj.choose(100.6))
        self.assertEqual(obj.choose(100 + gap), 12)
        self.assertEqual(obj.ready[11], 110)

    def test_revive_supports_restarted_clock(self):
        obj = self.bare_model()
        obj.ready = {11: 120, 12: 130}
        obj.normal_next = obj.action_ready = 115
        obj.mp = 0
        obj.reset_after_revive()
        self.assertEqual(obj.mp, 100)
        self.assertEqual(obj.ready, {})
        self.assertEqual(obj.choose(0), 11)

    def test_normal_attack_also_respects_action_time(self):
        obj = self.bare_model()
        obj.bar = []
        with patch.object(model.random, 'uniform', side_effect=lambda a, b: (a+b)/2):
            obj.cast(10, 0)
        self.assertIsNone(obj.choose(0.6))
        self.assertEqual(obj.choose(10), 10)

if __name__ == '__main__':
    unittest.main()
