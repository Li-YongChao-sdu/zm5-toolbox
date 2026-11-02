import json,uuid
import tkinter as tk
from tkinter import ttk
from category_spend_guard import CATEGORIES,ENV,matched

def page_category(title):
    if title=='免费洗练':return None
    if title in ('点券竞技场／斗宠大会','点券斗宠／竞技场'):return 'daily'
    if title=='日常任务2':return 'rewards'
    if title=='活动副本':return 'festival'
    if title in ('周常副本／领奖','BOSS挑战'):return 'weekly'
    if title in ('日常副本','一键刷图','关卡设置'):return 'dungeons'
    if title=='刷去益灵花':return 'commerce'
    if any(x in title for x in ('商店','背包','仓库','兑换','邮件','黑市')):return 'commerce'
    if any(x in title for x in ('宠','幻兽','洗练','炼丹')) and title not in ('斗神/乱斗','藏宝洞'):return 'cultivation'
    return None

class CategoryPermissions:
    def __init__(self,app):
        self.app=app;self.variables={k:[tk.BooleanVar(master=app.root,value=False) for _ in range(3)] for k in CATEGORIES}
        self.budgets={k:tk.StringVar(master=app.root,value='0') for k in CATEGORIES}
    def mount(self,parent,category):
        if category not in CATEGORIES:return None
        mounted=getattr(parent,'_category_permission_boxes',{})
        previous=mounted.get(category)
        if previous is not None and previous.winfo_exists():return previous
        title,code=CATEGORIES[category];box=ttk.LabelFrame(parent,text=title+' · 独立点券权限',padding=5)
        old=[c for c in parent.winfo_children() if c!=box and c.winfo_manager()=='pack']
        grids=[c for c in parent.winfo_children() if c!=box and c.winfo_manager()=='grid']
        if grids:
            columns=max(int(c.grid_info().get('column',0))+int(c.grid_info().get('columnspan',1)) for c in grids)
            for child in grids:child.grid_configure(row=int(child.grid_info()['row'])+1)
            box.grid(row=0,column=0,columnspan=columns,sticky='ew',padx=4,pady=4)
        else:
            box.pack(fill='x',padx=4,pady=4,**({'before':old[0]} if old else {}))
        ttk.Label(box,text='本类组合 '+code+'；默认000关闭。只授权已登记价格和次数检测的路由，不能解锁未知付费分支。',foreground='#a02020',wraplength=820).pack(anchor='w')
        row=ttk.Frame(box);row.pack(anchor='w')
        for i,var in enumerate(self.variables[category],1):ttk.Checkbutton(row,text='确认'+str(i),variable=var).pack(side='left',padx=5)
        ttk.Label(row,text='本次点券预算：').pack(side='left');ttk.Entry(row,textvariable=self.budgets[category],width=8).pack(side='left')
        mounted[category]=box;parent._category_permission_boxes=mounted
        return box
    def require(self,category):
        bits=''.join('1' if v.get() else '0' for v in self.variables[category])
        try:budget=int(self.budgets[category].get())
        except ValueError:raise ValueError('本类点券预算须为整数')
        if not matched(category,bits) or budget<=0:raise ValueError('请先开启 '+CATEGORIES[category][0]+' 的三框组合 '+CATEGORIES[category][1]+'，并填写本次预算')
    def reset(self,keep_hidden=False):
        for category,values in self.variables.items():
            if keep_hidden and category=='dungeons' and ''.join('1' if v.get() else '0' for v in values)=='001':continue
            for v in values:v.set(False)
        for v in self.budgets.values():v.set('0')
    def environment(self,account,args):
        permissions={}
        if not args[0].endswith('my_daily_runner.py'):
            for category,values in self.variables.items():
                bits=''.join('1' if v.get() else '0' for v in values)
                if matched(category,bits):
                    self.require(category);permissions[category]={'bits':bits,'budget':int(self.budgets[category].get())}
        obj={'token':uuid.uuid4().hex,'uid':str(account['uid']),'slot':int(account.get('record_index',0)),'permissions':permissions}
        self.reset(keep_hidden=True);return {ENV:json.dumps(obj)}
