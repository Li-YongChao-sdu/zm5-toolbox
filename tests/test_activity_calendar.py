"""Dynamic activity dates and frontend/backend boundary checks; no online account."""
import ast
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1]/'app'
sys.path.insert(0,str(APP))
import game_version as version
import activity_availability as availability
NOW=datetime(2026,11,5,12,tzinfo=version.BEIJING)

def row(mid='-1', name='test', start='2026/11/1-00:00:00', end='2026/11/9-23:59:59', **extra):
    return dict(id=1,name=name,dungeonId=str(mid),shelfTime=start,underTime=end,
                showUnderTime=extra.pop('showUnderTime',end),**extra)

def config(root, rows, name='cg1_20261102_1', **tables):
    folder=Path(root)/('cg_config_out_'+name);folder.mkdir()
    for key in ('Activity','Pet','Shop','Dungeon','Prop'):
        (folder/(key+'.json')).write_text(json.dumps(rows if key=='Activity' else {'1':{}}),encoding='utf-8')
    for key,value in tables.items():
        (folder/(key+'.json')).write_text(json.dumps(value),encoding='utf-8')
    return folder

class ActivityCalendarTests(unittest.TestCase):
    def test_real_config_boundaries_and_links(self):
        states=availability.availability_snapshot(NOW,APP)
        expected={'RUN_ACT_XINGTIAN':(2068,'open'),'RUN_ACT_GM':(2054,'expired'),
                  'RUN_ACT_FIGHT_GM':(2073,'open'),'RUN_CLOUD_LADDER':(2067,'open'),
                  'RUN_CLIMB_HIGH':(2066,'expired'),'RUN_XUANTA_EVENT':(30,'expired'),
                  'RUN_MAGIC_CRYSTAL':(2071,'open'),'RUN_REBIRTH_TRIAL':(2070,'expired'),
                  'RUN_REBIRTH_REWARD':(2070,'open')}
        for key,(aid,status) in expected.items():
            self.assertEqual((states[key]['id'],states[key]['status']),(aid,status),key)

    def test_gm_routes_are_separate_and_shop_is_not_challenge(self):
        with tempfile.TemporaryDirectory() as root:
            config(root,{'1':row('500120;500127',end='2026/11/4-23:59:59'),
                         '2':row('500112;500113'), '3':row(name='挑战GM商店')})
            states=availability.availability_snapshot(NOW,root)
            self.assertEqual(states['RUN_ACT_GM']['status'],'expired')
            self.assertEqual(states['RUN_ACT_FIGHT_GM']['status'],'open')

    def test_helper_selects_current_period_not_old_same_name(self):
        with tempfile.TemporaryDirectory() as root:
            config(root,{'1':row(name='登云梯'),'2':row(name='登云梯',end='2026/11/4-23:59:59')},
                   CloudLadderHelp={'1':{'activityId':2}})
            states=availability.availability_snapshot(NOW,root)
            self.assertEqual(states['RUN_CLOUD_LADDER']['status'],'expired')

    def test_date_change_same_process_and_no_xie_change(self):
        with tempfile.TemporaryDirectory() as root:
            folder=config(root,{'1':row('500105;500111')})
            self.assertEqual(availability.availability_snapshot(NOW,root)['RUN_ACT_XINGTIAN']['status'],'open')
            (folder/'Activity.json').write_text(json.dumps({'1':row('500105;500111',end='2026/11/4-23:59:59')}),encoding='utf-8')
            self.assertEqual(availability.availability_snapshot(NOW,root)['RUN_ACT_XINGTIAN']['status'],'expired')

    def test_new_week_dates_do_not_need_source_constant_change(self):
        with tempfile.TemporaryDirectory() as root:
            config(root,{'1':row('500105;500111',end='2026/11/4-23:59:59')})
            config(root,{'9000':row('500105;500111',end='2026/12/31-23:59:59')},name='cg1_20261102_2')
            self.assertEqual(availability.availability_snapshot(NOW,root)['RUN_ACT_XINGTIAN']['status'],'open')

    def test_task_id_is_not_activity_id(self):
        with tempfile.TemporaryDirectory() as root:
            config(root,{'30':row(end='2026/11/4-23:59:59'),'2014':row()},
                   TaskType={'2014':{'name':'玄塔有灵','activityId':30}})
            self.assertEqual(availability.availability_snapshot(NOW,root)['RUN_XUANTA_EVENT']['status'],'expired')

    def test_rebirth_reward_uses_show_end_not_challenge_end(self):
        with tempfile.TemporaryDirectory() as root:
            config(root,{'1':row(name='轮回试炼-测试',end='2026/11/4-23:59:59',showUnderTime='2026/11/9-23:59:59')})
            states=availability.availability_snapshot(NOW,root)
            self.assertEqual(states['RUN_REBIRTH_TRIAL']['status'],'expired')
            self.assertEqual(states['RUN_REBIRTH_REWARD']['status'],'open')
            self.assertEqual(states['RUN_MODULE_DCE2B544B5171119']['status'],'expired')
            self.assertEqual(states['RUN_MODULE_2A934499C1CD4B2E']['status'],'open')

    def test_future_preview_does_not_open_challenge(self):
        with tempfile.TemporaryDirectory() as root:
            config(root,{'1':row('500105;500111',start='2026/11/6-00:00:00',showShelfTime='2026/11/1-00:00:00')})
            self.assertEqual(availability.availability_snapshot(NOW,root)['RUN_ACT_XINGTIAN']['status'],'future')

    def test_invalid_helper_does_not_fall_back_to_another_period(self):
        with tempfile.TemporaryDirectory() as root:
            config(root,{'1':row(name='登云梯')},CloudLadderHelp={'1':{'activityId':999}})
            self.assertEqual(availability.availability_snapshot(NOW,root)['RUN_CLOUD_LADDER']['status'],'unknown')

    def test_bad_config_hides_and_blocks_only_managed_features(self):
        with tempfile.TemporaryDirectory() as root:
            folder=config(root,{'1':row('500105;500111')})
            (folder/'Activity.json').write_text('{bad',encoding='utf-8')
            with patch.object(version,'ROOT',Path(root)):
                self.assertTrue(availability.hidden_activity('RUN_ACT_XINGTIAN'))
                with self.assertRaises(RuntimeError):availability.require_open('RUN_ACT_XINGTIAN')
                self.assertEqual(availability.disabled_reason('RUN_NINE_TOWER'),'')

    def test_closing_boundary_no_version_reload(self):
        with tempfile.TemporaryDirectory() as root:
            config(root,{'1':row('500105;500111',end='2026/11/5-12:00:00')})
            self.assertEqual(availability.availability_snapshot(NOW,root)['RUN_ACT_XINGTIAN']['status'],'open')
            self.assertEqual(availability.availability_snapshot(NOW+timedelta(seconds=1),root)['RUN_ACT_XINGTIAN']['status'],'expired')

    def test_backend_stops_before_first_request_when_expired(self):
        from climb_high import run as climb
        from crystal_manual import run as crystal
        from rabbit_activity import run as rabbit
        from rebirth_trial import run as rebirth
        with tempfile.TemporaryDirectory() as root:
            config(root,{'1':row(end='2026/11/4-23:59:59')})
            with patch.object(version,'ROOT',Path(root)):
                for call in (lambda:climb(object(),{},0),lambda:crystal(object(),0),
                             lambda:rabbit(object(),{},0),lambda:rebirth(object(),{},None,None)):
                    with self.assertRaisesRegex(RuntimeError,'未执行该活动'):call()

    def test_daily_direct_functions_guard_without_network(self):
        tree=ast.parse((APP/'daily_auto.py').read_text(encoding='utf-8-sig'))
        names={'run_mid_autumn','run_jin_qiu','run_cloud_ladder','run_relic_treasure','run_xuanta_event','claim_dragon_treasure_tasks'}
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        namespace={'_activity_disabled_reason':lambda key:'已过期','print':lambda *args:None}
        exec(compile(ast.Module(body=functions,type_ignores=[]),'daily_guards','exec'),namespace)
        for name in names:
            args=(object(),) if name=='run_relic_treasure' else (object(),{})
            namespace[name](*args)

if __name__=='__main__':unittest.main()
