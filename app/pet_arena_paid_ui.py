"""同一斗宠设置页上的独立付费入口。"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from pet_arena_paid import PRESETS,COST,rounds_for,parse_rid
ROOT=Path(__file__).resolve().parent
class PaidPetArenaPanel:
    def __init__(self,app,parent):
        self.app=app;self.data=None;self.buttons=[]
        self.box=ttk.LabelFrame(parent,text='点券斗宠／竞技场',padding=6);self.box.pack(fill='x',padx=8,pady=6)
        self.kind=tk.StringVar(value='点券斗宠大会')
        kind_row=ttk.Frame(self.box);kind_row.pack(fill='x',pady=4)
        ttk.Label(kind_row,text='付费项目：').pack(side='left')
        ttk.Combobox(kind_row,textvariable=self.kind,values=('点券斗宠大会','点券竞技场'),state='readonly',width=20).pack(side='left')
        self.target=tk.StringVar(value='默认对手');self.custom_rid=tk.StringVar(value='');self.mode=tk.StringVar(value='按局数');self.value=tk.StringVar(value='10')
        self.battle=tk.StringVar(value='2');self.interval=tk.StringVar(value='8')
        ttk.Label(kind_row,text='局内秒数：').pack(side='left',padx=(12,0));ttk.Spinbox(kind_row,from_=2,to=3600,textvariable=self.battle,width=6).pack(side='left')
        ttk.Label(kind_row,text='局间秒数：').pack(side='left',padx=(12,0));ttk.Spinbox(kind_row,from_=8,to=3600,textvariable=self.interval,width=6).pack(side='left')
        row=ttk.Frame(self.box);row.pack(fill='x')
        ttk.Label(row,text='对手：').pack(side='left')
        self.target_combo=ttk.Combobox(row,textvariable=self.target,values=['默认对手'],state='readonly',width=16)
        self.target_combo.pack(side='left',padx=4)
        ttk.Combobox(row,textvariable=self.mode,values=('按局数','按点券预算'),state='readonly',width=12).pack(side='left',padx=4)
        ttk.Entry(row,textvariable=self.value,width=8).pack(side='left')
        for label,action in [('查询对手及余额','query'),('确认付费开始','run'),('继续未完成任务','resume')]:
            button=ttk.Button(row,text=label,command=lambda a=action:self.launch(a));button.pack(side='left',padx=4);self.buttons.append(button)
        self.custom_frame=ttk.Frame(self.box)
        ttk.Label(self.custom_frame,text='完整实际RID：').pack(side='left')
        ttk.Entry(self.custom_frame,textvariable=self.custom_rid,width=32).pack(side='left')
        self.summary=tk.StringVar(value='先查询再确认。当前选中账号/槽位出战，每局20点券，每10局汇总。')
        ttk.Label(self.box,textvariable=self.summary,wraplength=920).pack(anchor='w',pady=4)
        ttk.Label(self.box,text='仅执行所选项目的点券挑战，先用完该项目免费次数。开启本页独立点券权限并填写预算；报错保存断点，重新查询后继续。',wraplength=920).pack(anchor='w')
        self.target.trace_add('write',self.change_target)
        self.custom_rid.trace_add('write',lambda *_:self.invalidate())
        self.kind.trace_add('write',self.change_kind)
        for var in self.app.spend_permissions.variables['dungeons']:
            var.trace_add('write',self.refresh_targets)
        self.refresh_targets()
    def refresh_targets(self,*_):
        unlocked=''.join('1' if v.get() else '0' for v in self.app.spend_permissions.variables['dungeons'])=='001'
        choices=[*PRESETS,'自定义RID'] if unlocked else ['默认对手']
        self.target_combo.configure(values=choices)
        if self.target.get() not in choices:self.target.set('默认对手')
    def handler(self):return 'arena' if self.kind.get()=='点券竞技场' else 'petArena'
    def change_kind(self,*_):
        self.battle.set('22' if self.handler()=='arena' else '2');self.interval.set('22' if self.handler()=='arena' else '8')
        self.invalidate()
    def change_target(self,*_):
        self.custom_frame.pack(fill='x',pady=4) if self.target.get()=='自定义RID' else self.custom_frame.pack_forget()
        self.invalidate()
    def selected_rid(self):
        return parse_rid(self.custom_rid.get()) if self.target.get()=='自定义RID' else PRESETS[self.target.get()]
    def invalidate(self):self.data=None;self.summary.set('对手已变更，请重新查询。')
    def render(self,data):
        self.data=data;s=data['state'];resume=data.get('resume')
        currency='竞技币' if data.get('handler')=='arena' else '斗宠币'
        text='出战槽%s｜%s｜点券%s｜%s%s｜免费已用%s/%s'%(data['slot'],data.get('target_label','所选对手'),s['ticket'],currency,s['money'],s['used'],s['limit'])
        if resume:text+='｜未完成任务：%s/%s局（继续时以服务器核对为准）'%(resume['completed'],resume['rounds'])
        self.summary.set(text)
    def launch(self,action):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            target=self.selected_rid();handler=self.handler();args=[str(ROOT/'pet_arena_paid.py'),'--handler',handler,'--action',action,'--target',target]
            if action!='query':
                a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));d=self.data
                if not d or d.get('handler')!=handler or d['account']!=str(a.get('username','')) or d['slot']!=int(self.app.cmb_slot.get()) or d['target']!=target:raise ValueError('请先查询当前账号、槽位、付费项目和对手')
                battle=float(self.battle.get());interval=float(self.interval.get())
                if not 2<=battle<=3600 or not 8<=interval<=3600:raise ValueError('局内最低2秒，局间最低8秒')
                mode='rounds' if self.mode.get()=='按局数' else 'budget'
                rounds=rounds_for(mode,self.value.get())
                if action=='resume':
                    if not d.get('resume'):raise ValueError('没有可继续的任务，请先查询')
                    rounds=d['resume']['rounds']-d['resume']['completed']
                self.app.spend_permissions.require('daily')
                text='%s：当前账号槽%s挑战%s\n%s局，预计最多%s点券\n局内%g秒，局间%g秒；每10局核对。\n确认%s？'%(self.kind.get(),d['slot'],d.get('target_label','所选对手'),rounds,rounds*COST,battle,interval,'继续未完成任务' if action=='resume' else '付费挑战')
                if not messagebox.askyesno('确认点券挑战',text,parent=self.box):return
                args+=['--account',d['account'],'--slot',str(d['slot']),'--fingerprint',d['fingerprint'],'--mode',mode,'--value',self.value.get(),'--battle-wait',str(battle),'--round-wait',str(interval)]
            self.data=None;self.app._launch(args)
        except (ValueError,KeyError) as e:messagebox.showerror('未执行',str(e),parent=self.box)
