"""趣味活动批量入口，所有参数取自原子页面。"""
import json,math,re
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent
class FunBatchPage:
    def __init__(self,app,notebook):
        self.app=app;self.page=ttk.Frame(notebook,padding=10);notebook.add(self.page,text='批量执行');notebook.insert(0,self.page)
        self.rows={};self.buttons=[]
        bar=ttk.Frame(self.page);bar.pack(fill='x',pady=5)
        b=ttk.Button(bar,text='一键执行本页',command=self.run_checked);b.pack(side='left');self.buttons.append(b)
        self.choice=tk.StringVar();self.combo=ttk.Combobox(bar,textvariable=self.choice,state='readonly',width=26);self.combo.pack(side='left',padx=8)
        b=ttk.Button(bar,text='执行所选项',command=lambda:self.run([self.choice.get()]));b.pack(side='left');self.buttons.append(b)
        ttk.Label(self.page,text='一键执行本页仅执行勾选项目，按列表顺序逐项运行。沿用各子页面设置；不调用点券购买或付费刷新。',wraplength=950).pack(anchor='w',pady=6)
        self.add('黑市灵魂日常','black','购买灵魂商品，使用剩余VIP免费刷新')
        self.add('领取采集奖励','reward','当前采集位置；普通领取')
        self.add('派遣宠物采集','start','当前位置、宠物、材料和时长')
        self.add('妖王帖免费抽取','card','使用妖王帖页面填写的次数')
        self.add('仙魄商店购买','shop_selected','购买原商店页面勾选的商品，沿用各自数量')
        self.add('藏宝洞免费挑战','cave','当前挑战方式、次数及间隔；指定码需先查询')
        self.add('领取藏宝洞已发布收益','publish','查询本人已发布关卡并逐个领取仙魄；无已发布关卡跳过')
        self.add('幻兽派遣日常','dispatch','先领取完成奖励，再按原页面偏好和范围派遣')
        self.add('幻兽喂养','feed','当前选中幻兽、喂养方式与次数')
        self.combo.configure(values=list(self.rows));self.choice.set(next(iter(self.rows)))
    def add(self,label,kind,note,sid=None):
        var=tk.BooleanVar(value=False);row=ttk.Frame(self.page);row.pack(fill='x',pady=4)
        ttk.Checkbutton(row,text=label,variable=var,width=28).pack(side='left');ttk.Label(row,text=note).pack(side='left')
        self.rows[label]=(var,kind,sid)
        self.app.ui_settings_fields['趣味批量/'+label]=(var,None)
    def run_checked(self):self.run([label for label,(var,_,_) in self.rows.items() if var.get()])
    def build(self,labels,account,slot,auto=False):
        jobs=[];p=self.app.pet_utility_page
        for label in labels:
            if label not in self.rows:raise ValueError('请选择执行项目')
            _,kind,sid=self.rows[label];args={}
            if kind=='shop_selected':
                jobs.extend(p.selected_shop_jobs());continue
            if kind in ('reward','start'):args['pos']=int(p.pos.get())-1
            if kind=='start':
                material=p.material.get()
                if material not in p.materials:raise ValueError('采集材料无效，请在宠物采集页选择')
                gears=['3小时','6小时','12小时'];gear=p.gear.get() if p.gear.get() in gears else gears[0]
                args.update(collect_id=int(p.materials[material]),gear=gears.index(gear))
                fresh=bool(p.data and p.data['account']==str(account.get('username','')) and p.data['slot']==slot)
                if fresh and p.pet.get() in p.pets:args['entity']=p.pets[p.pet.get()]
                elif auto:args['auto']=True
                else:raise ValueError('请先在宠物采集页查询并选择宠物')
            if kind=='start' and not auto:
                if not p.data or p.data['account']!=str(account.get('username','')) or p.data['slot']!=slot:raise ValueError('请先刷新当前存档的采集状态')
            if kind=='card':
                args['count']=int(p.card_count.get())
                if args['count']<0:raise ValueError('妖王帖次数须为非负整数；0表示跳过')
            if kind=='buy':
                args.update(shop=sid,count=int(p.shop_rows[sid]['count'].get()))
                if not 1<=args['count']<=5:raise ValueError(label+'数量须为1～5')
            if kind=='cave':
                c=self.app.card_cave_target_page;mode=c.mode_key();n=int(c.count.get());wait=float(c.wait.get());code=c.code.get().strip();fingerprint=''
                if not 1<=n<=5 or not math.isfinite(wait) or not 0<=wait<=3600:raise ValueError('藏宝洞次数或间隔无效')
                if mode=='specified':
                    if auto:
                        # 我的日常：指定码在运行时现场核验；无效则按默认推荐最高守备强度挑战。
                        if not re.fullmatch(r'\d+_r\d+_\d+',code):mode='recommend';code=''
                    else:
                        d=c.data
                        if not d or d['account']!=str(account.get('username','')) or d['slot']!=slot or d.get('mode')!=mode or d['code']!=code:raise ValueError('请先在藏宝洞页查询当前指定挑战码')
                        fingerprint=d['fingerprint']
                args.update(matches=n,wait=wait,mode=mode,code=code,fingerprint=fingerprint)
            if kind=='dispatch':
                args.update(positions=[0,1,2] if self.app.var_fairy_daily_scope.get()=='全部可派档位' else [int(self.app.var_fairy_daily_pos.get())-1],preferences=self.app.fairy_preferences.value())
            if kind=='feed':
                f=self.app.fairy_feed_panel;binding=(str(account['uid']),slot);row=None
                if f.binding==binding:
                    row=f.rows.get(f.display.get())
                    if not row and f.selected_id:row=next((r for r in f.rows.values() if r.get('entityId')==f.selected_id),None)
                if not row and auto:
                    try:
                        entry=f.cache.get(binding);rows=[r for r in f.clean_rows(entry.get('fairies',[])) if r.get('role') in (None,f.role_value())]
                        selected=entry.get('selected','')
                        row=next((r for r in rows if r.get('entityId')==selected),None) or (rows[0] if rows else None)
                    except (OSError,ValueError,TypeError):row=None
                if not row and not auto:raise ValueError('请先查询并选择当前存档的幻兽')
                times=int(f.times.get()) if f.times.get().strip() else None
                if times is not None and times<=0:raise ValueError('喂养次数须为正整数')
                args.update(times=times,use_item=f.kind.get()=='妖元',role=f.role_value())
                if row:args['entity_id']=row['entityId']
                else:args['auto']=True
            jobs.append({'label':label,'kind':kind,'args':args})
        return {'uid':str(account['uid']),'slot':slot,'jobs':jobs}
    def run(self,labels):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            if not labels:raise ValueError('请先勾选执行项目')
            account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(self.app.cmb_slot.get());plan=self.build(labels,account,slot)
            if not messagebox.askyesno('趣味活动批量执行','依次执行以下项目，沿用子页面设置：\n'+'\n'.join(labels),parent=self.page):return
            password=self.app.pet_utility_page.password.get() if any(j['kind']=='buy' for j in plan['jobs']) else ''
            self.app._launch([str(ROOT/'fun_batch_runner.py'),'--plan',json.dumps(plan,ensure_ascii=False)],extra_env={'ZM5_PET_UTILITY_PASSWORD':password})
        except (OSError,ValueError,KeyError) as exc:messagebox.showerror('未执行',str(exc),parent=self.page)
