"""复用邮件查询、领取并删除接口的GUI入口。"""
import json,re,html
from pathlib import Path
from datetime import datetime,timezone,timedelta
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent
class MailPage:
    def __init__(self,app,notebook):
        self.app=app;self.data=None;self.buttons=[]
        page=ttk.Frame(notebook,padding=10);self.page=page;notebook.add(page,text='邮件')
        ttk.Label(page,text='使用当前账号和存档。领取附件后邮件会同时删除；请先查看内容，再选择领取。',foreground='#a06000').pack(anchor='w',pady=5)
        actions=ttk.Frame(page);actions.pack(fill='x')
        for text,claim in [('刷新邮件',False),('领取选中邮件附件并删除',True)]:
            b=ttk.Button(actions,text=text,command=lambda c=claim:self.run(c));b.pack(side='left',padx=4);self.buttons.append(b)
        self.status=tk.StringVar(value='尚未读取邮件');ttk.Label(actions,textvariable=self.status).pack(side='left',padx=12)
        frame=ttk.Frame(page);frame.pack(fill='both',expand=True,pady=8)
        self.tree=ttk.Treeview(frame,columns=('title','sender','time'),show='headings',selectmode='browse',height=9)
        for key,title,width in [('title','标题',400),('sender','发件人',140),('time','到期时间（北京时间）',190)]:self.tree.heading(key,text=title);self.tree.column(key,width=width)
        bar=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview);bar.pack(side='right',fill='y');self.tree.configure(yscrollcommand=bar.set);self.tree.pack(fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self.details)
        self.content=tk.Text(page,height=7,wrap='word',state='disabled');self.content.pack(fill='x')
    def render(self,data):
        self.data=data;self.tree.delete(*self.tree.get_children());self.rows={}
        for i,m in enumerate(data['mails']):
            key=str(i);self.rows[key]=m;expiry=m.get('expireTime');text='未提供'
            if isinstance(expiry,(int,float)) and expiry>0:text=datetime.fromtimestamp(expiry/1000,timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
            self.tree.insert('',tk.END,iid=key,values=(m.get('title','无标题'),m.get('sender',''),text))
        self.status.set('槽%s｜%d封邮件'%(data['slot'],len(data['mails'])))
        self.content.configure(state='normal');self.content.delete('1.0',tk.END);self.content.configure(state='disabled')
    def details(self,event=None):
        if not self.tree.selection():return
        m=self.rows[self.tree.selection()[0]]
        text=html.unescape(re.sub('<[^>]+>','\n',m.get('content','')))
        text+='\n附件类型：%s\n附件ID：%s\n数量：%s'%(m.get('type','无'),m.get('subType',''),m.get('count',''))
        self.content.configure(state='normal');self.content.delete('1.0',tk.END);self.content.insert('1.0',text);self.content.configure(state='disabled')
    def run(self,claim=False):
        if self.app.running:return
        if not self.app._save_selected_slot():return
        args=[str(ROOT/'mail_center.py')]
        if claim:
            account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
            if not self.data or self.data['account']!=str(account.get('username','')) or self.data['slot']!=int(self.app.cmb_slot.get()):messagebox.showinfo('邮件','账号或存档已变化，请刷新邮件',parent=self.page);return
            if not self.tree.selection():messagebox.showinfo('邮件','请先选择邮件',parent=self.page);return
            m=self.rows[self.tree.selection()[0]]
            if not messagebox.askyesno('领取并删除邮件','领取“%s”的附件后，该邮件会删除。是否继续？'%m.get('title',''),parent=self.page):return
            args+=['--claim',str(m['id'])]
        self.app._launch(args)
