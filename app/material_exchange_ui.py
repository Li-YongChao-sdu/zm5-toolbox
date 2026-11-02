import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from material_exchange import targets,catalog
ROOT=Path(__file__).resolve().parent
class MaterialExchangePage:
    def __init__(self,app,notebook):
        self.page=ttk.Frame(notebook,padding=4);notebook.add(self.page,text='材料置换')
        tabs=ttk.Notebook(self.page);tabs.pack(fill='both',expand=True)
        self.panels=[]
        for title,types in [('大材料（BOSS）',{2,3,4}),('小材料',{5,6,7})]:
            self.panels.append(MaterialExchangePanel(app,tabs,title,types))
        self.buttons=[b for panel in self.panels for b in panel.buttons]
    def render(self,data):
        config=catalog()
        for panel in self.panels:
            filtered=dict(data)
            filtered['sources']=[r for r in data['sources'] if config.get(str(r['id']),{}).get('type') in panel.types]
            panel.render(filtered)

class MaterialExchangePanel:
    def __init__(self,app,notebook,title,types):
        self.types=types
        self.app=app;self.data=None;self.sources={};self.targets={};self.buttons=[]
        self.page=ttk.Frame(notebook,padding=12);notebook.add(self.page,text=title)
        self.summary=tk.StringVar(value='请读取当前存档背包材料')
        ttk.Label(self.page,textvariable=self.summary,wraplength=850).pack(anchor='w',pady=6)
        b=ttk.Button(self.page,text='读取／刷新背包材料',command=lambda:self.run(False));b.pack(anchor='w',pady=8);self.buttons.append(b)
        row=ttk.Frame(self.page);row.pack(fill='x',pady=12)
        for col in range(3):row.columnconfigure(col,weight=1 if col==0 else 2)
        self.categories=({'防具（armor）':2,'头盔（helmet）':3,'武器（weapon）':4} if types=={2,3,4} else {'木（type=5）':5,'矿（type=6）':6,'布（type=7）':7})
        self.category=tk.StringVar(value=next(iter(self.categories)))
        ttk.Label(row,text='材料分类（配置原文）').grid(row=0,column=0,sticky='w')
        self.category_box=ttk.Combobox(row,textvariable=self.category,values=list(self.categories),state='readonly',width=19)
        self.category_box.grid(row=1,column=0,sticky='ew',padx=(0,8))
        ttk.Label(row,text='原始材料（背包已有）').grid(row=0,column=1,sticky='w')
        ttk.Label(row,text='需要置换的低阶材料').grid(row=0,column=2,sticky='w')
        self.source=tk.StringVar();self.target=tk.StringVar();self.count=tk.StringVar(value='1')
        self.left=ttk.Combobox(row,textvariable=self.source,state='readonly',width=30);self.left.grid(row=1,column=1,sticky='ew',pady=6,padx=(0,8))
        self.right=ttk.Combobox(row,textvariable=self.target,state='readonly',width=35);self.right.grid(row=1,column=2,sticky='ew')
        self.source.trace_add('write',lambda *_:self.update_targets())
        self.category.trace_add('write',lambda *_:self.update_sources())
        qty=ttk.Frame(self.page);qty.pack(fill='x',pady=8);ttk.Label(qty,text='数量（1:1）').pack(side='left');ttk.Entry(qty,textvariable=self.count,width=12).pack(side='left',padx=8)
        ttk.Button(qty,text='MAX',command=self.set_max).pack(side='left')
        b=ttk.Button(self.page,text='执行材料置换',command=lambda:self.run(True));b.pack(anchor='w',pady=10);self.buttons.append(b)
        note='本页仅显示'+title+'，只允许本组高阶换低阶。'
        ttk.Label(self.page,text=note+'可跨阶，1:1兑换。只使用背包材料，不从仓库取物或自动购买。每次执行核对材料数量及货币，失败或超时不自动重发。',wraplength=850).pack(anchor='w',pady=8)
    def render(self,data):
        self.data=data;self.summary.set('槽%s｜点券%s｜灵魂%s｜可置换原材料%s种'%(data['slot'],data['ticket'],data['spirit'],len(data['sources'])))
        self.update_sources()
    def update_sources(self):
        config=catalog();kind=self.categories.get(self.category.get())
        rows=(self.data or {}).get('sources',[])
        self.sources={'%s｜现有%s（%s）'%(r['name'],r['count'],r['id']):r for r in rows if config.get(str(r['id']),{}).get('type')==kind}
        self.left.configure(values=list(self.sources));self.source.set(self.source.get() if self.source.get() in self.sources else next(iter(self.sources),''));self.update_targets()
    def update_targets(self):
        r=self.sources.get(self.source.get());old=self.target.get()
        self.targets={'%s（%s）'%(v['name'],v['id']):v for v in targets(r['id'])} if r else {}
        self.right.configure(values=list(self.targets));self.target.set(old if old in self.targets else next(iter(self.targets),''));self.count.set('1')
    def set_max(self):
        r=self.sources.get(self.source.get())
        if r:self.count.set(str(r['count']))
    def run(self,execute):
        if self.app.running or not self.app._save_selected_slot():return
        args=[str(ROOT/'material_exchange.py')]
        if execute:
            try:
                account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
                if not self.data or self.data['account']!=str(account.get('username','')) or self.data['slot']!=int(self.app.cmb_slot.get()):raise ValueError('账号或存档改变，请先刷新材料')
                s=self.sources.get(self.source.get());t=self.targets.get(self.target.get());n=int(self.count.get())
                if not s or not t or not 0<n<=s['count']:raise ValueError('请选择左右材料，数量须在现有范围内')
                if not messagebox.askyesno('确认材料置换','%s ×%s → %s ×%s？'%(s['name'],n,t['name'],n),parent=self.page):return
                args+=['--source',str(s['id']),'--target',str(t['id']),'--count',str(n)]
            except (ValueError,KeyError) as exc:messagebox.showerror('未执行',str(exc),parent=self.page);return
        self.app._launch(args)
