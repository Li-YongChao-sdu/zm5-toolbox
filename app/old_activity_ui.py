"""旧活动商店页及五框控制的五日登录子页。"""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from old_shop import load_catalog, NAMES, price, dated_state, requires_ticket, remaining_text, latest_global_config, MATERIAL_SHOP_CATEGORIES, shop_category

def unlocked(flags):
    return tuple(bool(v) for v in flags) == (True, False, True, False, True)

def ticket_unlocked(flags):
    return tuple(bool(v) for v in flags) == (True, True, True, True, True)

def training_unlocked(flags):
    return tuple(bool(v) for v in flags) == (True, False, True, True, True)

class OldActivityPage:
    def __init__(self, app, notebook):
        self.app = app
        self.page = ttk.Frame(notebook, padding=10)
        notebook.add(self.page, text='刷去益灵花')
        row = ttk.Frame(self.page)
        row.pack(anchor='w', pady=(0, 8))
        self.flags = [tk.BooleanVar(value=False) for _ in range(5)]
        for flag in self.flags:
            ttk.Checkbutton(row, variable=flag, command=self.update_visibility).pack(side='left', padx=3)
        ttk.Label(row,text='',foreground='red',wraplength=700).pack(side='left',padx=12)
        self.tabs = ttk.Notebook(self.page)
        self.tabs.pack(fill='both', expand=True)
        self.buttons=[]
        # Other old activity entries are temporarily hidden.

        self.login = ttk.Frame(self.tabs, padding=12)
        ttk.Label(self.login, text='五日登录', font=('Microsoft YaHei', 13, 'bold')).pack(anchor='w')
        ttk.Label(self.login, text='每日领取一次：第1天10张，第2–4天各15张，第5天20张。', wraplength=700).pack(anchor='w', pady=8)
        ttk.Label(self.login, text='使用工具箱顶部当前账号及存档。与原活动共用领取记录；最终以服务器返回为准。', wraplength=700).pack(anchor='w', pady=4)
        actions = ttk.Frame(self.login)
        actions.pack(anchor='w', pady=12)
        for text,claim in [('查询领取状态',False),('领取今日宝券',True)]:
            button=ttk.Button(actions,text=text,command=lambda value=claim:self.run(value))
            button.pack(side='left',padx=(0,12));self.buttons.append(button)
        ttk.Label(self.login, text='领取天数、宝券到账和点券核对结果显示在下方运行日志。', foreground='gray').pack(anchor='w')
        self.training = ttk.Frame(self.tabs)
        canvas=tk.Canvas(self.training,highlightthickness=0)
        scrollbar=ttk.Scrollbar(self.training,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        body=ttk.Frame(canvas,padding=8);window=canvas.create_window(0,0,window=body,anchor='nw')
        body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        def wheel(event):
            if str(self.training) in self.tabs.tabs() and self.tabs.select()==str(self.training) and str(event.widget).startswith(str(self.training)):
                canvas.yview_scroll(-int(event.delta/120),'units')
        self.page.bind_all('<MouseWheel>',wheel,add='+')
        if callable(getattr(app,'attach_pet_training',None)):app.attach_pet_training(body)
        self.tabs.add(self.training,text='刷益灵花')
        self.tabs.select(self.training)
        self.build_soul_panel()
    def build_soul_panel(self):
        page=ttk.Frame(self.tabs,padding=6);self.tabs.add(page,text='限时灵魂商品')
        row=ttk.Frame(page);row.pack(fill='x',pady=(0,4))
        self.soul_source=tk.StringVar()
        ttk.Label(row,textvariable=self.soul_source,foreground='#0a6').pack(side='left')
        self.soul_current=tk.BooleanVar(value=True)
        ttk.Checkbutton(row,text='仅显示当期',variable=self.soul_current,command=self.render_souls).pack(side='left',padx=10)
        ttk.Button(row,text='重新读取最新配置',command=self.reload_souls).pack(side='left')
        self.soul_summary=tk.StringVar(value='尚未读取配置')
        ttk.Label(page,textvariable=self.soul_summary,wraplength=900).pack(fill='x',pady=3)
        area=ttk.Frame(page);area.pack(fill='both',expand=True,pady=4)
        cols=('id','name','give','cost','limit','shelf','under','state','left')
        self.soul_tree=ttk.Treeview(area,columns=cols,show='headings',height=9,selectmode='browse')
        for key,title,width in zip(cols,['商品ID','商品','获得数量','购买1次消耗','总限购','上架时间','下架时间','日期状态','剩余'],[90,170,75,190,70,150,150,135,120]):
            self.soul_tree.heading(key,text=title);self.soul_tree.column(key,width=width,stretch=False)
        vertical=ttk.Scrollbar(area,orient='vertical',command=self.soul_tree.yview)
        horizontal=ttk.Scrollbar(area,orient='horizontal',command=self.soul_tree.xview)
        self.soul_tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.soul_tree.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        area.rowconfigure(0,weight=1);area.columnconfigure(0,weight=1)
        self.soul_tree.tag_configure('current',foreground='#0a6a0a');self.soul_tree.tag_configure('closed',foreground='gray')
        self.soul_tree.bind('<<TreeviewSelect>>',self.select_soul)
        self.soul_detail=tk.StringVar(value='选择商品查看活动归属与限购明细。')
        ttk.Label(page,textvariable=self.soul_detail,wraplength=950,justify='left').pack(anchor='w',pady=3)
        ttk.Label(page,text='数据来自最新解包的 GlobalBuy.json，仅含灵魂计价且无附加点券的商品；不是服务器实时库存。',foreground='gray',wraplength=900).pack(anchor='w')
        self.reload_souls()

    def reload_souls(self):
        try:
            shops,labels=load_catalog('GlobalBuy');directory=latest_global_config().name
        except Exception as exc:
            self.soul_source.set('读取失败：'+str(exc));return
        self.souls,self.soul_labels=shops,labels
        self.soul_source.set('配置 %s ｜ 灵魂商品 %d 件'%(directory,len(shops)))
        self.render_souls()

    def render_souls(self):
        if not hasattr(self,'souls'):return
        self.soul_tree.delete(*self.soul_tree.get_children())
        rows=[(sid,cfg) for sid,cfg in sorted(self.souls.items(),key=lambda item:int(item[0])) if not self.soul_current.get() or dated_state(cfg)=='商品日期在期内']
        rows.sort(key=lambda item:(dated_state(item[1])!='商品日期在期内',str(item[1].get('underTime'))))
        current=[]
        for sid,cfg in rows:
            state=dated_state(cfg);left=remaining_text(cfg)
            if state=='商品日期在期内':current.append(cfg)
            self.soul_tree.insert('','end',iid=sid,values=(sid,cfg['name'],cfg['sell_count'],price(cfg,self.soul_labels),cfg.get('purchaseMaxNum','-'),cfg.get('shelfTime') or '-',cfg.get('underTime') or '-',state,left),tags=('current',) if state=='商品日期在期内' else ('closed',))
        if current:
            soon=min(current,key=lambda c:str(c.get('underTime')))
            self.soul_summary.set('当期在售 %d 件；最近下架：%s（%s）'%(len(current),soon.get('name'),remaining_text(soon)))
        else:
            self.soul_summary.set('当期没有在售的灵魂商品；共 %d 件历史商品'%len(self.souls))
        self.soul_detail.set('选择商品查看活动归属与限购明细。')

    def select_soul(self,event=None):
        selected=self.soul_tree.selection()
        if not selected:return
        c=self.souls[selected[0]]
        limits='；'.join('%s：%s'%(label,c.get(key) if c.get(key) is not None else '-') for key,label in [('purchaseMaxNum','总限购'),('dayPurchaseMaxNum','日限购'),('weekPurchaseMaxNum','周限购')])
        self.soul_detail.set('%s %s → %s×%s\n价格：%s\n上架：%s；下架：%s（%s）\n%s（-1 表示未配置上限）'%(c['id'],c['name'],c['sell_subType'],c['sell_count'],price(c,self.soul_labels),c.get('shelfTime') or '-',c.get('underTime') or '-',remaining_text(c),limits))
    def build_weekly_shop(self):
        tab=ttk.Frame(self.tabs)
        self.tabs.add(tab,text='每周免费活动商店')
        canvas=tk.Canvas(tab,highlightthickness=0)
        scrollbar=ttk.Scrollbar(tab,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        page=ttk.Frame(canvas,padding=10)
        window=canvas.create_window(0,0,window=page,anchor='nw')
        page.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        def wheel(event):
            if self.tabs.select()==str(tab) and str(event.widget).startswith(str(tab)):
                if canvas.bbox('all') and canvas.bbox('all')[3]>canvas.winfo_height():
                    canvas.yview_scroll(-int(event.delta/120),'units')
        tab.bind_all('<MouseWheel>',wheel,add='+')
        self.weekly_canvas=canvas
        ttk.Label(page,text='本期三项：霜降礼包免费；去灵花、幻之精华需消耗灵魂，不花点券。',wraplength=850).pack(anchor='w',pady=(0,8))
        try:
            gifts,labels=load_catalog('FestivalFree')
            soul,_=load_catalog('GlobalBuy')
            rows=[('FestivalFree',gifts['2069']),('GlobalBuy',soul['90003981']),('GlobalBuy',soul['91000664'])]
        except Exception as exc:
            ttk.Label(page,text='读取本期商品失败：'+str(exc),foreground='red').pack(anchor='w');return
        for source,cfg in rows:
            box=ttk.LabelFrame(page,text=cfg['name'],padding=8)
            box.pack(fill='x',pady=6)
            ids=str(cfg['sell_subType']).replace(';',',').split(',')
            counts=str(cfg['sell_count']).replace(';',',').split(',')
            rewards='；'.join(f'{labels.get(pid,pid)}×{n}' for pid,n in zip(ids,counts))
            ttk.Label(box,text=f"{rewards}\n价格：{price(cfg,labels)}；限领/限购：{cfg.get('purchaseMaxNum')}次\n截止：{cfg.get('underTime')}；{dated_state(cfg)}",wraplength=850).pack(anchor='w')
            actions=ttk.Frame(box);actions.pack(anchor='w',pady=(6,0))
            for label,buy in [('查询余额/状态',False),('免费领取' if source=='FestivalFree' else '使用灵魂购买1份',True)]:
                button=ttk.Button(actions,text=label,command=lambda source=source,cfg=cfg,buy=buy:self.run_weekly(source,cfg,buy))
                button.pack(side='left',padx=(0,10));self.buttons.append(button)
                if buy and dated_state(cfg)!='商品日期在期内':button.configure(state='disabled')

    def run_weekly(self,source,cfg,buy):
        if self.app.running:return
        if buy and dated_state(cfg)!='商品日期在期内':
            messagebox.showwarning('每周免费活动商店','该商品不在配置期限内，未发送请求');return
        if buy and not messagebox.askyesno('确认领取/购买',f"{cfg['name']}\n{price(cfg,load_catalog(source)[1])}\n存档槽：{self.app.cmb_slot.get()}\n是否执行一次？"):return
        if not self.app._save_selected_slot():return
        args=[str(Path(__file__).resolve().parent/'old_shop.py'),'--shop',str(cfg['id']),'--catalog',source]
        if buy:args.append('--buy')
        self.app._launch(args)

    def build_shop_browser(self):
        page=ttk.Frame(self.tabs,padding=6)
        self.tabs.add(page,text='商品购买测试')
        source_row=ttk.Frame(page);source_row.pack(fill='x',pady=(0,5))
        ttk.Label(source_row,text='配置表：').pack(side='left')
        self.catalog_choices={'通用商店（Shop）':'Shop','通用商店--进阶材料快捷购买':'MaterialShop','双十一独立商店（Double11Shop）':'Double11Shop','限时抢购·灵魂商品':'GlobalBuy','节气免费礼包':'FestivalFree'}
        self.catalog_var=tk.StringVar(value=next(iter(self.catalog_choices)))
        sources=ttk.Combobox(source_row,textvariable=self.catalog_var,values=list(self.catalog_choices),state='readonly',width=38)
        sources.pack(side='left');sources.bind('<<ComboboxSelected>>',self.change_catalog)
        self.current_soul=tk.BooleanVar(value=True)
        ttk.Checkbutton(source_row,text='隐藏已过期/未上架商品（按配置日期）',variable=self.current_soul,command=self.filter_shops).pack(side='left',padx=8)
        self.catalog_source='Shop'
        self.material_catalog=False
        try:
            self.shops,self.labels=load_catalog()
        except Exception as exc:
            ttk.Label(page,text='读取商店配置失败：'+str(exc),wraplength=800).pack(anchor='w')
            return
        filters=ttk.Frame(page);filters.pack(fill='x')
        self.types={'全部商店（含常驻及当前活动）':None}
        for typ in sorted({v['type'] for v in self.shops.values()}):
            self.types[f'{typ} · {NAMES.get(typ,"未映射类型")}']=typ
        self.shop_type=tk.StringVar(value=next(iter(self.types)))
        combo=ttk.Combobox(filters,textvariable=self.shop_type,values=list(self.types),state='readonly',width=31)
        self.store_combo=combo
        combo.pack(side='left');combo.bind('<<ComboboxSelected>>',lambda e:self.filter_shops())
        ttk.Label(filters,text='商品名/ID/材料：').pack(side='left',padx=(10,2))
        self.search=tk.StringVar();entry=ttk.Entry(filters,textvariable=self.search,width=22)
        entry.pack(side='left',fill='x',expand=True)
        entry.bind('<Return>',lambda e:self.filter_shops())
        ttk.Button(filters,text='筛选',command=self.filter_shops).pack(side='left',padx=4)
        self.shop_count=tk.StringVar();ttk.Label(page,textvariable=self.shop_count).pack(anchor='w',pady=3)
        ttk.Label(page,text='日期来自配置，不代表实际可购买。包含当前活动与旧商品；每次仅购买1次，可能消耗所列货币。',foreground='gray',wraplength=900).pack(anchor='w')
        area=ttk.Frame(page);area.pack(fill='both',expand=True,pady=4)
        cols=('id','store','name','give','cost','period','end')
        self.goods=ttk.Treeview(area,columns=cols,show='headings',height=10,selectmode='browse')
        for key,title,width in zip(cols,['商品ID','商店类别','商品','获得数量','购买1次消耗','商品日期状态','截止时间'],[85,125,190,75,230,145,160]):
            self.goods.heading(key,text=title);self.goods.column(key,width=width,stretch=False)
        vertical=ttk.Scrollbar(area,orient='vertical',command=self.goods.yview)
        horizontal=ttk.Scrollbar(area,orient='horizontal',command=self.goods.xview)
        self.goods.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self.goods.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        area.rowconfigure(0,weight=1);area.columnconfigure(0,weight=1)
        self.goods.tag_configure('paid',foreground='red')
        self.goods.bind('<<TreeviewSelect>>',self.select_shop)
        self.shop_detail=tk.StringVar(value='请选择商品查看价格、活动归属和限购规则。')
        ttk.Label(page,textvariable=self.shop_detail,wraplength=950,justify='left').pack(anchor='w',pady=3)
        actions=ttk.Frame(page);actions.pack(fill='x',pady=5)
        for text,buy in [('查询当前余额/状态',False),('购买所选商品（1次）',True)]:
            button=ttk.Button(actions,text=text,command=lambda value=buy:self.run_shop(value))
            button.pack(side='left',padx=(0,10));self.buttons.append(button)
            if buy:self.shop_buy_button=button
        ttk.Label(actions,text='结果：下方日志；分享报告：shop_test_reports',foreground='gray').pack(side='left')
        self.filter_shops()

    def change_catalog(self,event=None):
        selection=self.catalog_choices[self.catalog_var.get()]
        source='Shop' if selection=='MaterialShop' else selection
        try:shops,labels=load_catalog(source)
        except Exception as exc:
            messagebox.showerror('读取商店配置',str(exc))
            previous='MaterialShop' if self.material_catalog else self.catalog_source
            self.catalog_var.set(next(k for k,v in self.catalog_choices.items() if v==previous));return
        self.material_catalog=selection=='MaterialShop'
        self.catalog_source=source;self.shops,self.labels=shops,labels
        self.shop_buy_button.configure(text='免费领取所选礼包' if source=='FestivalFree' else '购买所选商品（1次）')
        self.types={'全部商品':None}
        if self.material_catalog:
            self.types.update({label:key for key,label in MATERIAL_SHOP_CATEGORIES.items()})
        else:
            for typ in sorted({v['type'] for v in self.shops.values()}):self.types[f'{typ} · {NAMES.get(typ,"双十一独立商店" if source=="Double11Shop" else "未映射类型")}']=typ
        self.store_combo.configure(values=list(self.types));self.shop_type.set(next(iter(self.types)))
        self.search.set('');self.filter_shops()

    def filter_shops(self):
        typ=self.types[self.shop_type.get()];query=self.search.get().strip().lower()
        self.goods.delete(*self.goods.get_children())
        count=0
        for sid,cfg in sorted(self.shops.items(),key=lambda item:int(item[0])):
            category=shop_category(cfg) if self.catalog_source=='Shop' else cfg['type']
            if self.catalog_source=='Shop' and (category in MATERIAL_SHOP_CATEGORIES)!=self.material_catalog:continue
            if typ is not None and category!=typ:continue
            if self.current_soul.get():
                state=dated_state(cfg)
                if state in ('商品日期已过','尚未到上架时间') or state.startswith('配置隐藏'):continue
            cost=price(cfg,self.labels)
            text=f"{sid} {cfg['name']} {cfg['consume_subType']} {cfg['sell_subType']} {cost}".lower()
            if query and query not in text:continue
            paid=any(v in str(cfg['consume_subType']).split(',') for v in ('ticket','yuanbao','rechargeMoney','rechargeMoney2')) or cfg.get('extTicket') not in (None,-1,'-1',0,'0')
            self.goods.insert('','end',iid=sid,values=(sid,'节气免费礼包' if self.catalog_source=='FestivalFree' else '限时灵魂抢购' if self.catalog_source=='GlobalBuy' else '双十一独立商店' if self.catalog_source=='Double11Shop' else MATERIAL_SHOP_CATEGORIES.get(category,NAMES.get(cfg['type'],f"类型{cfg['type']}")),cfg['name'],cfg['sell_count'],cost,dated_state(cfg),cfg.get('underTime')),tags=('paid',) if paid else ())
            count+=1
        self.shop_count.set(f'{self.catalog_source}：显示 {count} / {len(self.shops)} 件；红色为点券、元宝、充值积分或附加点券相关。')
        self.shop_detail.set('请选择商品查看价格、活动归属和限购规则。')

    def select_shop(self,event=None):
        selected=self.goods.selection()
        if not selected:return
        c=self.shops[selected[0]]
        currency_ids=str(c['consume_subType']).split(',')
        notes=[]
        # 引用之前逐件对应结果；未对应者不猜测活动状态。
        try:
            import json
            path=Path(__file__).resolve().parent/'audit_remaining_activity_shops_20261017/商品活动对应明细.json'
            row=next((v for v in json.loads(path.read_text(encoding='utf-8-sig')) if v['shopId']==int(c['id'])),None)
            if row:notes.append(row['activity_or_entry']+'；'+row['classification'])
        except (OSError,ValueError):pass
        limits='；'.join(f'{label}：{c.get(key)}' for key,label in [('purchaseMaxNum','总限购'),('dayPurchaseMaxNum','日限购'),('weekPurchaseMaxNum','周限购')])
        self.shop_detail.set(f"{c['id']} {c['name']} → {c['sell_type']}/{c['sell_subType']} × {c['sell_count']}\n价格：{price(c,self.labels)}；材料ID：{','.join(currency_ids)}\n商品上架：{c.get('shelfTime')}；下架：{c.get('underTime')}；{limits}（-1为未配置上限）\n"+('对应：'+'；'.join(notes) if notes else '所属活动期限未逐件对应；商品无独立期限不代表永久可买。'))
        if self.catalog_source=='FestivalFree':
            ids=str(c['sell_subType']).split(',');counts=str(c['sell_count']).split(',')
            rewards='；'.join(f'{self.labels.get(pid,pid)}×{n}' for pid,n in zip(ids,counts))
            self.shop_detail.set(f"{c['name']} · 免费领取\n内容：{rewards}\n截止：{c.get('underTime')}；限领：{c.get('purchaseMaxNum')}次\n仅调用免费领奖接口，与付费礼包独立；不调用3200点券礼包的购买接口。")
        if self.catalog_source=='GlobalBuy':
            self.shop_detail.set(f"限时抢购 {c['id']} {c['name']} ×{c['sell_count']}\n价格：{price(c,self.labels)}；个人限购：{c.get('purchaseMaxNum')}；双人档限购：{c.get('purchaseMaxNum_double')}\n{dated_state(c)}；截止：{c.get('underTime')}\n自动读取工具箱内最新配置；更新配置后重新打开工具箱。全服库存不等于个人剩余限购；购买前后余额、道具和次数见日志。")
        if self.catalog_source=='Double11Shop':
            ids=str(c['sell_subType']).split(',');counts=str(c['sell_count']).split(',')
            rewards='；'.join(f'{self.labels.get(pid,pid)}×{n}' for pid,n in zip(ids,counts))
            self.shop_detail.set(f"双十一 {c['id']} {c['name']}\n一次购买包含：{rewards}\n消耗：{price(c,self.labels)}；{dated_state(c)}\n奖池增量：{c.get('pool_yuanbao')}元宝（奖池，不是个人立即到账）\n路由：scene.shopHandler.double11Buy；仅发送shopId。配置隐藏商品保留供手动测试，不代表服务端允许购买。")

    def run_shop(self,buy):
        if self.app.running:return
        selected=self.goods.selection()
        if not selected:
            messagebox.showinfo('商店测试','请先选中一件商品');return
        cfg=self.shops[selected[0]]
        if buy and requires_ticket(cfg):
            try:self.app.spend_permissions.require('commerce')
            except ValueError as exc:
                messagebox.showwarning('商店点券权限',str(exc));return
        if buy and self.catalog_source=='FestivalFree' and dated_state(cfg)!='商品日期在期内':
            messagebox.showwarning('免费礼包','该礼包不在领取期限，未发送请求');return
        if buy and not messagebox.askyesno('确认领取' if cfg.get('freeGift') else '确认购买1次',f"配置：{self.catalog_source}\n商品：{cfg['name']}（ID {cfg['id']}）\n获得：{cfg['sell_count']}\n配置状态：{dated_state(cfg)}\n配置价格：{price(cfg,self.labels)}\n存档槽：{self.app.cmb_slot.get()}\n\n将向服务器发送一次购买请求，以配置所列价格为准；免费礼包不扣费。是否继续？"):
            return
        if not self.app._save_selected_slot():return
        args=[str(Path(__file__).resolve().parent/'old_shop.py'),'--shop',str(cfg['id']),'--catalog',self.catalog_source]
        if buy:args.append('--buy')
        self.app._launch(args)

    def update_visibility(self):
        visible = str(self.login) in self.tabs.tabs()
        if unlocked(flag.get() for flag in self.flags):
            if not visible:
                self.tabs.add(self.login, text='五日登录')
        elif visible:
            self.tabs.forget(self.login)
    def run(self, claim):
        if not unlocked(flag.get() for flag in self.flags) or self.app.running:
            return
        if not self.app._save_selected_slot():
            return
        args=[str(Path(__file__).resolve().parent/'old_login_reward.py')]
        if claim:
            args.append('--claim')
        self.app._launch(args)
