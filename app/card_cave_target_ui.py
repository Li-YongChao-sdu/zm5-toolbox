import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent

class CardCaveTargetPage:
    def __init__(self,app,notebook):
        self.app=app;self.data=None;self.buttons=[]
        self.page=ttk.Frame(notebook,padding=12);notebook.add(self.page,text='藏宝洞')
        row=ttk.Frame(self.page);row.pack(fill='x',pady=5);ttk.Label(row,text='挑战方式',width=30).pack(side='left')
        self.mode=tk.StringVar(value='指定挑战码');ttk.Combobox(row,textvariable=self.mode,values=['指定挑战码','推荐最高守备强度'],state='readonly',width=38).pack(side='left')
        self.code=self.field('指定挑战码','3922097053_r3_1');self.count=self.field('本次挑战次数（1～5）','5',app.var_times['CARD_CAVE_TIMES']);self.wait=self.field('结算等待／局间间隔（秒）','2')
        self.code.trace_add('write',lambda *_:self.invalidate())
        self.summary=tk.StringVar(value='默认指定挑战码：填写挑战码或从下方榜单选择，查询后确认挑战；两种方式共享每日5次免费额度。')
        self.mode.trace_add('write',lambda *_:self.change_mode())
        self.rank_data=None;self.rank_rows={}
        self.rank_frame=ttk.LabelFrame(self.page,text='守备强度排行榜候选')
        bar=ttk.Frame(self.rank_frame);bar.pack(fill='x')
        for text,command in [('加载榜单前8名',self.load_rank),('使用所选挑战码并查询',self.use_rank)]:
            button=ttk.Button(bar,text=text,command=command);button.pack(side='left',padx=4,pady=4);self.buttons.append(button)
        self.rank_tree=ttk.Treeview(self.rank_frame,columns=('rank','owner','strength','code'),show='headings',height=5,selectmode='browse')
        for k,title,width in [('rank','排名',60),('owner','洞主',190),('strength','守备强度',100),('code','挑战码',280)]:
            self.rank_tree.heading(k,text=title);self.rank_tree.column(k,width=width)
        self.rank_tree.pack(fill='x',padx=4,pady=4)
        self.rank_tree.bind('<Double-1>',lambda e:self.use_rank())
        self.change_mode()
        self.summary.set('默认指定挑战码：填写挑战码或从下方榜单选择，查询后确认挑战；两种方式共享每日5次免费额度。')

        ttk.Label(self.page,textvariable=self.summary,wraplength=950).pack(anchor='w',pady=8)
        for text,action in [('查询藏宝洞与免费次数','query'),('确认并正式挑战','fight'),('一键查询并挑战5次','auto')]:
            b=ttk.Button(self.page,text=text,command=lambda a=action:self.run(a));b.pack(anchor='w',pady=5);self.buttons.append(b)
        ttk.Label(self.page,text='走正式开局和奖励结算；只用每日剩余免费次数。支持自己的已发布藏宝洞。日常任务中的藏宝洞也使用本页的模式、次数和等待设置。默认指定挑战码；推荐模式每局刷新并重新选最高分。一键挑战会现场查询并连续挑战5局，中途失败即停。',wraplength=950).pack(anchor='w',pady=8)
    def field(self,label,value,var=None):
        row=ttk.Frame(self.page);row.pack(fill='x',pady=5);ttk.Label(row,text=label,width=30).pack(side='left')
        if label=='指定挑战码':self.code_row=row
        if label=='本次挑战次数（1～5）':self.count_row=row
        v=var if var is not None else tk.StringVar(value=value);ttk.Entry(row,textvariable=v,width=40).pack(side='left');return v
    def change_mode(self):
        if self.mode_key()=='specified':
            self.code_row.pack(fill='x',pady=5,before=self.count_row)
            self.rank_frame.pack(fill='x',pady=5,before=self.count_row)
        else:
            self.code_row.pack_forget();self.rank_frame.pack_forget()
        self.invalidate()
    def load_rank(self):
        if self.app.running or not self.app._save_selected_slot():return
        self.rank_data=None;self.rank_rows={};self.rank_tree.delete(*self.rank_tree.get_children())
        self.app._launch([str(ROOT/'card_cave_target.py'),'--rank'])
    def render_rank(self,data):
        self.rank_data=data;self.rank_rows={r['code']:r for r in data['rows']};self.rank_tree.delete(*self.rank_tree.get_children())
        for r in data['rows']:self.rank_tree.insert('',tk.END,iid=r['code'],values=(r['rank'],r['owner'],r['strength'],r['code']))
        self.app._append_log('[藏宝洞] 守备强度榜已载入%s名候选；选择后使用并查询。'%len(data['rows']))
    def use_rank(self):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));d=self.rank_data
            if not d or d['account']!=str(a.get('username','')) or d['slot']!=int(self.app.cmb_slot.get()):raise ValueError('账号或槽位已变化，请重新加载排行榜')
            chosen=self.rank_tree.selection()
            if not chosen:raise ValueError('请先选择排行榜中的玩家')
            self.mode.set('指定挑战码');self.code.set(chosen[0]);self.run('query')
        except (ValueError,KeyError) as e:messagebox.showerror('未执行',str(e),parent=self.page)
    def invalidate(self,message='账号、槽位、挑战方式或挑战码已变化，请重新查询。'):self.data=None;self.summary.set(message)
    def render(self,data):
        if data.get('mode','specified')!=self.mode_key():return
        if self.mode_key()=='specified' and data['code']!=self.code.get().strip():return
        try:
            a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
            slot=int(self.app.cmb_slot.get())
        except (OSError,ValueError,KeyError):
            self.invalidate('无法确认当前账号或槽位，请重新查询。');return
        if str(data.get('account',''))!=str(a.get('username','')) or int(data.get('slot',-1))!=slot:
            self.invalidate('账号或槽位已变化，请重新查询。');return
        self.data=data;self.summary.set('槽%s｜洞主：%s｜%s\n%s星｜守备强度%s｜今日剩余免费%s次\n挑战码：%s'%(data['slot'],data['owner'],data['name'],data['stars'],data['strength'],data['remaining'],data['code']))
    def mode_key(self):return 'specified' if self.mode.get()=='指定挑战码' else 'recommend'
    def run(self,action):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            code=self.code.get().strip()
            import re
            if self.mode_key()=='specified' and not re.fullmatch(r'\d+_r\d+_\d+',code):raise ValueError('请输入 UID_r编号_展位编号 格式的挑战码')
            args=[str(ROOT/'card_cave_target.py'),'--mode',self.mode_key(),'--code',code]
            if action=='auto':
                wait=float(self.wait.get())
                if not 0<=wait<=3600:raise ValueError('等待须为0～3600秒')
                a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
                args+=['--matches','5','--wait',str(wait),'--account',str(a.get('username','')),'--slot',str(int(self.app.cmb_slot.get()))]
                self.data=None;self.summary.set('已启动一键挑战：现场查询目标，连续挑战5局，中途失败即停。')
                self.app._append_log('[藏宝洞] 一键挑战已启动：%s，5局，间隔%s秒。'%('每局刷新推荐最高守备强度' if self.mode_key()=='recommend' else '指定挑战码',wait))
            if action=='fight':
                a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));d=self.data
                if not d:raise ValueError('请先查询当前账号、槽位与挑战码')
                if d['account']!=str(a.get('username','')) or d['slot']!=int(self.app.cmb_slot.get()):raise ValueError('账号或槽位已变化，请重新查询')
                if d.get('mode')!=self.mode_key() or (self.mode_key()=='specified' and d['code']!=code):raise ValueError('挑战方式或挑战码已变化，请重新查询')
                n=int(self.count.get());wait=float(self.wait.get())
                if not 1<=n<=5 or not 0<=wait<=3600:raise ValueError('次数须为1～5，等待须为0～3600秒')
                if d['remaining']<=0:raise ValueError('今天免费次数已用尽')
                description=('每局刷新推荐，选择最高守备强度' if self.mode_key()=='recommend' else '指定挑战%s的%s星藏宝洞'%(d['owner'],d['stars']))
                if not messagebox.askyesno('确认正式挑战','%s，最多%s局，结算等待及局间间隔%s秒？\n仅使用剩余免费次数。'%(description,min(n,d['remaining']),wait),parent=self.page):return
                args+=['--matches',str(n),'--wait',str(wait),'--account',d['account'],'--slot',str(d['slot']),'--fingerprint',d['fingerprint']]
            self.data=None;self.app._launch(args)
        except (ValueError,KeyError) as e:messagebox.showerror('未执行',str(e),parent=self.page)
