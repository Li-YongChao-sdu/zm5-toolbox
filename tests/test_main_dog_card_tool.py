import unittest,sys,copy
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import dog_card_tool as tool
class Flow:
 def __init__(self):self.d={'dog_1':2,'dogPos':{'1':1}};self.daily={'double11LotteryCnt':1};self.calls=[]
 def request(self,route,params):
  self.calls.append(route)
  if route.endswith('getDouble11Data'):return {'code':200,'data':copy.deepcopy(self.d)}
  if route.endswith('getUserInfo'):return {'code':200,'user':{'ticket':7,'yuanbao':9}}
  if route.endswith('double11Dog2Code'):
   self.d['dog_1']-=1;self.daily['addDouble11LotteryCnt']=1;return {'code':200,'cdkey':'fixture-code','everyDaySetting':copy.deepcopy(self.daily)}
  if route.endswith('double11Lottery'):
   self.d['dog_2']=1;self.daily['double11LotteryCnt']=2;return {'code':200,'give':[{'type':'coin','subType':'dog_2','count':1}],'everyDaySetting':copy.deepcopy(self.daily)}
  if route.endswith('double11Code2Dog'):
   self.d['dog_1']+=1;return {'code':200,'give':[{'type':'coin','subType':'dog_1','count':1}]}
  raise AssertionError(route)
class Tests(unittest.TestCase):
 def run_action(self,f,action):
  with patch.object(tool,'enter',side_effect=lambda f,s:{'_id':'fixture_r0','everyDaySetting':copy.deepcopy(f.daily)}),patch('builtins.print'):
   return tool.execute(f,0,action,[1],'fixture-code',lambda r:None,sleep=lambda n:None)
 def test_single_gift_then_one_draw(self):
  f=Flow();r=self.run_action(f,'gift_draw');self.assertEqual(r['status'],'complete');self.assertEqual(f.calls.count('scene.activityHandler.double11Dog2Code'),1);self.assertEqual(f.calls.count('scene.activityHandler.double11Lottery'),1)
 def test_used_bonus_does_not_consume_card(self):
  f=Flow();f.daily['addDouble11LotteryCnt']=1
  with self.assertRaises(ValueError):self.run_action(f,'gift_draw')
  self.assertFalse(any(x.endswith('double11Dog2Code') for x in f.calls))
 def test_redeem_no_activation(self):
  f=Flow();r=self.run_action(f,'redeem');self.assertEqual(r['after']['cards'][0]['count'],3);self.assertFalse(any(x.endswith('activeDouble11Dog') for x in f.calls))
 def test_already_active_skips(self):
  f=Flow();self.run_action(f,'activate');self.assertFalse(any(x.endswith('activeDouble11Dog') for x in f.calls))
 def test_unknown_gift_result_does_not_draw_or_retry(self):
  f=Flow();original=f.request
  def lost(route,p):
   if route.endswith('double11Dog2Code'):f.calls.append(route);raise TimeoutError()
   return original(route,p)
  f.request=lost
  with self.assertRaises(TimeoutError):self.run_action(f,'gift_draw')
  self.assertEqual(f.calls.count('scene.activityHandler.double11Dog2Code'),1);self.assertNotIn('scene.activityHandler.double11Lottery',f.calls)


class TableTests(unittest.TestCase):
 def test_result_renders_in_window_and_rejects_other_account(self):
  import tkinter as tk,tempfile,json
  from types import SimpleNamespace
  import dog_card_ui as ui
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'ROOT',Path(folder)):
   Path(folder,'account.local.json').write_text(json.dumps({'uid':'fixture'}),encoding='utf8')
   root=tk.Tk();root.withdraw()
   try:
    app=SimpleNamespace(root=root,running=False,cmb_slot=SimpleNamespace(get=lambda:'0'))
    ui.open_window(app);app.dog_card_window.withdraw()
    from union_boss_batch import dog_inventory
    app.render_dog_cards({'uid':'fixture','slot':0,'state':{'cards':dog_inventory({'code':200,'data':{'dog_1':2,'dog_2':1,'dogPos':{'1':123,'3':456}}}),'daily':{'double11LotteryCnt':1}},'message':'查询完成'})
    self.assertEqual(len(app.dog_card_table.get_children()),11)
    self.assertIn('giftable',app.dog_card_table.item('1','tags'))
    self.assertIn('ready',app.dog_card_table.item('2','tags'))
    self.assertIn('active',app.dog_card_table.item('3','tags'))
    self.assertIn('empty',app.dog_card_table.item('4','tags'))
    self.assertEqual(str(app.dog_card_table.item('1','values')[1]),'2')
    self.assertIn('查询完成',app.dog_card_status.get())
    app.render_dog_cards({'uid':'other','slot':0});self.assertIn('忽略旧结果',app.dog_card_status.get())
   finally:root.destroy()
