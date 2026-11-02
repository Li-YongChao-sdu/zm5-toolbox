"""幻兽偏好分档及档内顺序编辑器。"""
import json
import tkinter as tk
from tkinter import ttk
from fairy_preferences import REWARDS,STRATEGIES,normalize

class FairyPreferenceSettings:
    def __init__(self,app,parent):
        self.loading=False;self.groups=[[],[],[]]
        self.state=tk.StringVar(master=app.root,value=json.dumps(normalize(),ensure_ascii=False))
        self.enabled=tk.BooleanVar(master=app.root,value=False)
        self.strategy=tk.StringVar(master=app.root,value=STRATEGIES[3])
        self.fill=tk.BooleanVar(master=app.root,value=False)
        self.note=tk.StringVar(master=app.root)
        self.box=ttk.LabelFrame(parent,text='奖励偏好与档内顺序',padding=6);self.box.pack(fill='x',pady=6)
        self.box._default_expanded=True
        row=ttk.Frame(self.box);row.pack(fill='x')
        ttk.Checkbutton(row,text='启用奖励偏好',variable=self.enabled).pack(side='left')
        ttk.Combobox(row,textvariable=self.strategy,values=list(STRATEGIES.values()),state='readonly',width=29).pack(side='left',padx=6)
        ttk.Checkbutton(self.box,text='免费刷新用尽后，允许其他可派任务补位（方案②始终补位）',variable=self.fill).pack(anchor='w')
        columns=ttk.Frame(self.box);columns.pack(fill='x',pady=4);self.lists=[];self.add_vars=[];self.group_frames=[]
        for tier in range(3):
            frame=ttk.LabelFrame(columns,text='第%s优先级'%(tier+1),padding=4);frame.pack(side='left',fill='both',expand=True,padx=3)
            self.group_frames.append(frame)
            frame._default_expanded=True
            var=tk.StringVar(master=app.root,value=next(iter(REWARDS)));self.add_vars.append(var)
            addrow=ttk.Frame(frame);addrow.pack(fill='x')
            ttk.Combobox(addrow,textvariable=var,values=list(REWARDS),state='readonly',width=12).pack(side='left')
            ttk.Button(addrow,text='添加',command=lambda t=tier:self.add(t)).pack(side='left',padx=3)
            box=tk.Listbox(frame,height=4,exportselection=False);box.pack(fill='both',expand=True,pady=3);self.lists.append(box)
            buttons=ttk.Frame(frame);buttons.pack(fill='x')
            ttk.Button(buttons,text='上移',command=lambda t=tier:self.move(t,-1)).pack(side='left')
            ttk.Button(buttons,text='下移',command=lambda t=tier:self.move(t,1)).pack(side='left')
            ttk.Button(buttons,text='移除',command=lambda t=tier:self.remove(t)).pack(side='left')
        ttk.Label(self.box,text='同档从上到下决定当前任务的派遣顺序，不为档内顺序额外刷新。①②支持分档及档内顺序；③只用一个有序列表，命中任一偏好就派遣。未启用偏好时沿用原派遣流程。①②刷新可能刷掉其他已有偏好任务。刷新会影响所有空闲档位，自动刷新建议选全部可派档位。',wraplength=900).pack(anchor='w')
        ttk.Label(self.box,textvariable=self.note,wraplength=900).pack(anchor='w')
        for var in (self.enabled,self.strategy,self.fill):var.trace_add('write',self.commit)
        self.state.trace_add('write',self.restore)
        app.ui_settings_fields['幻兽派遣/奖励偏好排序']=(self.state,None)
        self.commit()
    def value(self):
        strategy=next(k for k,v in STRATEGIES.items() if v==self.strategy.get())
        return normalize({'enabled':self.enabled.get(),'strategy':strategy,'groups':self.groups,'fill':self.fill.get()})
    def render(self):
        for widget,group in zip(self.lists,self.groups):
            widget.delete(0,'end')
            for index,name in enumerate(group,1):widget.insert('end','%s. %s'%(index,name))
    def layout(self):
        single=self.strategy.get()==STRATEGIES[3]
        for tier,frame in enumerate(self.group_frames):
            title='奖励先后顺序' if single and tier==0 else '第%s优先级'%(tier+1)
            frame.configure(text=title)
            adapter=getattr(frame,'_collapse_adapter',None)
            if adapter is not None:
                adapter.title=title;adapter.button.configure(text=('▸ ' if adapter.collapsed else '▾ ')+title)
            if single and tier>0:frame.pack_forget()
            elif not frame.winfo_manager():frame.pack(side='left',fill='both',expand=True,padx=3)

    def commit(self,*_):
        if self.loading:return
        self.layout()
        try:value=self.value()
        except (ValueError,StopIteration) as exc:self.note.set(str(exc));return
        if self.groups!=value['groups']:
            self.groups=[list(g) for g in value['groups']];self.render()
        self.note.set('当前未启用奖励偏好。' if not value['enabled'] else '执行顺序：先领取全部已完成奖励，再按档位及档内顺序派遣；只用免费刷新。')
        self.loading=True
        try:self.state.set(json.dumps(value,ensure_ascii=False))
        finally:self.loading=False
    def restore(self,*_):
        if self.loading:return
        try:value=normalize(json.loads(self.state.get()))
        except (ValueError,TypeError):self.note.set('已保存的奖励偏好无效，请重新设置');return
        self.loading=True
        try:
            self.groups=[list(g) for g in value['groups']];self.enabled.set(value['enabled']);self.strategy.set(STRATEGIES[value['strategy']]);self.fill.set(value['fill']);self.render()
        finally:self.loading=False
        self.commit()
    def add(self,tier):
        name=self.add_vars[tier].get()
        if any(name in group for group in self.groups):self.note.set('该奖励已在优先级列表中，请先移除再调整档位');return
        self.groups[tier].append(name);self.render();self.lists[tier].selection_set(len(self.groups[tier])-1);self.commit()
    def move(self,tier,direction):
        chosen=self.lists[tier].curselection()
        if not chosen:return
        index=chosen[0];other=index+direction
        if not 0<=other<len(self.groups[tier]):return
        self.groups[tier][index],self.groups[tier][other]=self.groups[tier][other],self.groups[tier][index]
        self.render();self.lists[tier].selection_set(other);self.commit()
    def remove(self,tier):
        chosen=self.lists[tier].curselection()
        if not chosen:return
        del self.groups[tier][chosen[0]];self.render();self.commit()
