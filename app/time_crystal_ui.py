import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent
class TimeCrystalPanel:
    def __init__(self,app,parent):
        self.app=app;self.buttons=[];self.box=ttk.LabelFrame(parent,text='使用时光水晶',padding=8);self.box.pack(fill='x',padx=4,pady=6);self.box._default_expanded=True
        self.summary=tk.StringVar(value='使用存档沿用上方“兑换存档”；请先选择存档并查看状态。')
        ttk.Label(self.box,textvariable=self.summary,wraplength=820).pack(anchor='w',pady=3)
        row=ttk.Frame(self.box);row.pack(fill='x',pady=4)
        ttk.Label(row,text='使用数量：').pack(side='left');self.count=tk.StringVar(value='1');ttk.Entry(row,textvariable=self.count,width=7).pack(side='left')
        ttk.Label(row,text='二级密码（不保存）：').pack(side='left',padx=(12,0));self.password=tk.StringVar();ttk.Entry(row,textvariable=self.password,show='*',width=20).pack(side='left')
        for label,action in [('查看水晶数量与时光能量',False),('使用时光水晶',True)]:
            button=ttk.Button(self.box,text=label,command=lambda flag=action:self.launch(flag));button.pack(anchor='w',pady=3);self.buttons.append(button)
        ttk.Label(self.box,text='每个增加1点时光能量；多个时逐个使用并核对。只使用背包已有水晶，不购买、不兑换次数。',wraplength=820).pack(anchor='w',pady=3)
        app.ui_settings_fields['时光水晶/使用数量']=(self.count,None)
        app.var_timeboat_slot.trace_add('write',lambda *_:self.invalidate())
    def binding(self):
        account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(self.app.var_timeboat_slot.get())
        if not 0<=slot<=7:raise ValueError('请先选择上方兑换存档')
        return str(account['uid']),slot
    def invalidate(self):self.password.set('');self.summary.set('账号或存档已切换，请重新查看水晶与能量。')
    def render(self,data):
        if (str(data['uid']),int(data['slot']))!=self.binding():return False
        self.summary.set('存档槽%s｜时光水晶%s个｜时光能量%s'%(data['slot'],data['crystals'],data['energy']));return True
    def launch(self,use):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            uid,slot=self.binding();args=[str(ROOT/'time_crystal.py'),'--uid',uid,'--slot',str(slot)];password=''
            if use:
                n=int(self.count.get())
                if not 1<=n<=9999:raise ValueError('使用数量须为1～9999')
                if not messagebox.askyesno('使用时光水晶','在槽%s使用%s个时光水晶？不购买、不兑换副本次数。'%(slot,n),parent=self.box):return
                args+=['--use','--count',str(n)];password=self.password.get();self.password.set('')
            self.app._launch(args,extra_env={'ZM5_TIME_CRYSTAL_PASSWORD':password})
        except (ValueError,OSError,KeyError) as exc:messagebox.showerror('未执行',str(exc),parent=self.box)
