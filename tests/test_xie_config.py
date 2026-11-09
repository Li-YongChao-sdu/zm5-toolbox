"""Configuration rotation regressions; no account login or game requests."""
import json
import ast
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP))
import game_version as version
import game_config_sync as sync
import activity_availability as availability

NOW = datetime(2026, 11, 5, 12, tzinfo=version.BEIJING)

def activity(mid, start='2026/11/2-00:00:00', end='2026/11/9-23:59:59', **extra):
    return dict(dungeonId=str(mid), shelfTime=start, underTime=end,
                weekDay='0;1;2;3;4;5;6', **extra)

def write_config(root, name, rows):
    folder = Path(root) / ('cg_config_out_' + name)
    folder.mkdir()
    for key in sync.KEY_TABLES:
        (folder / (key + '.json')).write_text(json.dumps(rows if key == 'Activity' else {'1': {}}), encoding='utf-8')
    return folder

class XieConfigTests(unittest.TestCase):
    def test_current_real_config(self):
        state = version.xie_activity_state(NOW, APP)
        self.assertEqual(set(state['active']), {'RUN_ACT_XSHASENG', 'RUN_ACT_XYANGJIAN'})
        self.assertFalse(state['error'])

    def test_new_week_and_numeric_hotfix(self):
        with tempfile.TemporaryDirectory() as root:
            write_config(root, 'cg1_20261026_1', {'1': activity(500123)})
            write_config(root, 'cg1_20261102_2', {'1': activity(500125)})
            write_config(root, 'cg1_20261102_10', {'1': activity(500121)})
            write_config(root, 'cg1_20261109_1', {'1': activity(500137)})
            self.assertEqual(version.active_xie_switches(NOW, root), {'RUN_ACT_XYANGJIAN'})
            self.assertEqual(version.active_xie_switches(NOW.replace(day=9), root), {'RUN_ACT_XYAOYAO'})

    def test_time_window_not_show_window(self):
        with tempfile.TemporaryDirectory() as root:
            write_config(root, 'cg1_20261102_1', {
                'old': activity(500123, end='2026/11/4-23:59:59'),
                'future': activity(500125, start='2026/11/6-00:00:00', showShelfTime='2026/11/1-00:00:00'),
                'live': activity(500121, start='2026/11/5-12:00:00', end='2026/11/5-12:00:00'),
            })
            self.assertEqual(version.active_xie_switches(NOW, root), {'RUN_ACT_XYANGJIAN'})
            self.assertEqual(version.active_xie_switches(NOW + timedelta(seconds=1), root), set())

    def test_timezone_and_weekday(self):
        with tempfile.TemporaryDirectory() as root:
            row = activity(500125)
            row['weekDay'] = '4'  # Thursday in the official Sunday=0 convention.
            write_config(root, 'cg1_20261102_1', {'1': row})
            self.assertEqual(version.active_xie_switches(NOW.astimezone(timezone.utc), root), {'RUN_ACT_XSHASENG'})
            self.assertEqual(version.active_xie_switches(NOW.replace(day=6), root), set())

    def test_corrupt_latest_does_not_reenable_old_rotation(self):
        with tempfile.TemporaryDirectory() as root:
            write_config(root, 'cg1_20261026_1', {'1': activity(500123)})
            folder = write_config(root, 'cg1_20261102_1', {'1': activity(500125)})
            (folder / 'Activity.json').write_text('{broken', encoding='utf-8')
            state = version.xie_activity_state(NOW, root)
            self.assertFalse(state['active'])
            self.assertTrue(state['error'])

    def test_invalid_or_missing_config(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(version.xie_activity_state(NOW, root)['error'])
            write_config(root, 'cg1_20261102_1', {'1': activity(500125, start='invalid')})
            self.assertFalse(version.active_xie_switches(NOW, root))

    def test_same_process_picks_up_new_file(self):
        with tempfile.TemporaryDirectory() as root:
            folder = write_config(root, 'cg1_20261102_1', {'1': activity(500125)})
            self.assertEqual(version.active_xie_switches(NOW, root), {'RUN_ACT_XSHASENG'})
            (folder / 'Activity.json').write_text(json.dumps({'1': activity(500121), '2': activity(500137)}), encoding='utf-8')
            self.assertEqual(version.active_xie_switches(NOW, root), {'RUN_ACT_XYANGJIAN', 'RUN_ACT_XYAOYAO'})

    def test_no_hardcoded_tang_window_after_config_update(self):
        with tempfile.TemporaryDirectory() as root:
            write_config(root, 'cg1_20261102_1', {'1': activity(500116)})
            with patch.object(version, 'ROOT', Path(root)):
                self.assertEqual(availability.disabled_reason('RUN_ACT_XTANG', NOW), '')

    def test_failed_unpack_keeps_previous_config(self):
        with tempfile.TemporaryDirectory() as root:
            folder = write_config(root, 'cg1_20261102_1', {'1': activity(500125)})
            before = (folder / 'Activity.json').read_bytes()
            def incomplete(data, out):
                Path(out).mkdir()
                (Path(out) / 'Activity.json').write_text('{}')
                return {}, ['Activity'], []
            with patch.object(sync, 'unpack', side_effect=incomplete):
                with self.assertRaisesRegex(RuntimeError, '关键表缺失'):
                    sync.install_config(b'dummy', 'cg1_20261102_1.swf', root, log=lambda _: None)
            self.assertEqual((folder / 'Activity.json').read_bytes(), before)
            self.assertFalse(list(Path(root).glob('.cg1_unpack_*')))

    def test_discovery_uses_beijing_week_and_latest_hotfix(self):
        def head(name):
            return (200, 100) if name in ('cg1_20261102_1.swf', 'cg1_20261102_2.swf') else (404, 0)
        with patch.object(sync, 'head', side_effect=head):
            self.assertEqual(sync.discover(today=NOW.date())['name'], 'cg1_20261102_2.swf')

    def test_backend_rechecks_even_when_old_saved_switch_is_true(self):
        tree=ast.parse((APP/'daily_auto.py').read_text(encoding='utf-8-sig'))
        func=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='run_activity')
        namespace={'ACTIVITIES':[{'name':'邪·八戒'}], 'RUN_ACT_XBAJIE':True,
                   '_activity_disabled_reason':lambda key:'当前配置未开放',
                   'xie_status_text':lambda:'test configuration', 'print':lambda *a:None}
        exec(compile(ast.Module(body=[func],type_ignores=[]),'backend_guard','exec'),namespace)
        # The minimal row/flow would fail immediately if execution got past the guard.
        self.assertIsNone(namespace['run_activity'](object(),{}))

if __name__ == '__main__':
    unittest.main()
