"""可记忆的多材料售出选择与顺序。"""
import json
import tkinter as tk
from tkinter import ttk
class FundingChoices:
    def __init__(self,app,parent,catalog):
        self.catalog=catalog;self.order=list(catalog);self.selected=set();self.loading=False
        box=ttk.LabelFrame(parent,text='自动售出材料（可多选，按列表顺序）',padding=4);box.pack(fill='x',pady=4)
        self.tree=ttk.Treeview(box,columns=('pick','name','currency'),show='headings',height=7,selectmode='browse')
        for key,title,width in [('pick','选择',55),('name','材料',260),('currency','兑换货币',100)]:self.tree.heading(key,text=title);self.tree.column(key,width=width)
        self.tree.pack(side='left',fill='both',expand=True);bar=ttk.Scrollbar(box,command=self.tree.yview);bar.pack(side='left',fill='y');self.tree.configure(yscrollcommand=bar.set)
        actions=ttk.Frame(box);actions.pack(side='left',padx=6)
        for text,command in [('勾选／取消',self.toggle),('上移',lambda:self.move(-1)),('下移',lambda:self.move(1))]:ttk.Button(actions,text=text,command=command).pack(pady=3)
        self.tree.bind('<ButtonRelease-1>',self.click);self.tree.bind('<space>',lambda e:self.toggle())
        self.state=tk.StringVar(value='');self.state.trace_add('write',self.restore)
        app.ui_settings_fields['联盟仓库/自动售出材料及顺序']=(self.state,None)
        self.render();self.save()
    def render(self,focus=None):
        self.tree.delete(*self.tree.get_children())
        for key in self.order:
            row=self.catalog[key];self.tree.insert('',tk.END,iid=str(key),values=('☑' if key in self.selected else '☐',row['name'],'魂玉' if int(row['itemId'])==101026013 else '魂石'))
        if focus and str(focus) in self.tree.get_children():self.tree.selection_set(str(focus));self.tree.see(str(focus))
    def click(self,event):
        if self.tree.identify_column(event.x)=='#1':
            row=self.tree.identify_row(event.y)
            if row:self.tree.selection_set(row);self.toggle()
    def toggle(self):
        rows=self.tree.selection()
        if not rows:return
        key=int(rows[0])
        if key in self.selected:self.selected.remove(key)
        else:self.selected.add(key)
        self.render(key);self.save()
    def move(self,direction):
        rows=self.tree.selection()
        if not rows:return
        key=int(rows[0]);i=self.order.index(key);j=i+direction
        if 0<=j<len(self.order):self.order[i],self.order[j]=self.order[j],self.order[i];self.render(key);self.save()
    def value(self):return [key for key in self.order if key in self.selected]
    def save(self):
        self.loading=True
        try:self.state.set(json.dumps({'order':self.order,'selected':self.value()}))
        finally:self.loading=False
    def restore(self,*_):
        if self.loading:return
        try:
            data=json.loads(self.state.get());order=data['order'];selected=data['selected']
            if not isinstance(order,list) or not isinstance(selected,list):return
            if any(type(k)!=int for k in order+selected):return
            self.order=list(dict.fromkeys(k for k in order if k in self.catalog));self.order.extend(k for k in self.catalog if k not in self.order)
            self.selected={k for k in selected if k in self.catalog};self.render()
        except (ValueError,KeyError,TypeError):return
