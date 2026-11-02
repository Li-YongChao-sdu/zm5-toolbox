"""黑市筛选及灵魂购买、免费刷新界面。"""
import json
import tkinter as tk
from tkinter import ttk,messagebox
from pathlib import Path
ROOT=Path(__file__).resolve().parent

class BlackMarketPage:
    def __init__(self,app,notebook):
        self.app=app;self.data=None;self.buttons=[];self.rows={}
        self.page=ttk.Frame(notebook,padding=8);notebook.add(self.page,text='黑市')
        self.summary=tk.StringVar(value='使用顶部当前账号及存档，请先读取黑市')
        ttk.Label(self.page,textvariable=self.summary,wraplength=850).pack(fill='x',pady=6)
        ttk.Label(self.page,text='仅显示灵魂商品，以及4折天清气／地浊气（200点券）、风火水土灵参（100点券）。点券商品须使用独立购买确认入口；刷新只走VIP免费路由，用完即停。',wraplength=850,foreground='#b00000').pack(fill='x',pady=6)
        actions=ttk.Frame(self.page);actions.pack(fill='x',pady=6)
        for label,action in [('读取当前黑市','status'),('购买选中灵魂商品（1份）','buy'),('免费刷新一次','refresh')]:
            button=ttk.Button(actions,text=label,command=lambda value=action:self.run(value));button.pack(side='left',padx=(0,10));self.buttons.append(button)
        daily=ttk.Button(actions,text='执行黑市灵魂日常',command=self.run_daily);daily.pack(side='left',padx=(0,10));self.buttons.append(daily)
        ttk.Label(self.page,text='黑市灵魂日常：先买当前灵魂标价的未购商品，再按VIP自动使用当天剩余免费刷新次数继续购买。VIP0～4无免费刷新，VIP5一次，VIP6～8两次；不买点券商品。',wraplength=850).pack(fill='x',pady=4)
        paid=ttk.LabelFrame(self.page,text='黑市独立点券购买',padding=6);paid.pack(fill='x',pady=5)
        from black_market import TICKET_GOODS
        self.allow_ticket=tk.BooleanVar(value=False);self.auto_ticket=tk.BooleanVar(value=False)
        ttk.Checkbutton(paid,text='第一层：允许花点券',variable=self.allow_ticket).pack(anchor='w')
        ttk.Checkbutton(paid,text='第二层：自动购买选中商品',variable=self.auto_ticket).pack(anchor='w')
        goods_frame=ttk.Frame(paid);goods_frame.pack(fill='x',pady=4)
        self.ticket_goods={name:tk.BooleanVar(value=False) for name in ('天清气','地浊气','风灵参','火灵参','土灵参','水灵参')}
        self.ticket_good_checks=[]
        for name,var in self.ticket_goods.items():
            check=ttk.Checkbutton(goods_frame,text='四折%s（%s点券）'%(name,TICKET_GOODS[name]),variable=var)
            check.pack(side='left',padx=3);self.ticket_good_checks.append(check)
        def update_ticket_locks(*_):
            enabled=self.allow_ticket.get() and self.auto_ticket.get()
            for check in self.ticket_good_checks:check.configure(state='normal' if enabled else 'disabled')
        self.allow_ticket.trace_add('write',update_ticket_locks);self.auto_ticket.trace_add('write',update_ticket_locks);update_ticket_locks()
        auto=ttk.Button(paid,text='开始点券自动购买',command=self.run_paid_auto);auto.pack(anchor='w',pady=4);self.buttons.append(auto)

        button=ttk.Button(paid,text='确认购买选中点券商品（1份）',command=self.run_paid);button.pack(side='left');self.buttons.append(button)
        ttk.Label(paid,text='自动购买仅限勾选的四折商品；只使用VIP剩余免费刷新。需开启本页商店独立点券权限并填写预算。',wraplength=700).pack(side='left',padx=8)
        area=ttk.Frame(self.page);area.pack(fill='both',expand=True)
        columns=('id','name','count','cost','discount','state')
        self.tree=ttk.Treeview(area,columns=columns,show='headings',selectmode='browse')
        for key,label,width in zip(columns,['商品ID','商品','获得数量','消耗','折扣','状态'],[100,180,90,160,75,150]):
            self.tree.heading(key,text=label);self.tree.column(key,width=width,stretch=False)
        vertical=ttk.Scrollbar(area,orient='vertical',command=self.tree.yview);horizontal=ttk.Scrollbar(area,orient='horizontal',command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.tree.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        area.rowconfigure(0,weight=1);area.columnconfigure(0,weight=1)
        self.tree.tag_configure('ticket',foreground='red')
        ttk.Label(self.page,text='每次操作都会重新读取服务器状态；购买仅1份。结果及货币／道具核对见下方日志，报告保存至black_market_reports。',wraplength=850).pack(fill='x',pady=6)

    def render(self,data):
        self.data=data;self.rows={r['id']:r for r in data['rows']}
        self.summary.set('槽%s｜VIP%s｜灵魂%s｜点券%s｜免费刷新剩余%s/%s｜%s' % (data['slot'],data['vip'],data['spirit'],data['ticket'],data['free_remaining'],data['free_limit'],'活动黑市' if data['activity'] else '普通黑市'))
        self.tree.delete(*self.tree.get_children())
        for sid,row in self.rows.items():
            self.tree.insert('','end',iid=sid,values=(sid,row['name'],row['count'],row['currency']+'×'+str(row['price']),str(row['discount'])+'折','已购买' if row['bought'] else '需独立点券确认' if row['currency']=='点券' else '可购买'),tags=('ticket',) if row['currency']=='点券' else ())

    def run_paid_auto(self):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            from black_market_paid_auto import selected_goods
            goods=selected_goods([name for name,var in self.ticket_goods.items() if var.get()],self.allow_ticket.get(),self.auto_ticket.get())
            self.app.spend_permissions.require('commerce')
            budget=int(self.app.spend_permissions.budgets['commerce'].get())
            text='自动购买：%s\n本次点券预算上限：%s\n当前列表及VIP免费刷新后，只购买勾选的四折商品。确认开始？'%('、'.join(goods),budget)
            if not messagebox.askyesno('黑市点券自动购买',text,parent=self.page):return
            self.app._launch([str(ROOT/'black_market_paid_auto.py'),'--goods',json.dumps(goods,ensure_ascii=False),'--allow-ticket','--auto-confirm'])
            self.allow_ticket.set(False);self.auto_ticket.set(False)
            for var in self.ticket_goods.values():var.set(False)
        except (ValueError,KeyError) as exc:messagebox.showerror('未执行',str(exc),parent=self.page)

    def run_paid(self):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            if not self.allow_ticket.get():raise ValueError('请先开启允许花点券')
            account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
            if not self.data or self.data['slot']!=int(account.get('record_index',0)) or self.data.get('username')!=account.get('username'):raise ValueError('请先读取当前账号和存档的黑市')
            selected=self.tree.selection()
            if not selected:raise ValueError('请先选中点券商品')
            row=self.rows[selected[0]]
            if row['currency']!='点券' or row['bought']:raise ValueError('请选择当前未购买的点券商品')
            self.app.spend_permissions.require('commerce')
            if int(self.app.spend_permissions.budgets['commerce'].get())<row['price']:raise ValueError('本次点券预算不足')
            text='%s×%s（购买1份）\n将消耗%s点券。\n仅购买此商品，不刷新黑市。是否确认？'%(row['name'],row['count'],row['price'])
            if not messagebox.askyesno('黑市点券购买确认',text,parent=self.page):return
            self.app._launch([str(ROOT/'black_market_paid.py'),'--shop',row['id'],'--price',str(row['price']),'--slot',str(self.data['slot'])])
        except (ValueError,KeyError,OSError) as exc:messagebox.showerror('未购买',str(exc),parent=self.page)

    def run_daily(self):
        if self.app.running or not self.app._save_selected_slot():return
        if not messagebox.askyesno('黑市灵魂日常','购买当前及免费刷新后的全部灵魂商品？\n按实际VIP剩余免费次数执行，不花点券。'):return
        self.app._launch([str(ROOT/'black_market_daily.py')])

    def run(self,action):
        if self.app.running:return
        if not self.app._save_selected_slot():return
        args=[str(ROOT/'black_market.py'),'--action',action]
        if action!='status':
            if not self.data:
                messagebox.showinfo('黑市','请先读取当前黑市');return
            account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
            if int(account.get('record_index',0))!=self.data['slot'] or account.get('username')!=self.data.get('username'):
                messagebox.showinfo('黑市','账号或存档已变更，请先重新读取黑市');return
            if action=='buy':
                selected=self.tree.selection()
                if not selected:messagebox.showinfo('黑市','请选择灵魂商品');return
                row=self.rows[selected[0]]
                if not row['can_buy']:messagebox.showwarning('黑市','此按钮仅购买灵魂商品；点券商品请使用独立确认入口');return
                if not messagebox.askyesno('确认灵魂购买','%s×%s\n消耗灵魂%s，购买1份，是否继续？'%(row['name'],row['count'],row['price'])):return
                args.extend(['--shop',row['id']])
            else:
                if self.data['free_remaining']<=0:messagebox.showinfo('黑市','免费刷新次数已用完');return
                if not messagebox.askyesno('免费刷新','仅使用一次VIP免费刷新机会，是否继续？'):return
        self.app._launch(args)
