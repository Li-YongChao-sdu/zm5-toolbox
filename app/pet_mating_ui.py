"""宠物上推荐界面；密码仅通过子进程环境传递，不保存。"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from pet_mating import FIELDS,build_params
ROOT=Path(__file__).resolve().parent

class PetMatingPage:
    def __init__(self,app,notebook):
        self.app=app;self.data=None;self.buttons=[];self.pets={};self.targets={}
        self.page=ttk.Frame(notebook,padding=10);notebook.add(self.page,text='宠物上推荐')
        self.summary=tk.StringVar(value='先刷新当前账号与槽位的宠物和推荐状态')
        ttk.Label(self.page,textvariable=self.summary,wraplength=950).pack(anchor='w')
        self.button('刷新宠物及上架状态',lambda:self.run('status'))
        self.pet,self.petbox=self.field('自己的宠物','',[])
        self.target,self.targetbox=self.field('希望配对的种类','',[])
        self.pet.trace_add('write',lambda *_:self.change_pet())
        self.target.trace_add('write',lambda *_:self.change_target())
        self.mode,_=self.field('上架方式','普通上架',['普通上架','密码上架'])
        self.password,self.passwordbox=self.field('配对密码','',secret=True)
        self.mode.trace_add('write',lambda *_:self.passwordbox.configure(state='normal' if self.mode.get()=='密码上架' else 'disabled'))
        self.passwordbox.configure(state='disabled')
        ttk.Label(self.page,text='以下填写对方宠物的最低要求，不会改变自己宠物的数值。普通上架提交空密码。').pack(anchor='w',pady=5)
        grid=ttk.Frame(self.page);grid.pack(fill='x');self.values={};self.ranges={}
        for i,(key,label) in enumerate(FIELDS.items()):
            row=i//2;col=(i%2)*3;ttk.Label(grid,text=label).grid(row=row,column=col,sticky='w',padx=6,pady=4)
            v=tk.StringVar(value='1');self.values[key]=v
            ttk.Entry(grid,textvariable=v,width=12).grid(row=row,column=col+1)
            hint=tk.StringVar(value='');self.ranges[key]=hint;ttk.Label(grid,textvariable=hint).grid(row=row,column=col+2,padx=8)
        self.cost=tk.StringVar();ttk.Label(self.page,textvariable=self.cost,wraplength=950).pack(anchor='w',pady=8)
        self.button('预览并确认上推荐',lambda:self.run('apply'))
    def button(self,text,command):
        b=ttk.Button(self.page,text=text,command=command);b.pack(anchor='w',pady=4);self.buttons.append(b)
    def field(self,label,value,choices=None,secret=False):
        row=ttk.Frame(self.page);row.pack(fill='x',pady=4);ttk.Label(row,text=label,width=22).pack(side='left')
        v=tk.StringVar(value=value)
        w=ttk.Combobox(row,textvariable=v,values=choices,state='readonly',width=65) if choices is not None else ttk.Entry(row,textvariable=v,show='*' if secret else '',width=30)
        w.pack(side='left');return v,w
    def render(self,data):
        self.data=data;m=data['listing'];p=m['pet']
        detail=('当前：%s｜%s星｜%s级｜%s｜%s' % (p['name'],p['quality'],p['level'],'待领取' if m['completed'] else '已上架','有密码' if m['has_password'] else '无密码')) if m['present'] else '当前没有上架宠物'
        self.summary.set('槽%s｜%s\n%s' % (data['slot'],detail,'；'.join('%s：%s'%(FIELDS[k],v) for k,v in m['conditions'].items() if v is not None)))
        self.pets={'%s｜%s星｜Lv%s｜%s'%(p['name'],p['quality'],p['level'],p['entityId']):p for p in data['pets']}
        self.petbox.configure(values=list(self.pets));self.pet.set(next(iter(self.pets),''));self.password.set('')
    def change_pet(self):
        p=self.pets.get(self.pet.get());self.targets={t['name']:t for t in p['targets']} if p else {}
        self.targetbox.configure(values=list(self.targets));self.target.set(next(iter(self.targets),''))
    def change_target(self):
        t=self.targets.get(self.target.get())
        for k in FIELDS:self.ranges[k].set('1～%s'%t['maxima'][k] if t else '')
        self.cost.set('需要等级≥%s；消耗%s×%s，背包现有%s。上架会将宠物暂时移出背包。'%(t['level'],t['material_name'],t['count'],t['available']) if t else '没有可上架的成熟形态宠物；基础形态需先在游戏中进化。')
    def run(self,action):
        if self.app.running or not self.app._save_selected_slot():return
        request={}
        try:
            if action=='apply':
                a=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
                if not self.data or self.data['account']!=str(a.get('username','')) or self.data['slot']!=int(self.app.cmb_slot.get()):raise ValueError('账号或槽位已变化，请刷新')
                if self.data['listing']['present']:raise ValueError('已有上架记录，请先在游戏中领取或下架')
                p=self.pets.get(self.pet.get());t=self.targets.get(self.target.get())
                if not p or not t:raise ValueError('请选择可上架的宠物和配对种类')
                values={k:v.get() for k,v in self.values.items()};mode='password' if self.mode.get()=='密码上架' else 'public'
                build_params(p,t,values,mode,self.password.get())
                preview='%s → 配对种类%s\n%s\n%s\n消耗%s×%s，确认上推荐？'%(self.pet.get(),t['name'],self.mode.get(),'；'.join('%s≥%s'%(FIELDS[k],v) for k,v in values.items()),t['material_name'],t['count'])
                if not messagebox.askyesno('确认上推荐',preview,parent=self.page):return
                request={'account':self.data['account'],'slot':self.data['slot'],'entity':p['entityId'],'target':t['id'],'values':values,'mode':mode,'password':self.password.get() if mode=='password' else ''}
        except (ValueError,KeyError) as e:messagebox.showerror('未执行',str(e),parent=self.page);return
        self.password.set('')
        self.app._launch([str(ROOT/'pet_mating.py'),'--action',action],extra_env={'ZM5_PET_MATING_REQUEST':json.dumps(request,ensure_ascii=False)})
