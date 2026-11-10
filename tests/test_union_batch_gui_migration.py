import sys,json,tempfile,unittest,os
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import union_batch_gui as ui
class MigrationTests(unittest.TestCase):
 def test_real_widgets_and_four_worker_commands(self):
  import tkinter as tk
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   root=tk.Tk();root.withdraw()
   try:
    window=ui.UnionBatchWindow(root);root.update_idletasks()
    self.assertFalse(window.jobs)
    account=Path(folder)/'account.json';account.write_text(json.dumps({'uid':'test','username':'fixture','cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']}}),encoding='utf8')
    window.slot.set('6');window.add_path(account);self.assertEqual(len(window.jobs),1)
    with patch.object(ui.messagebox,'showerror') as err:window.add_path(account);self.assertFalse(err.called)
    self.assertEqual(len(window.jobs),1)
    for action in ['boss','devote','garden','dog']:
     window.action.set(action)
     with patch.object(ui.subprocess,'Popen') as launch,patch.object(ui.threading.Thread,'start'):
      window.start();args=launch.call_args.args[0]
      self.assertEqual(args[args.index('--action')+1],action)
      rows=json.loads(Path(args[args.index('--batch-file')+1]).read_text(encoding='utf8'))
      self.assertEqual(rows[0]['slot'],6);self.assertNotIn('garden_password',rows[0])
      self.assertNotIn('cookies',rows[0]);window.cleanup();window.proc=None
   finally:root.destroy()
 def test_worker_password_environment_and_duplicate_rejection(self):
  import union_boss_batch as worker
  with tempfile.TemporaryDirectory() as folder:
   a=Path(folder)/'a.json';a.write_text(json.dumps({'uid':'u'}),encoding='utf8')
   batch=Path(folder)/'batch.json';batch.write_text(json.dumps([{'path':str(a),'slot':0}]),encoding='utf8')
   with patch.dict(os.environ,{'ZM5_UNION_BATCH_PASSWORDS':json.dumps({'u':'fixture-secret'})}):
    self.assertEqual(worker.load_jobs(batch)[0][0]['_garden_password'],'fixture-secret')
   batch.write_text(json.dumps([{'path':str(a),'slot':0},{'path':str(a),'slot':1}]),encoding='utf8')
   with self.assertRaises(ValueError):worker.load_jobs(batch)


class ScrollTests(unittest.TestCase):
 def test_small_window_scroll_reaches_bottom_and_native_log_is_preserved(self):
  import tkinter as tk
  from types import SimpleNamespace
  root=tk.Tk();root.withdraw()
  try:
   window=ui.UnionBatchWindow(root);root.geometry('640x480');root.update_idletasks()
   # Hidden windows do not receive layout sizes; explicitly size canvas for this widget test.
   window.canvas.configure(width=620,height=450);root.update_idletasks()
   window.canvas.configure(scrollregion=window.canvas.bbox('all'))
   self.assertGreater(window.scroll_body.winfo_reqheight(),450)
   window.canvas.yview_moveto(0)
   window.scroll_wheel(SimpleNamespace(widget=window.start_button,delta=-120,state=0))
   self.assertGreater(window.canvas.yview()[0],0)
   window.canvas.yview_moveto(1);self.assertAlmostEqual(window.canvas.yview()[1],1)
   old=window.canvas.yview()
   window.scroll_wheel(SimpleNamespace(widget=window.log,delta=120,state=0))
   self.assertEqual(old,window.canvas.yview())
  finally:root.destroy()


class DogCalendarFixTests(unittest.TestCase):
 def test_stale_year_queries_server_and_draws_once(self):
  import union_boss_batch as worker
  calls=[];drawn=[False]
  class F:
   def request(self,route,params):
    calls.append(route)
    if route.endswith('getDouble11Data'):return {'code':200,'data':{'dog_1':1} if drawn[0] else {}}
    if route.endswith('getUserInfo'):return {'code':200,'user':{'ticket':0}}
    if route.endswith('double11Lottery'):
     drawn[0]=True;return {'code':200,'give':[{'type':'coin','subType':'dog_1','count':1}]}
    raise AssertionError(route)
  with tempfile.TemporaryDirectory() as folder,patch.object(worker,'dog_calendar_check',return_value='旧配置'),patch('builtins.print'):
   prev=os.getcwd()
   try:
    os.chdir(folder);self.assertTrue(worker.run_dog({},0,'fixture',flow=F()))
   finally:os.chdir(prev)
  self.assertEqual(sum(x.endswith('double11Lottery') for x in calls),1)
 def test_current_expired_configuration_remains_blocked(self):
  import union_boss_batch as worker
  from types import SimpleNamespace
  from datetime import datetime,timezone
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder);(p/'Double11Common.json').write_text(json.dumps({'1':{'startActivityId':1}}),encoding='utf8')
   (p/'Activity.json').write_text(json.dumps({'1':{'underTime':'2026/01/01-00:00:00'}}),encoding='utf8')
   with patch('game_version.latest_config_folder',return_value=p),patch('game_version.beijing_now',return_value=datetime(2026,11,10,tzinfo=timezone.utc)),patch('activity_availability.require_open',side_effect=RuntimeError('已过期')) as check:
    with self.assertRaises(RuntimeError):worker.dog_calendar_check()
    check.assert_called_once_with('RUN_DOG_CARD')
 def test_exception_text_cannot_leak_login_secrets(self):
  import union_boss_batch as worker
  self.assertNotIn('private-secret',worker.dog_failure_reason(RuntimeError('token=private-secret')))


class MemoryTests(unittest.TestCase):
 def test_selection_roundtrip_no_password_and_no_start(self):
  import tkinter as tk
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   account=Path(folder)/'account.json';account.write_text(json.dumps({'uid':'fixture','cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']}}),encoding='utf8')
   root=tk.Tk();root.withdraw()
   try:
    one=ui.UnionBatchWindow(root);one.slot.set('6');one.add_path(account)
    one.jobs[next(iter(one.jobs))]['garden_password']='secret-fixture';one.save_selection()
    saved=one.settings_path.read_text(encoding='utf8');self.assertNotIn('secret-fixture',saved);self.assertNotIn('cookies',saved)
   finally:root.destroy()
   root=tk.Tk();root.withdraw()
   try:
    two=ui.UnionBatchWindow(root);self.assertEqual(len(two.jobs),1)
    row=next(iter(two.jobs.values()));self.assertEqual(row['slot'],6);self.assertNotIn('garden_password',row);self.assertIsNone(two.proc)
    two.table.selection_set(next(iter(two.jobs)));two.remove()
    self.assertEqual(json.loads(two.settings_path.read_text(encoding='utf8'))['accounts'],[])
   finally:root.destroy()


class LaunchOnceTests(unittest.TestCase):
 def test_script_creates_one_window_and_exits_after_mainloop(self):
  import runpy,tkinter as tk
  path=Path(ui.__file__)
  with patch.object(tk,'Tk') as factory,patch.object(ui.UnionBatchWindow,'__init__',return_value=None):
   # Execute entry block against a stub window class, without connecting or opening real GUI.
   import ast
   tree=ast.parse(path.read_text(encoding='utf8'))
   blocks=[n for n in tree.body if isinstance(n,ast.If) and '__name__' in ast.unparse(n.test)]
   self.assertEqual(len(blocks),1)
   fake_class=MagicMock();root=MagicMock();factory.return_value=root
   exec(compile(ast.Module(body=blocks,type_ignores=[]),str(path),'exec'),{'__name__':'__main__','tk':tk,'UnionBatchWindow':fake_class})
   factory.assert_called_once();fake_class.assert_called_once_with(root);root.mainloop.assert_called_once()


class PrivateAccountsTests(unittest.TestCase):
 def test_import_is_independent_and_survives_source_removal(self):
  import tkinter as tk
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   source=Path(folder)/'source.json';source.write_text(json.dumps({'uid':'123','username':'fixture','cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']},'password':'do-not-copy'}),encoding='utf8')
   root=tk.Tk();root.withdraw()
   try:
    window=ui.UnionBatchWindow(root);window.import_private_account(source)
    target=Path(folder)/'union_accounts/123.json'
    self.assertTrue(target.exists());self.assertFalse((Path(folder)/'accounts').exists())
    self.assertNotIn('password',json.loads(target.read_text(encoding='utf8')))
    self.assertIn('专用 · 123',window.files);source.unlink()
   finally:root.destroy()
   root=tk.Tk();root.withdraw()
   try:
    restored=ui.UnionBatchWindow(root);self.assertEqual(len(restored.jobs),1)
    self.assertEqual(Path(next(iter(restored.jobs.values()))['path']),target.resolve())
    self.assertIsNone(restored.proc)
   finally:root.destroy()


class IndependentLoginTests(unittest.TestCase):
 def test_saved_and_session_accounts_are_separate(self):
  import tkinter as tk
  from union_boss_batch import load_jobs
  account={'uid':'123','username':'fixture','cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']}}
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   root=tk.Tk();root.withdraw()
   try:
    w=ui.UnionBatchWindow(root);w.accept_login(account,False)
    self.assertFalse((Path(folder)/'union_accounts').exists())
    self.assertEqual(json.loads(w.settings_path.read_text(encoding='utf8'))['accounts'],[])
    batch=Path(folder)/'batch.json';batch.write_text(json.dumps([{'uid':'123','path':'','slot':0}]),encoding='utf8')
    with patch.dict(os.environ,{'ZM5_UNION_BATCH_ACCOUNTS':json.dumps({'123':account})}):self.assertEqual(load_jobs(batch)[0][0]['uid'],'123')
    w.accept_login(account,True);self.assertTrue((Path(folder)/'union_accounts/123.json').exists())
    self.assertNotIn('password',(Path(folder)/'union_accounts/123.json').read_text(encoding='utf8'))
   finally:root.destroy()
 def test_cookie_header_and_json(self):
  from union_batch_login import cookie_account
  cookies={'Pauth':'123|fixture','Uauth':'x','Xauth':'x','USESSIONID':'x'}
  self.assertEqual(cookie_account('test',json.dumps(cookies))['uid'],'123')
  self.assertEqual(cookie_account('test','; '.join(k+'='+v for k,v in cookies.items()))['uid'],'123')


class ExecutionMemoryTests(unittest.TestCase):
 def test_options_restore_without_running(self):
  import tkinter as tk
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   root=tk.Tk();root.withdraw()
   try:
    w=ui.UnionBatchWindow(root);w.action.set('dog');w.garden_pick.set(True);w.garden_uproot.set(True);w.garden_mode.set('buy');w.garden_count.set('2');w.idle.set(False);w.dps.set('123')
    seed=list(w.garden_seeds)[-1];w.garden_seed.set(seed);w.garden_seed.event_generate('<<ComboboxSelected>>');w.save_selection()
   finally:root.destroy()
   root=tk.Tk();root.withdraw()
   try:
    w=ui.UnionBatchWindow(root)
    self.assertEqual(w.action.get(),'dog');self.assertTrue(w.garden_pick.get());self.assertTrue(w.garden_uproot.get());self.assertEqual(w.garden_mode.get(),'buy');self.assertEqual(w.garden_count.get(),'2');self.assertFalse(w.idle.get());self.assertEqual(w.dps.get(),'123');self.assertEqual(w.garden_seed.get(),seed);self.assertIsNone(w.proc)
   finally:root.destroy()


class DogInventoryTests(unittest.TestCase):
 def test_all_cards_and_only_activated_spares_are_giftable(self):
  from union_boss_batch import dog_inventory
  rows=dog_inventory({'code':200,'data':{'dog_1':2,'dog_2':3,'dogPos':{'1':123}}})
  self.assertEqual(len(rows),11);self.assertEqual(rows[0]['giftable'],2);self.assertEqual(rows[1]['giftable'],0);self.assertEqual(rows[10]['count'],0)
 def test_query_only_reads(self):
  from union_boss_batch import query_dogs
  class F:
   def request(self,route,params):
    assert route=='scene.activityHandler.getDouble11Data'
    return {'code':200,'data':{}}
  with patch('builtins.print') as log:
   self.assertTrue(query_dogs({},0,'fixture',flow=F()))
   self.assertEqual(len(log.call_args_list),14)


class SlotCheckTests(unittest.TestCase):
 def test_empty_frozen_missing_and_unknown_stop(self):
  from teacher_trial import check_slot_records,SlotUnavailableError
  for records in [None,[],[{'index':1,'status':0}],[{'index':1,'status':3}],[{'index':1,'status':9}]]:
   with self.assertRaises(SlotUnavailableError):check_slot_records(records,1)
  self.assertEqual(check_slot_records([{'index':1,'status':1}],1)['index'],1)
 def test_empty_slot_stops_before_entry_and_does_not_retry_gate(self):
  import teacher_trial as t
  calls=[]
  class F:
   def __init__(self,**kw):pass
   def query_entry(self,*a):return ('host',1)
   def auth(self,*a):return {'code':200}
   def request(self,route,params):
    calls.append(route);return {'code':200,'user':{'records':[{'index':1,'status':0}]}}
   def disconnect(self):pass
  account={'uid':'1','username':'fixture','cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']}}
  with patch.object(t,'GameLoginFlow',F),patch.object(t,'fetch_game_token',return_value='fake'):
   with self.assertRaises(t.SlotUnavailableError):t.connect(account,1)
  self.assertEqual(calls,['connector.roleHandler.getUserInfo'])


class SlotPickerTests(unittest.TestCase):
 def test_roles_are_visible_but_slot_stays_numeric(self):
  import tkinter as tk
  choices,lines=ui.describe_slots([{'index':0,'status':0},{'index':1,'status':1,'p1':{'name':'孙悟空','level':40}},{'index':2,'status':3,'p1':{'name':'沙悟净','level':30}}])
  self.assertEqual(len(choices),1);self.assertIn('孙悟空 Lv40',choices[0]);self.assertIn('[空]',lines[0]);self.assertIn('[冻结]',lines[2])
  root=tk.Tk();root.withdraw()
  try:
   picker=ui.SlotPicker(root,values=choices);picker.set(choices[0]);self.assertEqual(picker.get(),'1')
  finally:root.destroy()


class CookiePasteTests(unittest.TestCase):
 def test_outer_quotes_and_unusual_browser_fields(self):
  from union_batch_login import cookie_account
  header='analytics=""; Pauth=123|fixture; Uauth=example|value; Xauth=x; USESSIONID=s; ck_accname=fixture; other=one%u1234; empty='
  for text in [header,'"'+header+'"',"'"+header+"'",'Cookie: '+header,json.dumps(header)]:
   account=cookie_account('',text);self.assertEqual(account['uid'],'123');self.assertEqual(account['username'],'fixture');self.assertNotIn('analytics',account['cookies'])
 def test_json_string_does_not_raise_attribute_error(self):
  from union_batch_login import cookie_account
  with self.assertRaises(ValueError):cookie_account('fixture','"invalid"')


class DuplicateUpdateTests(unittest.TestCase):
 def test_saved_login_readd_updates_slot_and_keeps_one_account(self):
  import tkinter as tk
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   root=tk.Tk();root.withdraw()
   try:
    w=ui.UnionBatchWindow(root);a={'uid':'123','username':'fixture','cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']}}
    w.accept_login(a,True);key=next(iter(w.jobs));w.jobs[key]['garden_password']='fixture-secret'
    w.slot.set('1');w.add_selected()
    self.assertEqual(len(w.jobs),1);self.assertEqual(w.jobs[key]['slot'],1);self.assertNotIn('garden_password',w.jobs[key])
    saved=json.loads(w.settings_path.read_text(encoding='utf8'));self.assertEqual(saved['accounts'][0]['slot'],1)
   finally:root.destroy()


class ActivateDogsTests(unittest.TestCase):
 def test_only_available_unactivated_selected_cards_are_consumed(self):
  import union_boss_batch as worker,copy
  class F:
   def __init__(self):self.data={'dog_1':2,'dog_2':1,'dogPos':{'2':123}};self.writes=[]
   def request(self,route,params):
    if route.endswith('getDouble11Data'):return {'code':200,'data':copy.deepcopy(self.data)}
    if route.endswith('getUserInfo'):return {'code':200,'user':{'ticket':7,'yuanbao':9}}
    assert route.endswith('activeDouble11Dog');self.writes.append(params);self.data['dog_1']-=1;self.data['dogPos']['1']=456;return {'code':200}
  flow=F()
  with tempfile.TemporaryDirectory() as folder,patch('builtins.print'):
   old=os.getcwd()
   try:os.chdir(folder);self.assertTrue(worker.activate_dogs({},0,'fixture',[1,2,3],flow=flow))
   finally:os.chdir(old)
  self.assertEqual(flow.writes,[{'id':1,'type':0}])
 def test_default_selection_only_pomeranian(self):
  import tkinter as tk
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   root=tk.Tk();root.withdraw()
   try:
    w=ui.UnionBatchWindow(root);self.assertEqual([k for k,v in w.dog_activation.items() if v.get()],['dog_activate_1'])
   finally:root.destroy()


class OverviewTests(unittest.TestCase):
 def test_inventory_renders_into_account_row(self):
  import tkinter as tk
  from union_boss_batch import dog_inventory
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   root=tk.Tk();root.withdraw()
   try:
    w=ui.UnionBatchWindow(root);w.accept_login({'uid':'123','username':'fixture','cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']}},False);key=next(iter(w.jobs))
    w.table.selection_set(key)
    w.render_dog_overview({'uid':'123','slot':0,'status':'ok','cards':dog_inventory({'code':200,'data':{'dog_1':2,'dogPos':{'1':1}}}),'daily':{'double11LotteryCnt':1}})
    self.assertIn('giftable',w.table.item(key,'tags'));self.assertIn('2 / ✓已激活',w.table.item(key,'values')[6]);self.assertIn('已激活1/11',w.dog_detail.get());self.assertIn('giftable',w.dog_detail_table.item('1','tags'));self.assertIn('empty',w.dog_detail_table.item('2','tags'))
    with patch.object(w,'start') as start:w.refresh_selected_dogs();self.assertEqual(start.call_args.kwargs['job_keys'],w.table.selection())
   finally:root.destroy()


class GiftFilterTests(unittest.TestCase):
 def test_filter_does_not_treat_unknown_as_not_gifted(self):
  import tkinter as tk
  from union_boss_batch import dog_inventory
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   root=tk.Tk();root.withdraw()
   try:
    w=ui.UnionBatchWindow(root)
    for uid in ['1','2','3']:w.accept_login({'uid':uid,'username':'fixture'+uid,'cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']}},False)
    cards=dog_inventory({'code':200,'data':{}})
    w.render_dog_overview({'uid':'1','slot':0,'status':'ok','cards':cards,'daily':{'addDouble11LotteryCnt':1}})
    w.render_dog_overview({'uid':'2','slot':0,'status':'ok','cards':cards,'daily':{}})
    w.dog_filter.set('今日未赠送');visible=w.table.get_children();self.assertEqual(len(visible),1);self.assertEqual(w.jobs[visible[0]]['uid'],'2')
    w.dog_filter.set('今日已赠送');visible=w.table.get_children();self.assertEqual(len(visible),1);self.assertEqual(w.jobs[visible[0]]['uid'],'1')
    w.dog_filter.set('全部');self.assertEqual(len(w.table.get_children()),3);self.assertEqual(len(w.jobs),3)
   finally:root.destroy()


class CombinedFilterTests(unittest.TestCase):
 def test_activation_and_today_filters_intersect(self):
  import tkinter as tk
  from union_boss_batch import dog_inventory
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   root=tk.Tk();root.withdraw()
   try:
    w=ui.UnionBatchWindow(root)
    for uid in ['1','2','3','4']:w.accept_login({'uid':uid,'username':'fixture'+uid,'cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']}},False)
    for uid,pos,extra in [('1',{'1':1},0),('2',{'2':1},1),('3',{},0)]:w.render_dog_overview({'uid':uid,'slot':0,'status':'ok','cards':dog_inventory({'code':200,'data':{'dogPos':pos}}),'daily':{'addDouble11LotteryCnt':extra}})
    def shown():return [w.jobs[k]['uid'] for k in w.table.get_children()]
    w.dog_activation_filter.set('已激活博美汪');self.assertEqual(shown(),['1'])
    w.dog_activation_filter.set('已激活斗牛汪');self.assertEqual(shown(),['2'])
    w.dog_filter.set('今日未赠送');self.assertEqual(shown(),[])
    w.dog_activation_filter.set('两种都未激活');self.assertEqual(shown(),['3'])
    w.dog_activation_filter.set('全部');w.dog_filter.set('全部');self.assertEqual(len(shown()),4)
   finally:root.destroy()


class ChainLaunchTests(unittest.TestCase):
 def test_chain_only_passes_visible_accounts_and_selected_card(self):
  import tkinter as tk
  from union_boss_batch import dog_inventory
  with tempfile.TemporaryDirectory() as folder,patch.object(ui,'HERE',Path(folder)):
   root=tk.Tk();root.withdraw()
   try:
    w=ui.UnionBatchWindow(root)
    for uid in ['1','2']:w.accept_login({'uid':uid,'username':'fixture'+uid,'cookies':{k:'fake' for k in ['Pauth','Uauth','Xauth','USESSIONID']}},False)
    cards=dog_inventory({'code':200,'data':{'dog_5':1,'dogPos':{'5':1}}})
    for uid,bonus in [('1',0),('2',1)]:w.render_dog_overview({'uid':uid,'slot':0,'status':'ok','cards':cards,'daily':{'addDouble11LotteryCnt':bonus}})
    w.dog_filter.set('今日未赠送');w.chain_card.set('金毛汪');w.chain_seed.set('使用名单中余卡')
    with patch.object(ui.messagebox,'askyesno',return_value=True),patch.object(ui.subprocess,'Popen') as launch,patch.object(ui.threading.Thread,'start'):
     w.start(action_override='dog_chain',job_keys=w.table.get_children());args=launch.call_args.args[0]
     self.assertEqual(args[args.index('--chain-card')+1],'5');self.assertEqual(args[args.index('--chain-seed')+1],'inventory')
     batch=json.loads(Path(args[args.index('--batch-file')+1]).read_text(encoding='utf8'));self.assertEqual(len(batch),1);self.assertEqual(batch[0]['uid'],'1')
     self.assertNotIn('cookies',batch[0]);w.cleanup();w.proc=None
   finally:root.destroy()
