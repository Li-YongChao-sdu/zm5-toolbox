import os,itertools,sys,tkinter as tk
sys.path.insert(0,os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'app'))
from unittest.mock import patch
from tkinter import ttk
from types import SimpleNamespace
import pet_capture_ui

root=tk.Tk();root.withdraw();fields={};calls=[]
app=SimpleNamespace(running=False,feature_buttons=[],ui_settings_fields={},_save_selected_slot=lambda:True,_launch=lambda args,**kw:calls.append((args,kw)))
def frame(parent,title,description):
    f=ttk.LabelFrame(parent,text=title);f.pack();return f
def field(parent,label,value='',values=None,**kw):
    v=tk.StringVar(value=value);fields[label]=v;ttk.Entry(parent,textvariable=v).pack();return v
def button(parent,label,script,args):ttk.Button(parent,text=label,command=lambda:None).pack()
pet_capture_ui.attach_training(root,frame,field,button,lambda v:str(int(v.get())),app)
cycle=next(b for b in app.feature_buttons if b.cget('text')=='一键运行：抓宠 → 早停升级 → 保留3级')
quick=next(w for w in root.winfo_children() if isinstance(w,ttk.LabelFrame) and w.cget('text')=='刷去益灵花 · 一键运行')
pwd_entry=next(c for row in quick.winfo_children() if isinstance(row,ttk.Frame) for c in row.winfo_children() if isinstance(c,ttk.Entry) and str(c.cget('show'))=='*')
def set_password(value):pwd_entry.delete(0,'end');pwd_entry.insert(0,value)
fields['循环轮数（0为持续循环）'].set('3');set_password('private-test')
cycle.invoke();args,kw=calls[-1]
assert '--harvest' not in args and args[args.index('--retain-min')+1]=='3'
assert args[args.index('--mode')+1]=='auto' and args[args.index('--cycles')+1]=='3'
assert '--early-stop' in args and args[args.index('--target-passive')+1]=='3'
assert '--map' not in args
fields['升级副本地图（0＝自动最新主线，可填78等）'].set('78');cycle.invoke();assert calls[-1][0][calls[-1][0].index('--map')+1]=='78'
fields['升级副本地图（0＝自动最新主线，可填78等）'].set('0');cycle.invoke();assert '--map' not in calls[-1][0]
fields['培养方式'].set('旧两段75→101（效率低，仅兼容）');cycle.invoke();assert '--early-stop' not in calls[-1][0]
fields['培养方式'].set('早停（推荐，实测约4分钟/朵）')
assert 'private-test' not in args and kw['extra_env']['ZM5_PET_CAPTURE_PASSWORD']=='private-test'
assert pwd_entry.get()==''
fields['潜能处理'].set('自动遗忘换益灵花（消耗去灵花）');cycle.invoke();assert '--harvest' in calls[-1][0]
set_password('second')
current=next(b for b in app.feature_buttons if b.cget('text').startswith('仅处理当前批次：'))
current.invoke();assert '--harvest' in calls[-1][0] and calls[-1][1]['extra_env']['ZM5_PET_CAPTURE_PASSWORD']=='second'
capture_parent=ttk.Frame(root);pet_capture_ui.attach(capture_parent,frame,field,button,lambda v:str(int(v.get())),app)
assert not any(isinstance(w,ttk.LabelFrame) and str(w.cget('text')).startswith('刷益灵花') for w in capture_parent.winfo_children())
from old_activity_ui import OldActivityPage
notebook=ttk.Notebook(root);app.attach_pet_training=lambda parent:ttk.Label(parent,text='training contents').pack()
with patch('old_activity_ui.load_catalog',return_value=({},{})):
    old=OldActivityPage(app,notebook)
assert str(old.training) in old.tabs.tabs()
assert notebook.tab(old.page,'text')=='刷去益灵花'
assert old.tabs.select()==str(old.training)
for bits in itertools.product((False,True),repeat=5):
    for var,value in zip(old.flags,bits):var.set(value)
    old.update_visibility()
    assert str(old.training) in old.tabs.tabs()
    assert (str(old.login) in old.tabs.tabs())==(bits==(True,False,True,False,True))
    if str(old.training) in old.tabs.tabs():assert old.tabs.tab(old.training,'text')=='刷益灵花'
root.destroy();print('PASS: toolbox build, auto dual mode, secret transport, moved content and all32 five-box visibility patterns')
