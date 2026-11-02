"""宠物采集及免费资源功能界面。"""
import json
from pathlib import Path
from datetime import datetime,timezone,timedelta
import tkinter as tk
from tkinter import ttk,messagebox
from pet_utilities import table,scrolls
ROOT=Path(__file__).resolve().parent
class PetUtilityPage:
    def __init__(self,app,notebook):
        self.app=app;self.data=None;self.buttons=[];self.pets={};self.goods={}
        self.page=ttk.Frame(notebook,padding=8);notebook.add(self.page,text='宠物采集')
        self.pages={'宠物采集':self.page}
        self.permission_parents={'宠物采集':self.page}
        self.summary=tk.StringVar(value='请先刷新当前账号与存档状态');ttk.Label(self.page,textvariable=self.summary,wraplength=1000).pack(fill='x')
        self.button(self.page,'刷新采集、免费次数与仙魄限购状态',lambda:self.run('status'))
        tabs=ttk.Notebook(self.page);tabs.pack(fill='both',expand=True)
        self.collect_tabs=tabs
        collect=self.scroll_page(tabs,'采集任务')
        self.slots=ttk.Treeview(collect,columns=('pos','name','pet','state'),show='headings',height=4)
        for key,title,width in [('pos','位置',60),('name','采集材料',140),('pet','宠物',150),('state','状态／完成时间（北京时间）',340)]:self.slots.heading(key,text=title);self.slots.column(key,width=width)
        self.slots.pack(fill='x',pady=5)
        self.pos=self.field(collect,'采集位置','1',['1','2','3'])
        cfg=table('Collect');self.materials={v.get('name',str(k))+'（'+str(k)+'）':str(k) for k,v in sorted(cfg.items(),key=lambda kv:int(kv[1].get('order',0)))}
        self.material=self.field(collect,'采集材料',next(iter(self.materials)),list(self.materials))
        self.photo_summary=tk.StringVar(value='刷新后显示照片收集进度及当前材料缺图')
        ttk.Label(collect,textvariable=self.photo_summary,wraplength=850,justify='left').pack(fill='x',pady=5)
        self.last_photo=tk.StringVar(value='本次出片结果：尚未在此页面领取采集奖励')
        ttk.Label(collect,textvariable=self.last_photo,wraplength=850,justify='left').pack(fill='x',pady=4)
        self.material.trace_add('write',lambda *_:self.update_photos())
        self.pet,self.pet_box=self.field(collect,'派遣宠物','',[],return_widget=True)
        self.gear,self.gear_box=self.field(collect,'采集时间','3小时',['3小时'],return_widget=True)
        row=ttk.Frame(collect);row.pack(fill='x',pady=4)
        self.button(row,'派遣选中宠物',lambda:self.run('start'));self.button(row,'领取选中位置（普通）',lambda:self.run('reward'))
        ttk.Label(collect,text='使用空闲或已领奖的位置；采集材料的关卡解锁要求以服务器为准。普通领取固定不翻倍、不强制图鉴，不使用点券加速。',wraplength=900).pack(fill='x',pady=6)
        album=self.scroll_page(tabs,'采集相册')
        ttk.Label(album,text='读取当前存档服务器相册。可查看已收集与缺失照片；这里不删除照片、不领取相册奖励。',wraplength=850).pack(fill='x',pady=5)
        self.button(album,'刷新相册（同时刷新采集状态）',lambda:self.run('status'))
        self.album_filter=self.field(album,'照片状态','全部',['全部','已收集','未收集'])
        self.album_scope=self.field(album,'照片范围','全部照片',['全部照片','当前采集材料'])
        self.album_summary=tk.StringVar(value='请刷新相册')
        ttk.Label(album,textvariable=self.album_summary,wraplength=850).pack(fill='x',pady=4)
        holder=ttk.Frame(album);holder.pack(fill='both',expand=True,pady=5)
        self.album_tree=ttk.Treeview(holder,columns=('id','name','group','state','pet','time'),show='headings',height=14)
        for key,title,width in [('id','ID',50),('name','照片名称',160),('group','所属区域',130),('state','收集状态',80),('pet','采集宠物',160),('time','获得时间（北京时间）',170)]:
            self.album_tree.heading(key,text=title);self.album_tree.column(key,width=width)
        bar=ttk.Scrollbar(holder,orient='vertical',command=self.album_tree.yview)
        self.album_tree.configure(yscrollcommand=bar.set);self.album_tree.pack(side='left',fill='both',expand=True);bar.pack(side='right',fill='y')
        self.album_filter.trace_add('write',lambda *_:self.update_album())
        self.album_scope.trace_add('write',lambda *_:self.update_album())
        cards=self.scroll_page(notebook,'妖王帖')
        self.pages['妖王帖']=notebook.nametowidget(notebook.tabs()[-1])
        self.permission_parents['妖王帖']=cards
        ttk.Label(cards,textvariable=self.summary,wraplength=1000).pack(fill='x')
        self.button(cards,'刷新免费次数',lambda:self.run('status'))
        self.card_status=tk.StringVar(value='请刷新免费次数');ttk.Label(cards,textvariable=self.card_status).pack(anchor='w',pady=10)
        ttk.Label(cards,text='每日免费次数：VIP0为1次，VIP1–2为2次，VIP3–8为3次。每抽一次重新核对免费计数；不足即停，不消耗招募道具，不执行精英招募。',wraplength=850).pack(anchor='w',pady=5)
        self.card_count=self.field(cards,'本次抽取次数','1')
        self.button(cards,'按指定次数免费抽取',lambda:self.run('card'))
        shop=self.scroll_page(notebook,'藏宝仙魄商店')
        self.pages['藏宝仙魄商店']=notebook.nametowidget(notebook.tabs()[-1])
        self.permission_parents['藏宝仙魄商店']=shop
        ttk.Label(shop,textvariable=self.summary,wraplength=1000).pack(fill='x')
        self.button(shop,'刷新仙魄余额和限购次数',lambda:self.run('status'))
        self.shop_status=tk.StringVar(value='请刷新仙魄余额和限购次数');ttk.Label(shop,textvariable=self.shop_status).pack(anchor='w',pady=8)
        self.goods={str(k):v for k,v in scrolls().items()};self.shop_rows={}
        grid=ttk.Frame(shop);grid.pack(fill='x',pady=6)
        for col,title in enumerate(['选购卷轴','仙魄单价','今日已购','剩余次数','本次购买数量']):
            ttk.Label(grid,text=title,font=('Microsoft YaHei',10,'bold')).grid(row=0,column=col,padx=8,pady=5,sticky='w')
        grid.columnconfigure(0,weight=1)
        for row,(sid,cfg) in enumerate(self.goods.items(),1):
            selected=tk.BooleanVar(value=False)
            ttk.Checkbutton(grid,text=cfg['name'],variable=selected).grid(row=row,column=0,padx=8,pady=5,sticky='w')
            ttk.Label(grid,text=cfg['consume_count']).grid(row=row,column=1,padx=8,sticky='w')
            used=tk.StringVar(value='未读取');remain=tk.StringVar(value='未读取');number=tk.StringVar(value='5')
            ttk.Label(grid,textvariable=used).grid(row=row,column=2,padx=8,sticky='w')
            ttk.Label(grid,textvariable=remain).grid(row=row,column=3,padx=8,sticky='w')
            ttk.Entry(grid,textvariable=number,width=8).grid(row=row,column=4,padx=8,sticky='w')
            self.shop_rows[sid]={'used':used,'remaining':remain,'count':number,'selected':selected}
            app.ui_settings_fields['仙魄商店/'+sid+'/选购']=(selected,None)
            app.ui_settings_fields['仙魄商店/'+sid+'/数量']=(number,None)
        self.password=self.field(shop,'二级密码（可留空）','',secret=True)
        self.button(shop,'购买勾选商品',lambda:self.app.fun_batch_page.run(['仙魄商店购买']))
        ttk.Label(shop,text='勾选需要购买的商品并填写每次购买数量，设置保留供下次使用。批量执行和我的日常统一使用“仙魄商店购买”项目；执行前重新检查余额及剩余限购，失败不重发。',wraplength=850).pack(anchor='w',pady=8)
        for key,var,choices in [('位置',self.pos,['1','2','3']),('材料',self.material,list(self.materials))]:app.ui_settings_fields['采集藏宝/'+key]=(var,choices)
    def scroll_page(self,tabs,title):
        outer=ttk.Frame(tabs);tabs.add(outer,text=title)
        outer.rowconfigure(0,weight=1);outer.columnconfigure(0,weight=1)
        canvas=tk.Canvas(outer,highlightthickness=0)
        vertical=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
        horizontal=ttk.Scrollbar(outer,orient='horizontal',command=canvas.xview)
        canvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        canvas.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
        body=ttk.Frame(canvas,padding=10);window=canvas.create_window(0,0,window=body,anchor='nw')
        def resize(event=None):
            canvas.itemconfigure(window,width=max(canvas.winfo_width(),body.winfo_reqwidth()))
            canvas.configure(scrollregion=canvas.bbox('all'))
        body.bind('<Configure>',resize);canvas.bind('<Configure>',resize)
        def wheel(event):
            # Comboboxes retain their own scrolling; other descendants scroll this page.
            if isinstance(event.widget,ttk.Combobox):return
            canvas.yview_scroll(-int(event.delta/120),'units');return 'break'
        tag='PetUtilityScroll'+str(canvas)
        canvas.bind_class(tag,'<MouseWheel>',wheel)
        def bind_children():
            def visit(widget):
                widget.bindtags((tag,)+widget.bindtags())
                for child in widget.winfo_children():visit(child)
            visit(body)
            canvas.bindtags((tag,)+canvas.bindtags())
            resize()
        body.after_idle(bind_children)
        return body
    def field(self,parent,label,value,choices=None,secret=False,return_widget=False):
        row=ttk.Frame(parent);row.pack(fill='x',pady=3);ttk.Label(row,text=label,width=22).pack(side='left');var=tk.StringVar(value=value)
        widget=ttk.Combobox(row,textvariable=var,values=choices,state='readonly',width=55) if choices is not None else ttk.Entry(row,textvariable=var,width=30,show='*' if secret else '')
        widget.pack(side='left');return (var,widget) if return_widget else var
    def button(self,parent,label,command):
        b=ttk.Button(parent,text=label,command=command);b.pack(anchor='w',pady=3);self.buttons.append(b)
    def render(self,data):
        self.data=data;self.summary.set('槽%s｜VIP%s｜点券%s｜仙魄%s'%(data['slot'],data['card']['vip'],data['ticket'],data['fairyMoney']))
        self.slots.delete(*self.slots.get_children())
        for s in data['slots']:
            when='空闲'
            if s.get('collectId'):
                when='已领奖' if s.get('reward') else ('可领取' if s['finished'] else '采集中')
                if s.get('finishTime'):when+='｜'+datetime.fromtimestamp(s['finishTime']/1000,timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')
            self.slots.insert('',tk.END,values=(s['pos']+1,s['name'],(s.get('pet') or {}).get('nickName') or (s.get('pet') or {}).get('name',''),when))
        self.pets={('%s｜Lv%s｜%s'%(p['name'],p['level'],p['entityId'])):p['entityId'] for p in data['pets'] if not p['busy']}
        self.pet_box.configure(values=list(self.pets))
        if self.pet.get() not in self.pets:self.pet.set(next(iter(self.pets),''))
        gears=['3小时','6小时','12小时'][:min(2,data['collectGear'])+1];self.gear_box.configure(values=gears)
        if self.gear.get() not in gears:self.gear.set(gears[0])
        q=data['card'];self.card_count.set(str(q['remaining']));self.card_status.set('VIP%s｜每日免费%s次｜已用%s次｜剩余%s次'%(q['vip'],q['limit'],q['used'],q['remaining']));self.update_shop();self.update_photos()
        r=data.get('last_photo_result')
        if r:
            text={'none':'本次未获得新照片（photoId=0；不能区分未命中与重复过滤）','unknown':'回包没有照片字段，无法判断','failed':'领取失败，未判定出片'}.get(r.get('outcome'))
            if text is None:text='本次照片：%s［%s］；%s'%((r.get('photo') or {}).get('name','未知照片'),r.get('photoId'),'相册到账已核对' if r.get('outcome')=='confirmed' else '相册变化尚未确认')
            self.last_photo.set(text+'\n服务器rate：'+str(r.get('rate','未下发')))
        else:self.last_photo.set('本次出片结果：尚未在此页面领取采集奖励')
    def update_photos(self):
        if not self.data:return
        status=self.data.get('photo_status') or {}
        if not status.get('known'):
            self.photo_summary.set('服务器未下发相册，缺图状态未知');self.update_album();return
        missing=(self.data.get('photo_by_material') or {}).get(self.materials.get(self.material.get()),[])
        names='、'.join('%s[%s]'%(p['name'],p['id']) for p in missing) or '已集齐／该材料无对应照片'
        self.photo_summary.set('相册：%s/%s；全相册缺%s张\n当前选择材料尚缺：%s'%(status['owned'],status['total'],len(status['missing']),names))
        self.update_album()

    def update_album(self):
        self.album_tree.delete(*self.album_tree.get_children())
        if not self.data:return
        status=self.data.get('photo_status') or {}
        if not status.get('known'):
            self.album_summary.set('服务器未下发相册，不能将未知状态当作全部缺失');return
        rows=status.get('photos') or []
        if self.album_scope.get()=='当前采集材料':
            cfg=table('Collect').get(self.materials.get(self.material.get()),{})
            ids=str(cfg.get('photoId','-1')).split(';');rows=[r for r in rows if str(r['id']) in ids]
        mode=self.album_filter.get()
        rows=[r for r in rows if mode=='全部' or (mode=='已收集')==r['owned']]
        for r in rows:
            when=''
            if r.get('time'):
                try:when=datetime.fromtimestamp(float(r['time'])/1000,timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError,TypeError,OverflowError,OSError):when='时间格式未知'
            pet=r.get('pet','')
            if pet and r.get('level'):pet+=' Lv'+str(r['level'])
            self.album_tree.insert('',tk.END,values=(r['id'],r['name'],r['group'],'已收集' if r['owned'] else '未收集',pet,when))
        self.album_summary.set('全相册 %s/%s｜缺%s张｜当前列表%s张'%(status['owned'],status['total'],len(status['missing']),len(rows)))

    def update_shop(self):
        if not self.data:return
        self.shop_status.set('仙魄余额：%s｜各卷轴每日独立限购5份'%self.data['fairyMoney'])
        for g in self.data['scrolls']:
            row=self.shop_rows.get(str(g['id']))
            if not row:continue
            row['used'].set('%s／5'%(5-g['remaining']))
            row['remaining'].set(str(g['remaining']))
            # 刷新余额与限购不覆盖用户保存的购买数量。
    def selected_shop_jobs(self):
        jobs=[]
        for sid,cfg in self.goods.items():
            row=self.shop_rows[sid]
            if not row['selected'].get():continue
            count=int(row['count'].get())
            if not 1<=count<=5:raise ValueError(cfg['name']+'购买数量须为1～5')
            jobs.append({'label':'仙魄购买：'+cfg['name'],'kind':'buy','args':{'shop':sid,'count':count}})
        if not jobs:raise ValueError('请先在藏宝仙魄商店勾选要购买的商品')
        return jobs

    def run(self,action,shop_id=None):
        if self.app.running:return
        if not self.app._save_selected_slot():return
        args=[str(ROOT/'pet_utilities.py'),'--action',action]
        if action!='status':
            try:
                account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
                if not self.data or self.data['account']!=str(account.get('username','')) or self.data['slot']!=int(self.app.cmb_slot.get()):raise ValueError('账号或存档已变化，请刷新状态')
                if action in ('start','reward'):args+=['--pos',str(int(self.pos.get())-1)]
                if action=='start':
                    if self.pet.get() not in self.pets:raise ValueError('没有可派遣的宠物')
                    args+=['--collect-id',self.materials[self.material.get()],'--entity',self.pets[self.pet.get()],'--gear',str(['3小时','6小时','12小时'].index(self.gear.get()))]
                if action=='card':
                    count=int(self.card_count.get())
                    if count<=0 or count>self.data['card']['remaining']:raise ValueError('次数须为正整数，且不能超过剩余免费次数')
                    args+=['--count',str(count)]
                message={'start':'派遣该宠物采集所选材料？','reward':'领取所选位置的普通采集奖励？不翻倍，不强制图鉴。','card':('消耗%s次免费普通妖王帖招募机会？'%self.card_count.get())}.get(action)
                if action=='buy':
                    sid=str(shop_id)
                    if sid not in self.shop_rows:raise ValueError('请选择对应卷轴的购买按钮')
                    count=int(self.shop_rows[sid]['count'].get());g=next(g for g in self.data['scrolls'] if str(g['id'])==sid)
                    if count<=0 or count>g['remaining']:raise ValueError('购买数量超出剩余限额')
                    cost=g['price']*count
                    if self.data['fairyMoney'] is None or self.data['fairyMoney']<cost:raise ValueError('仙魄不足')
                    args+=['--shop',sid,'--count',str(count)];message='购买%s ×%s，消耗仙魄%s？'%(g['name'],count,cost)
                if not messagebox.askyesno('确认操作',message,parent=self.page):return
            except (ValueError,KeyError) as exc:messagebox.showerror('操作未执行',str(exc),parent=self.page);return
        password=self.password.get();self.password.set('')
        self.app._launch(args,extra_env={'ZM5_PET_UTILITY_PASSWORD':password if action=='buy' else ''})
