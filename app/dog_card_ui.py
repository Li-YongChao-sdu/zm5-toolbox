import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from union_boss_batch import DOG_NAMES
ROOT=Path(__file__).resolve().parent

def open_window(app):
    old=getattr(app,'dog_card_window',None)
    if old is not None and old.winfo_exists():old.deiconify();old.lift();return
    w=tk.Toplevel(app.root);app.dog_card_window=w;w.title('狗卡管理');w.geometry('720x680');w.minsize(620,500)
    ttk.Label(w,text='使用主窗口当前账号和槽位；查询及操作结果在下方表格显示。').pack(anchor='w',padx=10,pady=8)
    frame=ttk.LabelFrame(w,text='激活所选狗卡（默认博美汪）');frame.pack(fill='x',padx=10)
    selected={}
    for n,name in enumerate(DOG_NAMES,1):
        v=tk.BooleanVar(value=n==1);selected[n]=v;ttk.Checkbutton(frame,text=name,variable=v).grid(row=(n-1)//4,column=(n-1)%4,sticky='w',padx=6)
    gift=tk.StringVar(value=DOG_NAMES[0]);row=ttk.Frame(w);row.pack(fill='x',padx=10,pady=8)
    ttk.Label(row,text='赠送品种：').pack(side='left');ttk.Combobox(row,textvariable=gift,values=DOG_NAMES,state='readonly',width=15).pack(side='left')
    code=tk.StringVar();codes=ttk.Frame(w);codes.pack(fill='x',padx=10)
    ttk.Label(codes,text='兑换码：').pack(side='left');ttk.Entry(codes,textvariable=code,width=35).pack(side='left')
    result_status=tk.StringVar(value='尚未查询，请先查询当前账号库存。')
    result_box=ttk.LabelFrame(w,text='当前狗卡库存与操作结果');result_box.pack(side='bottom',fill='both',expand=True,padx=10,pady=8)
    ttk.Label(result_box,textvariable=result_status,wraplength=650).pack(fill='x',padx=4,pady=4)
    table=ttk.Treeview(result_box,columns=('name','count','active','gift'),show='headings',height=11)
    for key,title in [('name','狗卡'),('count','持有数量'),('active','激活状态'),('gift','可赠送数量')]:
        table.heading(key,text=title);table.column(key,width=140,anchor='center')
    table.tag_configure('giftable',foreground='#14532d',background='#dcfce7')
    table.tag_configure('ready',foreground='#9a3412',background='#ffedd5')
    table.tag_configure('active',foreground='#1e40af',background='#eff6ff')
    table.tag_configure('empty',foreground='#6b7280')
    legend=ttk.Frame(result_box);legend.pack(fill='x',padx=4,pady=3)
    for text,color in [('绿色：可赠送余卡','#14532d'),('橙色：持卡待激活','#9a3412'),('蓝色：已激活无余卡','#1e40af'),('灰色：未激活且无卡','#6b7280')]:
        ttk.Label(legend,text=text,foreground=color).pack(side='left',padx=5)
    scroll=ttk.Scrollbar(result_box,orient='vertical',command=table.yview);table.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right',fill='y');table.pack(fill='both',expand=True)
    app.dog_card_table=table;app.dog_card_status=result_status
    def render(payload):
        if not w.winfo_exists():return
        current=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
        if str(payload.get('uid'))!=str(current['uid']) or payload.get('slot')!=int(app.cmb_slot.get()):
            result_status.set('账号或槽位已切换，忽略旧结果；请重新查询。');return
        state=payload['state'];table.delete(*table.get_children())
        for n,row in enumerate(state['cards'],1):
            tag='giftable' if row['giftable']>0 else ('ready' if not row['active'] and row['count']>0 else ('active' if row['active'] else 'empty'))
            active_text='已激活' if row['active'] else ('未激活 · 有卡' if row['count']>0 else '未激活')
            gift_text=str(row['giftable'])+'张 · 可赠送' if row['giftable']>0 else '0'
            table.insert('', 'end',iid=str(n),values=(row['name'],row['count'],active_text,gift_text),tags=(tag,))
        daily=state.get('daily') or {}
        result_status.set('槽%s｜%s｜今日已抽%s，额外次数%s'%(payload['slot'],payload.get('message',''),daily.get('double11LotteryCnt',0),daily.get('addDouble11LotteryCnt',0)))
    app.render_dog_cards=render
    def launch(action):
        if app.running or not app._save_selected_slot():return
        account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(app.cmb_slot.get())
        ids=[n for n,v in selected.items() if v.get()] if action=='activate' else [DOG_NAMES.index(gift.get())+1]
        if action=='activate' and not ids:messagebox.showinfo('未选择','请勾选狗卡',parent=w);return
        if action=='redeem' and not code.get().strip():messagebox.showinfo('未填写','请输入兑换码',parent=w);return
        if action!='query' and not messagebox.askyesno('确认狗卡操作','当前槽%s，%s；不购买、不自动继续其他操作。确认？'%(slot,{'activate':'激活：'+ '、'.join(DOG_NAMES[n-1] for n in ids),'redeem':'领取兑换码','gift_draw':'赠送'+gift.get()+'并在新增次数确认后额外抽一次'}[action]),parent=w):return
        args=[str(ROOT/'dog_card_tool.py'),'--action',action,'--account',str(account['uid']),'--slot',str(slot)]
        for n in ids:args+=['--id',str(n)]
        value=code.get().strip() if action=='redeem' else '';code.set('') if action=='redeem' else None
        result_status.set('正在处理，请等待结果；不要重复点击。')
        app._launch(args,extra_env={'ZM5_DOG_REDEEM_CODE':value})
    def view_code():
        account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(app.cmb_slot.get())
        for path in sorted((ROOT/'dog_card_reports').glob('*.private.json'),reverse=True):
            report=json.loads(path.read_text(encoding='utf8'))
            if str(report.get('uid'))==str(account['uid']) and report.get('slot')==slot and report.get('generated_code'):
                code.set(report['generated_code']);return
        messagebox.showinfo('赠送码','当前账号槽位没有已保存的赠送码',parent=w)
    ttk.Button(codes,text='查看上次生成码',command=view_code).pack(side='left',padx=4)
    buttons=ttk.Frame(w);buttons.pack(fill='x',padx=10,pady=10)
    for title,action in [('查询库存','query'),('激活所选','activate'),('赠送＋额外抽一次','gift_draw'),('领取兑换码','redeem')]:ttk.Button(buttons,text=title,command=lambda a=action:launch(a)).pack(side='left',padx=3)
    ttk.Label(w,text='赠送码仅在私有记录保存，可点击查看；异常后先核对记录。',wraplength=600).pack(anchor='w',padx=10)
