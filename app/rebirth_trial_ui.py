"""轮回试炼页面，查询后确认操作。"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent
class RebirthTrialPage:
    def __init__(self,app,notebook=None,parent=None):
        self.app=app;self.data=None;self.buttons=[]
        if parent is None:
            self.page=ttk.Frame(notebook,padding=12);notebook.add(self.page,text='轮回试炼')
        else:
            self.page=ttk.LabelFrame(parent,text='轮回试炼 · 前13层及领奖',padding=12)
            self.page.pack(fill='x',padx=4,pady=6)
            self.page._default_expanded=True
        self.summary=tk.StringVar(value='请先查询当前账号与存档的轮回试炼进度。')
        ttk.Label(self.page,textvariable=self.summary).pack(anchor='w',pady=8)
        row=ttk.Frame(self.page);row.pack(fill='x')
        for label,action in [('查询进度','query'),('挑战至第13层','run'),('领取已达成奖励（至13层）','reward')]:
            button=ttk.Button(row,text=label,command=lambda a=action:self.launch(a));button.pack(side='left',padx=4);self.buttons.append(button)
            if action!='query':button._activity_key='RUN_REBIRTH_TRIAL' if action=='run' else 'RUN_REBIRTH_REWARD'
        self.wait=tk.StringVar(value='10')
        row=ttk.Frame(self.page);row.pack(fill='x',pady=12)
        ttk.Label(row,text='每关等待（秒，最低10）：').pack(side='left')
        ttk.Spinbox(row,from_=10,to=3600,textvariable=self.wait,width=8).pack(side='left')
        ttk.Label(self.page,text='最高仅挑战到第13层。1～10层要求出战角色战力14万，11～13层要求56万；不叠加双人战力。战力不足时停在已完成层数，遇到录像要求或异常停止。\n可领取的奖励档位：3、6、9、11、13层。领奖单独确认，不受当前战力限制，不自动购买或重置。',wraplength=950).pack(anchor='w',pady=8)
    def refresh_availability(self,states=None):
        from activity_availability import availability_snapshot
        states=states if states is not None else availability_snapshot()
        for button in self.buttons:
            key=getattr(button,'_activity_key',None)
            if key:button.configure(state='disabled' if self.app.running or states[key]['reason'] else 'normal')
        if not any(states[k]['status']=='open' for k in ('RUN_REBIRTH_TRIAL','RUN_REBIRTH_REWARD')):
            self.page.pack_forget()
        elif not self.page.winfo_manager():
            self.page.pack(fill='x',padx=4,pady=6,before=self.app.activity_task_checks)

    def render(self,data):
        self.data=data
        available=[str(n) for n in (3,6,9,11,13) if data['cur']>=n and data.get('reward',{}).get(str(1800100+n))==1]
        source=data.get('score_source','query')
        total=data.get('total_score')
        if total is None:total=float(data.get('score',0))+(0 if source=='settlement' else data['cur']*10000)
        label='结算总分' if source=='settlement' else '总分'
        extra='' if source=='settlement' else '（附加分%g）'%float(data.get('score',0))
        actor=data.get('combat_power');power_text='｜出战%sP战力%g'%(actor['index']+1,actor['value']) if actor else '｜出战战力待确认'
        self.summary.set('槽%s｜已通关%s层｜%s%g%s%s｜可领取：%s'%(data['slot'],data['cur'],label,total,extra,power_text,'、'.join(available) or '无'))
    def launch(self,action):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            args=[str(ROOT/'rebirth_trial.py'),'--action',action]
            if action!='query':
                from activity_availability import require_open
                require_open('RUN_REBIRTH_TRIAL' if action=='run' else 'RUN_REBIRTH_REWARD')
                a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));d=self.data
                if not d or d['account']!=str(a.get('username','')) or d['slot']!=int(self.app.cmb_slot.get()):raise ValueError('请先查询当前账号与槽位')
                wait=float(self.wait.get())
                if not 10<=wait<=3600:raise ValueError('间隔须为10～3600秒')
                if action=='run' and d['cur']>=13:
                    messagebox.showinfo('已完成','当前已达到13层，无需挑战。',parent=self.page);return
                if action=='run':
                    actor=d.get('combat_power')
                    if not actor:raise ValueError('请先查询确认出战角色战力')
                    need=140000 if d['cur']<10 else 560000
                    if actor['value']<need:raise ValueError('出战角色战力不足下一层要求%s'%need)
                    goal=13 if actor['value']>=560000 else 10
                    text='出战%sP，战力%g\n从已通关%s层最多推进到第%s层，每关等待%s秒。确认挑战？'%(actor['index']+1,actor['value'],d['cur'],goal,wait)
                else:text='领取当前已达成的3、6、9、11、13层奖励，确认领取？'
                if not messagebox.askyesno('轮回试炼',text,parent=self.page):return
                args+=['--account',d['account'],'--slot',str(d['slot']),'--act-id',str(d['actId']),'--wait',str(wait)]
            self.data=None;self.app._launch(args)
        except (ValueError,KeyError,RuntimeError) as e:messagebox.showerror('未执行',str(e),parent=self.page)
