"""仅V0～V2显示森林扫荡前水晶和二级密码设置。"""
import tkinter as tk
from tkinter import ttk
class ForestCrystalControls:
    def __init__(self,app,parent):
        self.vip=None;self.app=app
        self.enabled=tk.BooleanVar(value=False);self.password=tk.StringVar(value='')
        self.holder=ttk.Frame(parent);self.holder.pack(fill='x',padx=8,pady=3)
        self.box=ttk.Frame(self.holder,padding=4)
        self.notice=tk.StringVar()
        ttk.Label(self.box,textvariable=self.notice,wraplength=820).pack(anchor='w')
        ttk.Checkbutton(self.box,text='神兽森林扫荡前，能量不足时使用1个扫荡／速通水晶（不购买）',variable=self.enabled).pack(anchor='w',pady=3)
        row=ttk.Frame(self.box);row.pack(fill='x',pady=3)
        ttk.Label(row,text='二级密码（不保存）：').pack(side='left');ttk.Entry(row,textvariable=self.password,show='*',width=22).pack(side='left')
        app.var_forest_auto_crystal=self.enabled;app.var_forest_crystal_password=self.password
    def is_low_vip(self):return self.vip in (0,1,2)
    def set_vip(self,value):
        old=self.is_low_vip()
        try:
            if value is None or isinstance(value,bool):raise ValueError()
            value=int(value)
            if not 0<=value<=8:raise ValueError()
        except (ValueError,TypeError):value=None
        self.vip=value
        if self.is_low_vip():
            if not old:self.enabled.set(True)
            self.notice.set('检测到VIP%s：配置速通能量30点；森林4次需要40点。可在扫荡前使用1个水晶补充10点。'%value)
            self.box.pack(fill='x')
        else:self.box.pack_forget();self.password.set('');self.enabled.set(False)
    def invalidate(self):self.set_vip(None)
