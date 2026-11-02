"""背包与个人/超级仓库界面。密码仅传入本次子进程。"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from bag_warehouse import super_rules
ROOT=Path(__file__).resolve().parent
NAMES={'bag':'背包','warehouse':'个人仓库','super':'超级仓库'}
class BagWarehousePage:
    def __init__(self,app,notebook):
        self.app=app;self.data=None;self.buttons=[]
        self.launcher=ttk.Frame(notebook,padding=16);notebook.add(self.launcher,text='背包/仓库')
        ttk.Button(self.launcher,text='打开背包/仓库',command=self.open,width=28).pack(anchor='nw',pady=8)
        self.window=tk.Toplevel(notebook.winfo_toplevel())
        self.window.title('背包/仓库');self.window.geometry('1080x680');self.window.minsize(800,500)
        self.window.withdraw();self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.page=ttk.Frame(self.window,padding=8);self.page.pack(fill='both',expand=True)
        self.summary=tk.StringVar(value='请刷新当前账号、存档的道具列表')
        ttk.Label(self.page,textvariable=self.summary,wraplength=1000).pack(fill='x')
        ttk.Label(self.page,text='材料与消耗品存取；超级仓库受支持物品、通关条件及每周空间点限制，尚未验证成功存取。',foreground='#a06000',wraplength=1000).pack(fill='x',pady=5)
        row=ttk.Frame(self.page);row.pack(fill='x')
        self.button(row,'刷新状态',lambda:self.run())
        self.location=tk.StringVar(value='个人仓库');self.kind=tk.StringVar(value='全部');self.search=tk.StringVar()
        ttk.Label(row,text='右侧仓库：').pack(side='left')
        for var,values in [(self.location,['个人仓库','超级仓库']),(self.kind,['全部','材料','消耗品'])]:
            box=ttk.Combobox(row,textvariable=var,values=values,state='readonly',width=12);box.pack(side='left',padx=4);box.bind('<<ComboboxSelected>>',lambda e:self.filter())
        ttk.Label(row,text='搜索名称/ID：').pack(side='left');ttk.Entry(row,textvariable=self.search,width=22).pack(side='left');self.search.trace_add('write',lambda *a:self.filter())
        panel=ttk.Panedwindow(self.page,orient='horizontal');panel.pack(fill='both',expand=True,pady=6)
        self.trees={};self.active_tree=None
        self.warehouse_title=tk.StringVar(value='个人仓库')
        for side,title in [('bag','背包'),('warehouse',self.warehouse_title)]:
            column=ttk.Frame(panel);panel.add(column,weight=1)
            ttk.Label(column,**({'text':title} if isinstance(title,str) else {'textvariable':title}),font=('Microsoft YaHei',11,'bold')).pack(anchor='w',pady=4)
            table=ttk.Frame(column);table.pack(fill='both',expand=True)
            tree=ttk.Treeview(table,columns=('id','name','kind','count'),show='headings',height=10,selectmode='browse')
            for col,label,width in [('id','道具ID',100),('name','名称',170),('kind','分类',65),('count','数量',65)]:
                tree.heading(col,text=label);tree.column(col,width=width,minwidth=50)
            tree.bind('<<TreeviewSelect>>',lambda e,t=tree:self.details(e,t))
            bar=ttk.Scrollbar(table,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
            self.trees[side]=tree
        self.detail=tk.StringVar(value='选择任一列的物品，查看 Prop.json 说明、品质及出售价格')
        ttk.Label(self.page,textvariable=self.detail,wraplength=950).pack(fill='x')
        actions=ttk.Frame(self.page);actions.pack(fill='x')
        self.count=tk.StringVar(value='1');self.password=tk.StringVar()
        ttk.Label(actions,text='数量').pack(side='left');ttk.Entry(actions,textvariable=self.count,width=7).pack(side='left',padx=4)
        self.button(actions,'MAX',self.set_max)
        ttk.Label(actions,text='二级密码（可留空）').pack(side='left');ttk.Entry(actions,textvariable=self.password,show='*',width=16).pack(side='left',padx=4)
        for text,target in [('存入个人仓库','warehouse'),('取回背包','bag'),('存入超级仓库','super')]:self.button(actions,text,lambda t=target:self.run(t))
        self.button(actions,'出售选中物品',lambda:self.run('sell'))
        ttk.Label(self.page,text='个人仓库存取已在夕阳宏槽0、楚辞槽6空密码往返验证。密码不保存到配置或日志；若服务器返回502，请填写后手动重试。',wraplength=1000).pack(fill='x',pady=5)
    def open(self):
        self.window.deiconify();self.window.lift();self.window.focus_set()
    def close(self):
        self.password.set('');self.window.withdraw()
    def button(self,parent,text,command):
        b=ttk.Button(parent,text=text,command=command);b.pack(side='left',padx=3);self.buttons.append(b)
    def render(self,data):
        self.data=data;parts=[]
        for loc,cap in data['capacity'].items():
            parts.append(NAMES[loc]+' '+ ' / '.join('%s %s/%s'%(k,v['used'],v['max'] if v['max'] is not None else '?') for k,v in cap.items()))
        self.summary.set('槽%s｜点券%s｜'%(data['slot'],data['ticket'])+'；'.join(parts));self.filter()
    def filter(self):
        self.active_tree=None;self.visible={}
        self.warehouse_title.set(self.location.get())
        for tree in self.trees.values():tree.delete(*tree.get_children())
        if not self.data:return
        for i,r in enumerate(self.data['rows']):
            if r['location']!='bag' and NAMES[r['location']]!=self.location.get():continue
            if self.kind.get() not in ('全部',r['kind']):continue
            if self.search.get().strip().lower() not in (r['name']+' '+r['id']).lower():continue
            tree=self.trees['bag' if r['location']=='bag' else 'warehouse']
            key=str(i);self.visible[key]=r;tree.insert('',tk.END,iid=key,values=(r['id'],r['name'],r['kind'],r['count']))
    def details(self,event=None,tree=None):
        tree=tree or self.active_tree
        if tree is None or not tree.selection():return
        self.active_tree=tree
        for other in self.trees.values():
            if other is not tree:other.selection_remove(*other.selection())
        r=self.visible[tree.selection()[0]]
        self.detail.set('%s｜%s（%s）｜品质%s｜%s｜配置价格%s（实际出售收入以服务器为准）\n%s'%(NAMES[r['location']],r['name'],r['id'],r.get('quality','?'),'可出售' if r.get('sellable') else '不可出售',r.get('price','?'),r.get('description','')))
    def set_max(self):
        selected=self.active_tree.selection() if self.active_tree is not None else ()
        if not selected:
            messagebox.showinfo('数量MAX','请先选择背包或仓库中的物品',parent=self.page);return
        item=self.visible.get(selected[0])
        if item:self.count.set(str(item['count']))
    def run(self,target=None):
        if self.app.running:return
        if not self.app._save_selected_slot():return
        args=[str(ROOT/'bag_warehouse.py')]
        if target:
            try:
                account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
                if not self.data or self.data['account']!=str(account.get('username','')) or self.data['slot']!=int(self.app.cmb_slot.get()):raise ValueError('账号或存档已改变，请先刷新状态')
                selected=self.active_tree.selection() if self.active_tree is not None else ()
                if not selected:raise ValueError('请先选择一个道具')
                item=self.visible[selected[0]];source=item['location'];count=int(self.count.get())
                if count<=0 or count>item['count']:raise ValueError('数量须为正整数且不能超过现有数量')
                if target=='sell' and (source!='bag' or not item.get('sellable') or item.get('locked')):raise ValueError('只能出售背包中未锁定且配置允许出售的物品')
                if target!='sell' and (source=='bag')==(target=='bag'):raise ValueError('请选择背包与仓库之间的存取方向')
                note=''
                if 'super' in (source,target):
                    rule=super_rules().get(item['id'])
                    if not rule:raise ValueError('该道具无法放入超级仓库')
                    direction='in' if target=='super' else 'out'
                    note='\n预计消耗空间点：%s；要求已通关关卡ID：%s。最终以服务器为准。'%(int(rule[direction+'_count'])*count,rule['dungeonId_'+direction])
                if not messagebox.askyesno('确认存取','%s ×%s\n%s → %s%s'%(item['name'],count,NAMES[source],('出售（无法撤销）' if target=='sell' else NAMES[target]),note),parent=self.page):return
                if target=='sell':args+=['--sell','--item',item['id'],'--count',str(count)]
                else:args+=['--source',source,'--target',target,'--item',item['id'],'--count',str(count)]
            except (ValueError,KeyError) as exc:
                messagebox.showerror('背包/仓库',str(exc),parent=self.page);return
        password=self.password.get();self.password.set('')
        self.app._launch(args,extra_env={'ZM5_WAREHOUSE_PASSWORD':password})
