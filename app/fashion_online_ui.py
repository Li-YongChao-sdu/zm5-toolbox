"""永久时装在线时长显示；仅在实际后台连接运行时估算刷新。"""
import json
import time
from datetime import datetime,timezone,timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox

ROOT=Path(__file__).resolve().parent

def duration(seconds):
    seconds=max(0,int(seconds))
    return '%02d:%02d'%divmod(seconds,60)

def describe(data,extra=0):
    target=int(data['target_seconds'])
    estimate=min(target,int(data['estimated_seconds'])+max(0,int(extra)))
    state=('今日已领取' if data['claimed'] else '当前未开放' if not data['present'] else
           '估算已达标，领奖以服务器核验为准' if estimate>=target else '尚未达标')
    return ('槽%s｜%s\n服务器已存 %s｜本连接在线 %s｜累计估算 %s / %s｜估算剩余 %s\n%s' %
        (data['slot'],state,duration(data['stored_seconds']),duration(int(data['session_seconds'])+max(0,int(extra))),
         duration(estimate),duration(target),duration(max(0,target-estimate)),
         '后台连接维持中；不反复查询任务' if data.get('live') else '本次连接已结束，以上为最后查询值，不继续累计'))

class FashionOnlinePanel:
    def __init__(self,app,parent):
        self.app=app;self.data=None;self.received=0;self.buttons=[]
        self.box=ttk.LabelFrame(parent,text='在线任务进度',padding=8)
        self.box.pack(fill='x',padx=8,pady=6)
        self.summary=tk.StringVar(master=app.root,value='请查询当前账号和存档的在线任务进度。')
        ttk.Label(self.box,textvariable=self.summary,wraplength=800).pack(anchor='w')
        row=ttk.Frame(self.box);row.pack(fill='x',pady=5)
        for title,action in (('查询在线进度','query'),('保持在线至达标并领奖','wait')):
            button=ttk.Button(row,text=title,command=lambda a=action:self.launch(a))
            button.pack(side='left',padx=(0,8));self.buttons.append(button)
        ttk.Label(self.box,text='普通“在线任务领奖”未满时仍跳过；只有点击“保持在线至达标并领奖”才会等待。累计为保守估算，不重复叠加服务器已保存的同一段时间。',wraplength=800,foreground='#666').pack(anchor='w')
        self.box.after(1000,self.tick)

    def render(self,data):
        try:
            if int(self.app.cmb_slot.get())!=int(data['slot']):return
            current=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
            if str(current.get('uid'))!=str(data['uid']):return
        except (ValueError,OSError,KeyError):return
        self.data=dict(data);self.received=time.monotonic()
        self.summary.set(describe(self.data))

    def tick(self):
        if self.data is not None:
            if self.data['day']!=datetime.now(timezone(timedelta(hours=8))).date().isoformat():
                self.invalidate()
                self.summary.set('日期已变化，请重新查询今日在线任务；未沿用昨日计时。')
            else:
                extra=time.monotonic()-self.received if self.data.get('live') and self.app.running else 0
                self.summary.set(describe(self.data,extra))
        self.box.after(1000,self.tick)

    def finished(self):
        if self.data is not None:
            if self.data.get('live'):
                extra=max(0,int(time.monotonic()-self.received))
                self.data['estimated_seconds']=min(self.data['target_seconds'],self.data['estimated_seconds']+extra)
                self.data['session_seconds']+=extra
            self.data['live']=False
            self.summary.set(describe(self.data))

    def invalidate(self):
        self.data=None
        self.summary.set('账号或存档已切换，请重新查询；未将其他存档的时间带入。')

    def launch(self,action):
        if self.app.running or not self.app._save_selected_slot():return
        if action=='wait' and not messagebox.askyesno('永久时装在线任务','维持当前存档在线至任务达标后尝试领奖；已经领取则直接跳过。确认执行？',parent=self.box):return
        self.invalidate()
        self.app._launch([str(ROOT/'fashion_online.py'),'--action',action])
