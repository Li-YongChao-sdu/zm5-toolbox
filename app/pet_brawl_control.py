"""乱斗准备信息及手动操作；请求在原房间连接上串行执行。"""
import copy,json,math,queue,threading,time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
ATTRS='hpMax atk phyDef reHP hit dodge critical toughness lucky guardian'.split()
RESISTS='lightResist darkResist waterResist fireResist woodResist soilResist windResist rayResist'.split()
LABELS='生命 攻击 防御 回血 命中 闪避 暴击 韧性 幸运 守护 光抗 暗抗 水抗 火抗 木抗 土抗 风抗 雷抗'.split()

def valid_indices(values,pets):
 return list(dict.fromkeys(i for i in (values or []) if type(i) is int and 0<=i<len(pets)))

def round_results(winners,players,uid):
 me=next((p for p in players if str(p.get('playerId'))==str(uid)),{})
 own=me.get('rid')
 opponents={str(p['rid']) for p in players if p.get('rid') and str(p.get('playerId'))!=str(uid)}
 return ['平' if winner=='' else '胜' if own and str(winner)==str(own) else '负' if str(winner) in opponents else '待确认' for winner in winners]

class Catalog:
 def __init__(self):
  self.data={}
  for name in ['Pet','PetBattleLocker','PetBattleLockerAtt','PetElf','PetElfAtt','PetCharacter','Common','PetBattleFuLu','PetPerks']:
   path=ROOT/'feature_config'/(name+'.json')
   self.data[name]=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
 def prop(self,id):
  return self.data['PetBattleFuLu'].get(str(id),{}).get('name',str(id))
 def describe(self,pet):
  known='hpMax' in pet
  template=self.data['PetBattleLockerAtt'].get(str(pet.get('sysPetLv')), {}) if not known else {}
  base=pet if known else template
  locker=self.data['PetBattleLocker'].get(str(pet.get('btlPetId')), {})
  elf=(pet.get('equipments') or {}).get('petElf') or {}
  ec=self.data['PetElf'].get(str(elf.get('id')), {})
  elf_source='服务器' if elf else '配置模板'
  if not ec and not known and locker:
   ec=self.data['PetElf'].get(str(locker.get('petElfId')), {})
  elf_name=ec.get('name','未下发' if not known else '未装备')
  elf_level=(int(ec.get('quality',2))-1) if elf else base.get('petElfSkill')
  basis='服务器完整快照' if known else '配置模板推算（待出战快照核实）' if template else '仅有简略资料'
  detail=[basis, '基础十维（未叠加装备、真灵和性格；不是最终战斗面板）：']
  detail.extend(f'{label}：{base[k]:,}' if k in base else f'{label}：未下发' for k,label in zip(ATTRS,LABELS))
  pc=self.data['Pet'].get(str(pet.get('id')), {})
  detail.append('八系抗性：本体＋潜能/被动×0.45；不含装备额外抗性、临时符及天赋效果。')
  for k,label in zip(RESISTS,LABELS[10:]):
   if known or k in base:
    potential=float(base.get(k) or 0);perk_value=0
    if known:
     for sid,level in (pet.get('skill',{}).get('passivity') or {}).items():
      perk=self.data['PetPerks'].get(str(sid)+'_'+str(level),{})
      if perk.get('attributeT1')==k:
       perk_value+=math.floor((float(perk.get('attributeV1') or 0)+float(perk.get('boneValue') or 0)*float(pet.get('bone') or 0))*.45+.5)
    value=float(pc.get(k) or 0)+math.floor(potential*.45+.5)+perk_value
    detail.append(f'{label}：{value:g}（本体{pc.get(k) or 0}＋round({potential:g}×0.45)＋被动{perk_value}）')
   else:detail.append(f'{label}：未下发')
  detail.append(f'真灵：{elf_name} / 技能等级{elf_level if elf_level is not None else "未知"}（{elf_source}）')
  # 系统宠物快照仅穿真灵，按原版等级成长及特殊属性重建静态面板。
  if known and not (set(pet.get('equipments') or {})-{'petElf'}) and all(k in pet for k in ATTRS):
   panel={k:float(pet[k]) for k in ATTRS}
   def add_item(item,is_elf=False):
    config=self.data['PetElfAtt'].get(str(ec.get('baseId')), {}) if is_elf else {}
    for k in ATTRS:
     raw=float(item.get(k) or 0);growth=float(config.get(k+'Add') or 0)*float(item.get('level') or 0)
     panel[k]+=math.floor(raw+.0001+.5)+(math.floor(growth+.0002+.5) if not is_elf or raw>0 else 0)
    special=(item.get('petElfAtt') or {}).get('special')
    if special:add_item(special)
   if elf:add_item(elf,True)
   character=self.data['PetCharacter'].get(str(pet.get('character')), {})
   for k in ['atk','phyDef','dodge','critical']:panel[k]*=1+float(character.get(k) or 0)
   common=next((v for v in self.data['Common'].values() if 'petBattleHpMaxQualificationIndex' in v),{})
   multiplier=common.get('petBattleHpMaxQualificationIndex')
   if multiplier is not None:
    panel['hpMax']*=float(multiplier)
    detail.append(f'入场静态十维（已加真灵、性格；生命×{multiplier}，不含符/天赋/临时效果）：')
    detail.extend(f'{label}：{panel[k]:,.2f}' for k,label in zip(ATTRS,LABELS))
  elif not known:detail.append('最终面板：待服务器下发真灵实际属性后计算，当前不以模板冒充最终值。')
  detail.append('真灵及装备原始数据：'+json.dumps(pet.get('equipments'),ensure_ascii=False))
  return {'name':pet.get('name',str(pet.get('id'))),'level':pet.get('level','未知'),'power':pet.get('fightPower','未知'),'elf':elf_name+(f' Lv.{elf_level}' if elf_level is not None else ''),'basis':basis,'detail':'\n'.join(detail)}

class Preparation:
 def __init__(self,uid,notify=None):
  self.uid=str(uid);self.lock=threading.RLock();self.commands=queue.Queue();self.notify=notify or print
  self.state={'roomId':None,'stage':None,'session':None,'deadline':0,'players':[],'epoch':0,'results':[]};self.stopped=threading.Event()
 def snapshot(self):
  with self.lock:return copy.deepcopy(self.state)
 def observe(self,route,body):
  from pet_brawl import _message
  d=_message(body)
  notice=None
  with self.lock:
   if route=='onPrepareCreateOnlineCopy':
    self.state.update(roomId=d.get('roomId'),stage=None,players=copy.deepcopy(d.get('pets') or []),deadline=0,epoch=self.state['epoch']+1,results=[])
   elif route=='onPetPvpBtlChangeState':
    previous=(self.state['session'],self.state['stage'])
    self.state.update(stage=d.get('btlStage'),session=d.get('session'),players=copy.deepcopy(d.get('players') or []),deadline=time.monotonic()+float(d.get('time') or 0),epoch=self.state['epoch']+1)
    if isinstance(d.get('btlWin'),list):
     self.state['results']=round_results(d['btlWin'],self.state['players'],self.uid)
    current=(self.state['session'],self.state['stage'])
    if current!=previous:
     if current[1]==0:
      notice=(f'第{previous[0]}小局已结束；' if previous[0] is not None and current[0]!=previous[0] else '')+f'第{current[0]}小局准备开始，请选择宠物和宝符（{d.get("time") or 0}秒）'
     elif current[1]==1:notice=f'第{current[0]}小局选宠时间结束，正在加载战斗'
     elif current[1]==2:notice=f'第{current[0]}小局战斗开始，等待服务器返回结果'
   elif route in ('onPetPVPFinish','onPetPvpBtlExit','kicked'):
    self.state.update(stage=None,deadline=0,epoch=self.state['epoch']+1)
  if notice:self.notify(notice)
 def enqueue(self,kind,value=None):
  s=self.snapshot();self.commands.put((s['epoch'],kind,value))
 def process(self,flow):
  if self.stopped.is_set():raise InterruptedError('手动乱斗已停止')
  while True:
   try:epoch,kind,value=self.commands.get_nowait()
   except queue.Empty:return
   s=self.snapshot()
   if epoch!=s['epoch'] or s['stage']!=0 or time.monotonic()>=s['deadline'] or not s['roomId']:
    self.notify('操作未发送：已超过本回合准备时间');continue
   me=next((p for p in s['players'] if str(p.get('playerId'))==self.uid),None)
   if me is None:self.notify('未识别到我方数据');continue
   selected=me.get('onBtl') or []
   if kind=='pet':
    if value in selected:self.notify('该宠物已经出战，本次不重复提交');continue
    if type(value) is not int or value not in valid_indices(me.get('btlCards'),me.get('btlPets') or []):self.notify('只能选择本回合抽到的宠物');continue
    route='room.petPvpRoomHandler.setPetPvpWaitPet';params={'roomId':s['roomId'],'index':int(value)}
   elif kind in ('fulu','remove_fulu'):
    value=int(value or 0)
    if kind=='fulu' and (value not in (me.get('btlTally') or []) or len(me.get('cost') or [])>=3):
     self.notify('该符不可用，或本场使用次数已满');continue
    if kind=='remove_fulu':
     value=me.get('useFuLu');value=value[0] if isinstance(value,list) and value else value
     if not value:self.notify('当前没有上阵的符');continue
    route='room.petPvpRoomHandler.setPetPvpWaitFuLu';params={'roomId':s['roomId'],'fulu':int(value),'putOn':kind=='fulu'}
   else:self.notify('未知操作');continue
   # 回应成功才显示确认；服务端拒绝不自动重试。
   try:
    r=flow.request(route,params)
    if r.get('code')!=200 or r.get('error'):raise RuntimeError(str(r.get('error') or r.get('code')))
    with self.lock:
     if self.state['epoch']==epoch:
      current=next(p for p in self.state['players'] if str(p.get('playerId'))==self.uid)
      if isinstance(r.get('my'),dict):current.update(copy.deepcopy(r['my']))
      elif kind=='pet':current['onBtl']=[value]
      else:current['useFuLu']=value if kind=='fulu' else None
    self.notify('服务器已确认：'+('宠物选择' if kind=='pet' else '上符' if kind=='fulu' else '下符'))
   except Exception as exc:self.notify('操作失败：'+str(exc))

def run_window(flow,uid,args):
 import tkinter as tk
 from tkinter import ttk
 from pet_brawl import EVENTS
 from pet_brawl_manual import play_one
 root=tk.Tk();root.title('灵宠乱斗 · 准备阶段');root.geometry('1060x760');root.minsize(850,620)
 messages=queue.Queue();control=Preparation(uid,lambda s:messages.put(str(s)));events=queue.Queue();catalog=Catalog()
 def receive(route,body):
  control.observe(route,body);events.put((route,body))
 for route in EVENTS:flow.on(route,lambda body,name=route:receive(name,body))
 toolbar=ttk.Frame(root,padding=(10,10,10,4));toolbar.pack(fill='x')
 style=ttk.Style(root);style.configure('BrawlMatch.TButton',font=('Microsoft YaHei',15,'bold'),padding=(24,14))
 match_button=ttk.Button(toolbar,text='开始匹配',style='BrawlMatch.TButton',command=lambda:start_match())
 match_button.pack(fill='x')
 status=tk.StringVar(value='点击开始匹配，每次只打一场');ttk.Label(root,textvariable=status,font=('Microsoft YaHei',12)).pack(fill='x',padx=10,pady=8)
 settlement=tk.StringVar(value='结算后自动刷新战绩和乱斗币');ttk.Label(root,textvariable=settlement,wraplength=1000).pack(fill='x',padx=10,pady=4)
 score=tk.StringVar(value='小局结果：暂无已确认结果');ttk.Label(root,textvariable=score,wraplength=1000,font=('Microsoft YaHei',11,'bold')).pack(fill='x',padx=10,pady=4)
 opponent=tk.StringVar();ttk.Label(root,textvariable=opponent,wraplength=1000).pack(fill='x',padx=10)
 cols=('pet','level','power','elf','basis');tree=ttk.Treeview(root,columns=cols,show='headings',height=10)
 for c,title,width in zip(cols,['对手候选宠物','等级','战力','真灵','资料来源'],[190,65,115,150,340]):tree.heading(c,text=title);tree.column(c,width=width)
 tree.pack(fill='both',expand=True,padx=10,pady=8)
 detail=tk.Text(root,height=10,wrap='word');detail.pack(fill='both',expand=True,padx=10)
 box=ttk.LabelFrame(root,text='仅准备阶段可操作（符会按游戏规则消耗）',padding=10);box.pack(fill='x',padx=10,pady=8)
 pet_var=tk.StringVar();fulu_var=tk.StringVar();petbox=ttk.Combobox(box,textvariable=pet_var,state='disabled',width=32);petbox.grid(row=0,column=0,padx=4)
 pet_button=ttk.Button(box,text='确认出战',command=lambda:control.enqueue('pet',pet_choices.get(pet_var.get())));pet_button.grid(row=0,column=1,padx=4)
 fulubox=ttk.Combobox(box,textvariable=fulu_var,state='disabled',width=25);fulubox.grid(row=0,column=2,padx=4)
 fulu_button=ttk.Button(box,text='上符',command=lambda:control.enqueue('fulu',fulu_choices.get(fulu_var.get())));fulu_button.grid(row=0,column=3,padx=4)
 remove=ttk.Button(box,text='下符',command=lambda:control.enqueue('remove_fulu'));remove.grid(row=0,column=4,padx=4)
 choice_status=tk.StringVar();ttk.Label(box,textvariable=choice_status,wraplength=980).grid(row=1,column=0,columnspan=5,sticky='w',pady=(8,0))
 log=tk.StringVar();ttk.Label(root,textvariable=log,wraplength=1000).pack(fill='x',padx=10,pady=5)
 pet_choices={};fulu_choices={};display={};last_version=None;finished=threading.Event()
 finished.set();busy=threading.Event();outcomes=queue.Queue();outcome_text='尚未开始匹配';can_match=True
 def selected(event=None):
  items=tree.selection()
  if items and items[0] in display:
   detail.config(state='normal');detail.delete('1.0','end');detail.insert('1.0',display[items[0]]['detail']);detail.config(state='disabled')
 tree.bind('<<TreeviewSelect>>',selected)
 def poll():
  nonlocal last_version,outcome_text,can_match
  try:
   while True:
    result=outcomes.get_nowait();outcome_text=result['text'];can_match=result['can_match']
    stats=result.get('stats')
    if stats:settlement.set(f"战绩：{stats['total']}场 / 胜{stats['win']} / 负{stats['fail']} ｜ 积分{stats['score']} ｜ 乱斗币{stats['coin']} ｜ 今日已获{stats['daily_coin']}")
  except queue.Empty:pass
  s=control.snapshot();me=next((p for p in s['players'] if str(p.get('playerId'))==str(uid)),{});en=next((p for p in s['players'] if str(p.get('playerId'))!=str(uid)),{})
  active=not finished.is_set() and s['stage']==0 and time.monotonic()<s['deadline'];remaining=max(0,math.ceil(s['deadline']-time.monotonic()))
  phase={0:'准备：请选择宠物和宝符',1:'加载战斗',2:'战斗进行中，等待服务器结果'}.get(s['stage'],'匹配/入房')
  if s['stage']==2 and remaining==0:phase='本小局计时结束，等待服务器结算/下一轮'
  elif s['stage']==0 and remaining==0:phase='选宠计时结束，等待服务器切换阶段'
  status.set(outcome_text if finished.is_set() else f"第{s['session'] or '-'}小局 · {phase} · {remaining if s['stage'] is not None else '-'}秒")
  match_button.config(state='normal' if finished.is_set() and not busy.is_set() and can_match else 'disabled')
  results=s.get('results') or []
  score.set('小局结果：'+(' ｜ '.join(f'第{i+1}局：{value}' for i,value in enumerate(results)) if results else '暂无已确认结果')+f"  （胜{results.count('胜')} / 负{results.count('负')} / 平{results.count('平')}）")
  version=json.dumps(s['players'],sort_keys=True,ensure_ascii=False)
  if version!=last_version:
   last_version=version;old=tree.selection();tree.delete(*tree.get_children());display.clear()
   ep=en.get('btlPets') or [];cards=valid_indices(en.get('btlCards'),ep)
   opponent.set('对手：'+en.get('name','等待匹配')+' ｜ 天赋：'+('、'.join(catalog.prop(v) for v in en.get('btlTianFu') or []) or '无')+' ｜ 可用符：'+('、'.join(catalog.prop(v) for v in en.get('btlTally') or []) or '无')+'\n本轮候选：'+('、'.join(ep[i]['name'] for i in cards if 0<=i<len(ep)) or '未下发'))
   for i,p in enumerate(ep):
    d=catalog.describe(p);display[str(i)]=d;tree.insert('','end',iid=str(i),values=(d['name'],d['level'],d['power'],d['elf'],d['basis']))
   if old and old[0] in display:tree.selection_set(old);selected()
   elif display:tree.selection_set(next(iter(display)));selected()
   mp=me.get('btlPets') or [];indices=valid_indices((me.get('btlCards') or [])+(me.get('onBtl') or []),mp)
   pet_choices.clear();pet_choices.update({f"{i+1}. {mp[i]['name']}":i for i in indices if 0<=i<len(mp)});petbox.config(values=list(pet_choices))
   if pet_var.get() not in pet_choices:pet_var.set(next(iter(pet_choices),''))
   fulu_choices.clear();fulu_choices.update({catalog.prop(v)+f' ({v})':v for v in me.get('btlTally') or []});fulubox.config(values=list(fulu_choices))
   if fulu_var.get() not in fulu_choices:fulu_var.set(next(iter(fulu_choices),''))
  petbox.config(state='readonly' if active else 'disabled');fulubox.config(state='readonly' if active else 'disabled')
  pet_button.config(state='normal' if active and pet_choices else 'disabled');fulu_button.config(state='normal' if active and fulu_choices else 'disabled');remove.config(state='normal' if active else 'disabled')
  mp=me.get('btlPets') or [];on=valid_indices(me.get('onBtl'),mp);fulu=me.get('useFuLu');fulu=fulu[0] if isinstance(fulu,list) and fulu else fulu
  choice_status.set('我方已选：'+('、'.join(mp[i]['name'] for i in on if 0<=i<len(mp)) or '尚未选择')+' ｜ 已上符：'+(catalog.prop(fulu) if fulu else '无')+' ｜ 本场已用符：'+str(len(me.get('cost') or []))+'/3')
  try:
   while True:
    msg=messages.get_nowait();log.set(msg);print('[乱斗准备] '+msg,flush=True)
  except queue.Empty:pass
  root.after(150,poll)
 def worker():
  try:
   result=play_one(flow,events,control,args.match_seconds,args.battle_seconds,slot=getattr(args,'record_index',0))
   outcomes.put(result);messages.put(result['text'])
  except Exception as exc:
   outcomes.put({'text':'匹配异常：'+str(exc),'can_match':False});messages.put(str(exc))
  finally:busy.clear();finished.set()
 def start_match():
  nonlocal last_version
  if busy.is_set() or not can_match:return
  busy.set();finished.clear();match_button.config(text='继续匹配',state='disabled')
  while not events.empty():events.get_nowait()
  with control.lock:
   control.state.update(roomId=None,stage=None,session=None,deadline=0,players=[],results=[],epoch=control.state['epoch']+1)
  last_version=None
  threading.Thread(target=worker,daemon=True).start()
 def close():control.stopped.set();root.destroy()
 root.protocol('WM_DELETE_WINDOW',close);poll();root.mainloop()
