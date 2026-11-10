import sys,json,tempfile,unittest,copy
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import dog_card_chain as chain
class Tests(unittest.TestCase):
 def run_case(self,card,mode,fail=False):
  states={'a':{'dogPos':{str(card):1},'dog_'+str(card):0},'b':{'dogPos':{str(card):1},'dog_'+str(card):1},'c':{'dogPos':{}},'d':{'dogPos':{str(card):1}}};events=[]
  def connect(a,s):
   uid=a['uid']
   class F:
    def request(self,r,p):return {'code':200,'data':states[uid]}
    def disconnect(self):pass
   f=F();f.uid=uid
   return f,{'uid':uid,'everyDaySetting':{'addDouble11LotteryCnt':1 if uid=='d' else 0}}
  def executor(f,s,action,ids,code,save,**kw):
   events.append((f.uid,action,ids,code));save({'status':'running','requests':[{'phase':'pending'}]})
   if fail and f.uid=='b':raise TimeoutError()
   return {'generated_code':'next-'+f.uid,'status':'complete'}
  jobs=[({'uid':uid},0) for uid in states]
  with tempfile.TemporaryDirectory() as folder,patch('builtins.print'):
   if fail:
    with self.assertRaises(TimeoutError):chain.run_chain(jobs,card,mode,'fixture-code',folder,connect,executor)
    r=json.loads(next(Path(folder).glob('*.private.json')).read_text(encoding='utf8'));self.assertEqual(r['status'],'stopped')
    with self.assertRaises(ValueError):chain.run_chain(jobs,card,mode,'fixture-code',folder,connect,executor)
   else:
    r=chain.run_chain(jobs,card,mode,'fixture-code',folder,connect,executor);self.assertEqual(len(r['completed']),2);self.assertTrue(r['current_code'])
  return events
 def test_input_code_two_eligible_accounts_only(self):
  events=self.run_case(2,'code');self.assertEqual([(e[0],e[1]) for e in events],[('a','redeem'),('a','gift_draw'),('b','redeem'),('b','gift_draw')])
 def test_other_card_and_inventory_source_first(self):
  events=self.run_case(5,'inventory');self.assertEqual([(e[0],e[1]) for e in events],[('b','gift_draw'),('a','redeem'),('a','gift_draw')]);self.assertTrue(all(e[2]==[5] for e in events))
 def test_uncertain_stops_and_blocks_replay(self):
  events=self.run_case(2,'code',True);self.assertEqual(len(events),3)
