"""Validate feeding plans only; no account files, feeding requests or network."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from my_daily_catalog import validate_plan

KEY='RUN_FUN_FAIRY_FEED'

def plan(role=0,times=None):
    args={'entity_id':'dummy_r0_fairy','times':times,'use_item':False}
    if role is not None:args['role']=role
    return {'uid':'dummy','slot':0,'jobs':[{'kind':'feed','label':'幻兽喂养','args':args}]}

class FeedingPlanTests(unittest.TestCase):
    def test_both_roles_and_requested_or_daily_limit_counts(self):
        for role in (0,1):
            for count in (None,1,10,20,30):
                with self.subTest(role=role,count=count):
                    item=plan(role,count);original=copy.deepcopy(item)
                    self.assertEqual(validate_plan([KEY],item,'dummy',0),item['jobs'])
                    self.assertEqual(item,original)

    def test_legacy_roleless_plan(self):
        item=plan(None,None)
        self.assertEqual(validate_plan([KEY],item,'dummy',0),item['jobs'])

    def test_invalid_role_is_rejected(self):
        for role in (-1,2,'0'):
            with self.subTest(role=role),self.assertRaises(ValueError):
                validate_plan([KEY],plan(role),'dummy',0)

    def test_zero_negative_or_non_integer_count_rejected(self):
        for count in (0,-1,'20',True,1.5):
            with self.subTest(count=count),self.assertRaises(ValueError):
                validate_plan([KEY],plan(0,count),'dummy',0)

    def test_extra_arguments_and_wrong_identity_rejected(self):
        item=plan();item['jobs'][0]['args']['unexpected']=True
        with self.assertRaises(ValueError):validate_plan([KEY],item,'dummy',0)
        with self.assertRaises(ValueError):validate_plan([KEY],plan(),'other',0)
        with self.assertRaises(ValueError):validate_plan([KEY],plan(),'dummy',1)

    def test_other_job_combination_still_valid(self):
        item=plan()
        item['jobs'].insert(0,{'kind':'card','label':'妖王帖免费抽取','args':{'count':1}})
        self.assertEqual(validate_plan(['RUN_FUN_MONSTER_CARD',KEY],item,'dummy',0),item['jobs'])

if __name__=='__main__':unittest.main()
