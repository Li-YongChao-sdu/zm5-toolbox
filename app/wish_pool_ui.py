"""许愿池：手动逐池设置次数、按道具排序自动筛选，或随机3池各10次。"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from game_version import feature_config_path
import wish_pool_order as order_mod
ROOT=Path(__file__).resolve().parent
POOLS=('彻悟池','无量池','轮回池','圆满池')
class WishPoolPanel:
    def __init__(self,app,parent):
        self.app=app;self.parent=parent;self.data=None;self.buttons=[];self.editor=None
        self.mode=tk.StringVar(value='手动许愿');self.goals={};self.descriptions={};self.rows={}
        row=ttk.Frame(parent);row.pack(fill='x',pady=4);ttk.Label(row,text='许愿方式').pack(side='left');ttk.Combobox(row,textvariable=self.mode,values=['手动许愿','排序许愿','随机许愿'],state='readonly',width=20).pack(side='left',padx=8)
        self.summary=tk.StringVar(value='请先查看当前许愿池');ttk.Label(parent,textvariable=self.summary,wraplength=850).pack(anchor='w',pady=4)
        tools=ttk.Frame(parent);tools.pack(fill='x',pady=3)
        self.button(tools,'查看各池奖励、已许次数与消耗',lambda:self.launch(True))
        self.button(tools,'领取上期奖励',self.claim_prev)
        self.content=ttk.Frame(parent);self.content.pack(fill='x',pady=4)
        self.manual=ttk.Frame(self.content)
        for pool in POOLS:
            row=ttk.Frame(self.manual);row.pack(fill='x',pady=4);self.rows[pool]=row
            text=tk.StringVar(value=pool+'：未查询');self.descriptions[pool]=text
            ttk.Label(row,textvariable=text,width=64,wraplength=520).pack(side='left')
            ttk.Label(row,text='目标次数').pack(side='left');var=tk.StringVar(value='0');self.goals[pool]=var
            ttk.Combobox(row,textvariable=var,values=['0','1','10'],state='readonly',width=5).pack(side='left',padx=4)
            app.ui_settings_fields['许愿池/手动目标/'+pool]=(var,['0','1','10'])
        ttk.Label(self.manual,text='目标包含本期已许次数；0表示不参与。每期最多参与3个不同池，低等级受实际次数上限限制。',wraplength=850).pack(anchor='w',pady=4)
        self.ranked=ttk.Frame(self.content)
        self.rank_text=tk.StringVar(value='请先查看当前许愿池')
        ttk.Label(self.ranked,textvariable=self.rank_text,justify='left',wraplength=850).pack(anchor='w',pady=2)
        rank_tools=ttk.Frame(self.ranked);rank_tools.pack(fill='x',pady=3)
        ttk.Button(rank_tools,text='编辑道具优先级…',command=self.edit_order).pack(side='left')
        ttk.Button(rank_tools,text='刷新排序预览',command=self.refresh_rank).pack(side='left',padx=6)
        ttk.Label(self.ranked,text='规则：大愿望=中奖奖励，小愿望=保底奖励；大愿望排名优于小愿望→许10次，否则1次；按 min(大,小) 排名自动选最多3个池，已参与的池优先保留。',wraplength=850).pack(anchor='w',pady=2)
        self.random=ttk.Label(self.content,text='从当前可参与池随机选最多3个，各补到10次；已有次数计入，不额外再许10次。',wraplength=850)
        self.actions=ttk.Frame(parent);self.actions.pack(fill='x',pady=4)
        self.button(self.actions,'执行当前许愿方案',lambda:self.launch(False))
        self.mode.trace_add('write',self.update_mode);self.update_mode()
        app.ui_settings_fields['许愿池/许愿方式']=(self.mode,['手动许愿','排序许愿','随机许愿'])
    def button(self,parent,text,command):
        b=ttk.Button(parent,text=text,command=command);b.pack(anchor='w',pady=3);self.buttons.append(b)
    def update_mode(self,*_):
        for frame in (self.manual,self.ranked,self.random):frame.pack_forget()
        mode=self.mode.get()
        if mode=='手动许愿':self.manual.pack(fill='x',pady=4)
        elif mode=='排序许愿':self.ranked.pack(fill='x',pady=4);self.refresh_rank()
        else:self.random.pack(fill='x',pady=4)
    def binding(self):
        account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));return str(account['uid']),int(self.app.cmb_slot.get())
    def render(self,state):
        if (str(state['uid']),int(state['slot']))!=self.binding():return False
        self.data=state
        props=json.loads(feature_config_path('Prop').read_text(encoding='utf-8-sig'))
        def name(item):
            pid=item.get('subType')
            return '%s×%s（ID：%s）'%(order_mod.item_name(pid,props) if pid is not None else '未知物品',item.get('count',0),pid if pid is not None else '未知')
        found={c['pool']:c for c in state['cells']}
        for pool in POOLS:
            cell=found.get(pool)
            if not cell:self.descriptions[pool].set(pool+'：当前不可参与');continue
            item=cell['item'];used=state['positions'].get(str(cell['pos']),state['positions'].get(cell['pos'],0));costs=item['consumeCosts'];next_cost=str(costs[used]) if used<len(costs) and used<cell['target'] else '已达上限'
            self.descriptions[pool].set('%s｜已许%s/%s｜下次灵魂%s\n大愿望（中奖）：%s；小愿望（保底）：%s'%(pool,used,cell['target'],next_cost,name(item['reward']),name(item['base'])))
        self.summary.set('当前期：%s｜灵魂%s｜已参与%s/%s个池'%(state['key'],state['spirit'],len(state['positions']),state['maximum']))
        self.refresh_rank();return True
    def refresh_rank(self,*_):
        state=self.data
        try:
            if not state or (str(state['uid']),int(state['slot']))!=self.binding():raise ValueError
        except (OSError,ValueError,KeyError):
            self.rank_text.set('请先点“查看各池奖励…”获取当前许愿池。');return
        order=order_mod.load_order()
        picks=order_mod.select(state['cells'],state['positions'],state['maximum'],order=order)
        picked={int(p['cell']['pos']):p for p in picks}
        props=json.loads(feature_config_path('Prop').read_text(encoding='utf-8-sig'))
        lines=['当前排序预览（最多参与%s个池）：'%state['maximum']]
        for cell in sorted(state['cells'],key=lambda c:int(c['pos'])):
            item=cell.get('item') or {};ev=order_mod.evaluate(cell,order['ranks'])
            used=int(state['positions'].get(str(cell['pos']),state['positions'].get(cell['pos'],0)) or 0)
            cap=int(cell.get('target') or 0) or ev['suggest']
            def side(key):
                data=item.get(key) or {};pid=data.get('subType')
                if pid is None:return '无'
                rank=order['ranks'].get(int(pid))
                return '%s×%s（%s）'%(order_mod.item_name(int(pid),props),data.get('count',0),'未收录' if rank is None else '第%d'%(rank+1))
            plan=picked.get(int(cell['pos']))
            if plan:decision='参与，%s→目标%d次%s'%('追大愿望' if ev['bigBetter'] else '拿小愿望',plan['target'],'（上限%d）'%plan['effective'] if plan['effective']<plan['target'] else '')
            elif used>=min(ev['suggest'],cap):decision='已达标'
            else:decision='未入选'
            lines.append('%s｜%s｜大愿望（中奖）：%s；小愿望（保底）：%s｜已许%d/%d｜%s'%(cell['pool'],'大愿望更值' if ev['bigBetter'] else '小愿望更值',side('reward'),side('base'),used,cap,decision))
        lines.append('执行顺序：'+(' → '.join('%s（%d次）'%(p['cell']['pool'],p['effective']) for p in picks) if picks else '无，请调整排序表或查看最新池子'))
        self.rank_text.set('\n'.join(lines))
    def edit_order(self):
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.lift();self.editor.focus_force();return
        order=order_mod.load_order();items=list(order['items']);roles=order_mod.item_roles()
        big_only=sum(1 for r in roles.values() if r['big'] and not r['small'])
        small_only=sum(1 for r in roles.values() if r['small'] and not r['big'])
        both=sum(1 for r in roles.values() if r['big'] and r['small'])
        top=tk.Toplevel(self.parent);top.title('许愿池道具优先级');top.transient(self.parent.winfo_toplevel());top.geometry('720x560')
        self.editor=top
        ttk.Label(top,text='越靠上越值钱。大愿望排名优于小愿望→许10次，否则1次保底；未收录的道具排最后。',wraplength=660).pack(anchor='w',padx=8,pady=6)
        ttk.Label(top,text='【大】只在大愿望出现；【小】只在小愿望出现；【大/小】两者都有。当前配置：大 %d、小 %d、重叠 %d。'%(big_only,small_only,both),wraplength=660).pack(anchor='w',padx=8,pady=(0,6))
        body=ttk.Frame(top);body.pack(fill='both',expand=True,padx=8)
        box=tk.Listbox(body,height=18,width=56,exportselection=False)
        bar=ttk.Scrollbar(body,orient='vertical',command=box.yview);box.configure(yscrollcommand=bar.set)
        box.pack(side='left',fill='both',expand=True);bar.pack(side='left',fill='y')
        side=ttk.Frame(body);side.pack(side='left',fill='y',padx=8)
        def fill(select=0):
            box.delete(0,'end')
            for index,row in enumerate(items):
                role=roles.get(int(row['id']),{});big=bool(role.get('big'));small=bool(role.get('small'))
                tag='大/小' if big and small else '大' if big else '小' if small else '?'
                box.insert('end','%d. [%s] %s（ID：%s）'%(index+1,tag,row['name'],row['id']))
                box.itemconfig('end',foreground='#c00000' if big and small else '#1f4e79' if big else '#7f6000' if small else '#666666')
            if items:
                select=max(0,min(select,len(items)-1));box.selection_set(select);box.see(select)
        def move(step):
            selected=box.curselection()
            if not selected:return
            index=selected[0];target=index+step
            if 0<=target<len(items):items[index],items[target]=items[target],items[index];fill(target)
        def to_top():
            selected=box.curselection()
            if not selected:return
            index=selected[0]
            if index>0:items.insert(0,items.pop(index));fill(0)
        def to_bottom():
            selected=box.curselection()
            if not selected:return
            index=selected[0]
            if index<len(items)-1:items.append(items.pop(index));fill(len(items)-1)
        ttk.Button(side,text='上移',command=lambda:move(-1)).pack(fill='x',pady=2)
        ttk.Button(side,text='下移',command=lambda:move(1)).pack(fill='x',pady=2)
        ttk.Button(side,text='置顶',command=to_top).pack(fill='x',pady=2)
        ttk.Button(side,text='置底',command=to_bottom).pack(fill='x',pady=2)
        def reset():
            nonlocal items
            items=order_mod.default_items();fill(0)
        ttk.Button(side,text='恢复默认顺序',command=reset).pack(fill='x',pady=(14,2))
        limit=tk.StringVar(value=str(order.get('maxRank') or 0))
        row=ttk.Frame(top);row.pack(fill='x',padx=8,pady=6)
        ttk.Label(row,text='排名门槛：只考虑前 N 名（0=不限）').pack(side='left')
        tk.Spinbox(row,from_=0,to=999,textvariable=limit,width=6).pack(side='left',padx=6)
        def save():
            try:max_rank=max(0,int(limit.get() or 0))
            except ValueError:messagebox.showerror('未保存','排名门槛需为整数',parent=top);return
            order_mod.save_order(items,max_rank);self.refresh_rank();top.destroy()
        buttons=ttk.Frame(top);buttons.pack(fill='x',padx=8,pady=8)
        ttk.Button(buttons,text='保存',command=save).pack(side='right')
        ttk.Button(buttons,text='取消',command=top.destroy).pack(side='right',padx=6)
        fill()
    def configuration(self,required=True):
        label=self.mode.get()
        if label=='随机许愿':return 'random',None
        if not required:return 'manual',None
        uid,slot=self.binding();state=self.data
        if not state or (str(state['uid']),int(state['slot']))!=(uid,slot):raise ValueError('请先查看当前账号存档的许愿池')
        if label=='排序许愿':
            picks=order_mod.select(state['cells'],state['positions'],state['maximum'])
            if not picks:raise ValueError('当前没有符合排序的池子，请调整道具优先级或重新查看许愿池')
            cells=[{'pos':p['cell']['pos'],'wishId':p['cell']['wishId'],'target':p['target']} for p in picks]
            return 'manual',{'uid':uid,'slot':slot,'key':state['key'],'cells':cells}
        found={c['pool']:c for c in state['cells']};cells=[]
        for pool in POOLS:
            goal=int(self.goals[pool].get())
            if goal not in (0,1,10):raise ValueError('目标次数仅支持0、1、10')
            if not goal:continue
            if pool not in found:raise ValueError(pool+'当前不可参与，请将目标设为0')
            c=found[pool];cells.append({'pos':c['pos'],'wishId':c['wishId'],'target':goal})
        if not cells:raise ValueError('请至少为一个池设置目标次数')
        existing={int(k) for k in state['positions']}
        if len(existing|{c['pos'] for c in cells})>state['maximum']:raise ValueError('本期最多参与%s个不同池'%state['maximum'])
        return 'manual',{'uid':uid,'slot':slot,'key':state['key'],'cells':cells}
    def claim_prev(self):
        if self.app.running or not self.app._save_selected_slot():return
        self.app._launch([str(ROOT/'wish_pool_action.py'),'--claim'])
    def launch(self,query):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            uid,slot=self.binding();args=[str(ROOT/'wish_pool_modes.py'),'--uid',uid,'--slot',str(slot)]
            if query:args.append('--query')
            else:
                mode,plan=self.configuration();args+=['--mode',mode]
                if plan:args+=['--plan',json.dumps(plan,ensure_ascii=False)]
                if not messagebox.askyesno('确认许愿','按当前方案消耗灵魂许愿？已有次数计入目标，余额不足即停止。',parent=self.parent):return
            self.app._launch(args)
        except (OSError,ValueError,KeyError) as exc:messagebox.showerror('未执行',str(exc),parent=self.parent)
