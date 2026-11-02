"""许愿池：手动查看并逐池设置次数，或随机3池各10次。"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent
POOLS=('彻悟池','无量池','轮回池','圆满池')
class WishPoolPanel:
    def __init__(self,app,parent):
        self.app=app;self.parent=parent;self.data=None;self.buttons=[]
        self.mode=tk.StringVar(value='手动许愿');self.goals={};self.descriptions={};self.rows={}
        row=ttk.Frame(parent);row.pack(fill='x',pady=4);ttk.Label(row,text='许愿方式').pack(side='left');ttk.Combobox(row,textvariable=self.mode,values=['手动许愿','随机许愿'],state='readonly',width=20).pack(side='left',padx=8)
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
        self.random=ttk.Label(self.content,text='从当前可参与池随机选最多3个，各补到10次；已有次数计入，不额外再许10次。',wraplength=850)
        self.actions=ttk.Frame(parent);self.actions.pack(fill='x',pady=4)
        self.button(self.actions,'执行当前许愿方案',lambda:self.launch(False))
        self.mode.trace_add('write',self.update_mode);self.update_mode()
        app.ui_settings_fields['许愿池/许愿方式']=(self.mode,['手动许愿','随机许愿'])
    def button(self,parent,text,command):
        b=ttk.Button(parent,text=text,command=command);b.pack(anchor='w',pady=3);self.buttons.append(b)
    def update_mode(self,*_):
        self.manual.pack_forget();self.random.pack_forget()
        (self.manual if self.mode.get()=='手动许愿' else self.random).pack(fill='x',pady=4)
    def binding(self):
        account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));return str(account['uid']),int(self.app.cmb_slot.get())
    def render(self,state):
        if (str(state['uid']),int(state['slot']))!=self.binding():return False
        self.data=state
        props=json.loads((ROOT/'feature_config/Prop.json').read_text(encoding='utf-8-sig'))
        def name(item):return '%s×%s（ID：%s）'%((props.get(str(item.get('subType'))) or {}).get('name','未知物品'),item.get('count',0),item.get('subType','未知'))
        found={c['pool']:c for c in state['cells']}
        for pool in POOLS:
            cell=found.get(pool)
            if not cell:self.descriptions[pool].set(pool+'：当前不可参与');continue
            item=cell['item'];used=state['positions'].get(str(cell['pos']),state['positions'].get(cell['pos'],0));costs=item['consumeCosts'];next_cost=str(costs[used]) if used<len(costs) and used<cell['target'] else '已达上限'
            self.descriptions[pool].set('%s｜已许%s/%s｜下次灵魂%s\n中奖：%s；保底：%s'%(pool,used,cell['target'],next_cost,name(item['reward']),name(item['base'])))
        self.summary.set('当前期：%s｜灵魂%s｜已参与%s/%s个池'%(state['key'],state['spirit'],len(state['positions']),state['maximum']));return True
    def configuration(self,required=True):
        mode='manual' if self.mode.get()=='手动许愿' else 'random'
        if mode=='random' or not required:return mode,None
        uid,slot=self.binding();state=self.data
        if not state or (str(state['uid']),int(state['slot']))!=(uid,slot):raise ValueError('请先查看当前账号存档的许愿池')
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
        return mode,{'uid':uid,'slot':slot,'key':state['key'],'cells':cells}
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
