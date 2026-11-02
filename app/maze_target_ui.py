import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent

class MazeTargetControls:
    def __init__(self,app,parent):
        self.app=app;self.parent=parent;self.data=None;self.buttons=[]
        self.mode=tk.StringVar(value='按通关率筛选');self.rate_mode=tk.StringVar(value='high');self.code=tk.StringVar()
        ttk.Combobox(parent,textvariable=self.mode,values=['按通关率筛选','指定迷宫'],state='readonly',width=25).pack(anchor='w',padx=8,pady=5)
        self.filters=ttk.Frame(parent);self.filters.pack(fill='x')
        for text,value in [('挑战至少100次，通关率超过95%；同一迷宫连续完成','high'),('挑战至少100次，通关率低于10%；每次选不同迷宫','low')]:ttk.Radiobutton(self.filters,text=text,variable=self.rate_mode,value=value).pack(anchor='w',padx=8,pady=2)
        self.specified=ttk.Frame(parent)
        row=ttk.Frame(self.specified);row.pack(fill='x',padx=8,pady=4);ttk.Label(row,text='迷宫挑战码／UID_位置：').pack(side='left');ttk.Entry(row,textvariable=self.code,width=32).pack(side='left')
        button=ttk.Button(row,text='查询指定迷宫',command=self.query);button.pack(side='left',padx=6);self.buttons.append(button)
        self.summary=tk.StringVar(value='先查询并确认目标，再执行日常任务中的迷宫挑战。')
        ttk.Label(self.specified,textvariable=self.summary,wraplength=780).pack(anchor='w',padx=8,pady=4)
        wait_row=ttk.Frame(parent);wait_row.pack(fill='x',padx=8,pady=4)
        ttk.Label(wait_row,text='开局到胜利结算等待（秒）：').pack(side='left')
        self.wait=tk.StringVar(value='30');ttk.Entry(wait_row,textvariable=self.wait,width=8).pack(side='left')
        self.note=ttk.Label(parent,text='只补足每日迷宫活跃所需的3次，每局核对任务进度；默认等待30秒，可自定义。',foreground='gray');self.note.pack(anchor='w',padx=8,pady=4)
        self.mode.trace_add('write',lambda *_:self.change());self.code.trace_add('write',lambda *_:self.invalidate())
    def invalidate(self):self.data=None;self.summary.set('目标已变化，请重新查询。')
    def change(self):
        self.filters.pack_forget();self.specified.pack_forget()
        frame=self.specified if self.mode.get()=='指定迷宫' else self.filters
        frame.pack(fill='x',before=self.note);self.invalidate()
    def query(self):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            from maze_target import decode_code
            decode_code(self.code.get())
        except ValueError as e:messagebox.showerror('未执行',str(e),parent=self.parent);return
        self.data=None;self.app._launch([str(ROOT/'maze_target.py'),'--code',self.code.get().strip()])
    def render(self,data):
        from maze_target import decode_code
        try:
            if decode_code(self.code.get())!=(data['uid'],data['pos']):return
        except ValueError:return
        self.data=data
        text='槽%s｜洞主：%s｜迷宫：%s｜挑战%s次，通关%s次\n标识：%s｜游戏挑战码：%s｜今日任务进度%s/3'%(data['slot'],data['owner'],data['name'],data['attempts'],data['clears'],data['id'],data['code'],data['task_progress'])
        self.summary.set(text)
        if not messagebox.askyesno('确认指定迷宫',text+'\n使用此迷宫完成剩余每日任务次数？',parent=self.parent):self.invalidate()
    def wait_seconds(self):
        from maze_target import wait_seconds
        return wait_seconds(self.wait.get())
    def config(self):
        if self.mode.get()!='指定迷宫':return self.rate_mode.get(),'',''
        a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));d=self.data
        from maze_target import decode_code
        if not d or d['account']!=str(a.get('username','')) or d['slot']!=int(self.app.cmb_slot.get()) or decode_code(self.code.get())!=(d['uid'],d['pos']):raise ValueError('指定迷宫请先查询并确认当前账号、槽位和目标')
        return 'specified',d['id'],d['fingerprint']
