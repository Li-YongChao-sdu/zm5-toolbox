"""简单炼丹炉页面，查询后只展示当前炉等级已开放的配方。"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent

class StovePage:
    def __init__(self,app,notebook):
        self.app=app;self.data=None;self.rows={};self.buttons=[]
        self.page=ttk.Frame(notebook,padding=10);notebook.add(self.page,text='炼丹炉')
        self.summary=tk.StringVar(value='先查询当前存档的炼丹炉等级，再显示已开放配方。')
        ttk.Label(self.page,textvariable=self.summary).pack(anchor='w',pady=4)
        row=ttk.Frame(self.page);row.pack(fill='x')
        for text,command in [('查询炉等级及配方',self.refresh),('炼制所选配方一次',self.compose)]:
            b=ttk.Button(row,text=text,command=command);b.pack(side='left',padx=4,pady=5);self.buttons.append(b)
        self.only_enough=tk.BooleanVar(value=False)
        ttk.Checkbutton(row,text='只看材料充足',variable=self.only_enough,command=self.render_rows).pack(side='left',padx=12)
        frame=ttk.Frame(self.page);frame.pack(fill='both',expand=True)
        columns=('id','name','category','level','materials','status')
        self.tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='browse')
        for k,title,width in [('id','配方ID',65),('name','配方',165),('category','分类',110),('level','要求炉等级',85),('materials','材料：背包数量／需求',430),('status','材料状态',90)]:
            self.tree.heading(k,text=title);self.tree.column(k,width=width,minwidth=50,stretch=k=='materials')
        y=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview);x=ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        self.tree.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew')
        ttk.Label(self.page,text='每次炼制1次，不自动购买材料。成功率、特殊产物和背包空间由服务器校验；8级炉的实际经验以返回值为准。',wraplength=1000).pack(anchor='w',pady=5)
    def refresh(self):
        if self.app.running or not self.app._save_selected_slot():return
        self.data=None;self.render_rows();self.summary.set('正在查询炼丹炉等级……')
        self.app._launch([str(ROOT/'stove_tool.py')])
    def render(self,data):
        self.data=data;self.summary.set('槽%s｜炼丹炉%s级｜经验%s｜已开放%s个配方'%(data['slot'],data['level'],data['exp'],len(data['recipes'])));self.render_rows()
    def render_rows(self):
        self.tree.delete(*self.tree.get_children());self.rows={}
        for r in (self.data or {}).get('recipes',[]):
            if self.only_enough.get() and not r['enough']:continue
            key=str(r['id']);self.rows[key]=r
            self.tree.insert('',tk.END,iid=key,values=(r['id'],r['name'],r['category'],r['level'],'；'.join('%s %s／%s'%(m['name'],m['have'],m['need']) for m in r['materials']),'充足' if r['enough'] else '不足'))
    def compose(self):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
            if not self.data or self.data['account']!=str(a.get('username','')) or self.data['slot']!=int(self.app.cmb_slot.get()):raise ValueError('请先查询当前账号与槽位的炉等级')
            selected=self.tree.selection()
            if not selected:raise ValueError('请选择配方')
            r=self.rows[selected[0]]
            if not r['enough']:raise ValueError('背包材料不足')
            text='炼制%s一次\n消耗：%s\n确认提交？'%(r['name'],'、'.join('%s×%s'%(m['name'],m['need']) for m in r['materials']))
            if not messagebox.askyesno('确认炼制',text,parent=self.page):return
            args=[str(ROOT/'stove_tool.py'),'--compose-id',str(r['id']),'--account',self.data['account'],'--slot',str(self.data['slot'])]
            self.data=None;self.render_rows();self.app._launch(args)
        except (ValueError,KeyError) as e:messagebox.showerror('未执行',str(e),parent=self.page)
