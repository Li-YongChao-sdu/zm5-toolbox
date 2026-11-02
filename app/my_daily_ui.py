"""我的日常独立窗口：收藏、单项执行、批量执行，复用主GUI。"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent

WEEKLY_PAGES=frozenset(('周常副本／领奖','通天河','BOSS挑战'))
TOP_TASKS=('RUN_FLUSHOU',)
SECOND_TASKS=('RUN_GROWTH_BUFF','RUN_WEEKEND_BUFF')   # 固定第2、3位：成长buff、周末在线第1档buff
BOTTOM_TASKS=('RUN_LIVENESS','RUN_CELEBRATION','RUN_CELEBRATION_ONLINE','RUN_WEEKEND_ONLINE',
              'RUN_PERMANENT_FASHION','RUN_WHITE_DRAGON')  # 每日活跃之后：庆典/庆典15分钟/周末后几档/永久时装/八部天龙
PINNED_TASKS=frozenset(TOP_TASKS+BOTTOM_TASKS+SECOND_TASKS)
# 新手任务分组只保留这三项，其余细分开关不在“管理我的日常”里展示
NEWBIE_KEEP=frozenset(('RUN_PERMANENT_FASHION','RUN_WHITE_DRAGON','RUN_GROWTH_BUFF'))
NEWBIE_TIP='强烈建议新手用户选择该项内容！！'

def ordered_favorites(keys):
    keys=list(dict.fromkeys(keys))
    return ([key for key in TOP_TASKS if key in keys]
            +[key for key in SECOND_TASKS if key in keys]
            +[key for key in keys if key not in PINNED_TASKS]
            +[key for key in BOTTOM_TASKS if key in keys])

def load_favorites(path,allowed):
    try:data=json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return []
    keys=data.get('favorites',[]) if isinstance(data,dict) else []
    if not isinstance(keys,list):return []
    return ordered_favorites(k for k in keys if isinstance(k,str) and k in allowed)

def save_favorites(path,keys):
    p=Path(path);temp=p.with_suffix('.tmp');temp.write_text(json.dumps({'favorites':ordered_favorites(keys)},ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(p)

class MyDailyWindow:
    TITLE='我的日常'
    def __init__(self,app,catalog,pages,path=None):
        from my_daily_catalog import catalog as all_catalog,pages as all_pages,DEFINITIONS
        self.app=app;self.catalog={r[1]:r for r in all_catalog(catalog) if not r[3] and r[1].startswith('RUN_')};self.pages=all_pages(pages)
        for key,label,kind,page,note in DEFINITIONS:
            if key not in app.var_checks:app.var_checks[key]=tk.BooleanVar(master=app.root,value=False)
        from my_daily_modules import discover
        self.modules,module_pages=discover(app)
        for key,row in self.modules.items():
            self.catalog[key]=(row['label'],key,False,False,'沿用'+row['page']+'设置；仅非点券操作，保留原查询及确认要求')
            app.var_checks[key]=tk.BooleanVar(master=app.root,value=False)
        for title,keys in module_pages.items():self.pages[title]=tuple(self.pages.get(title,()))+tuple(keys)
        self.full_catalog=dict(self.catalog);self.full_pages=dict(self.pages);self.full_modules=dict(self.modules)
        weekly_keys={key for title,keys in self.pages.items() if title in WEEKLY_PAGES for key in keys}
        weekly_keys.update(self.pages.get('斗神/乱斗',()))
        self.pages={title:keys for title,keys in self.pages.items() if title not in WEEKLY_PAGES and title!='斗神/乱斗'}
        self.catalog={key:row for key,row in self.catalog.items() if key not in weekly_keys}
        self.modules={key:row for key,row in self.modules.items() if key not in weekly_keys}
        # 新手任务分组只保留 永久时装/八部天龙/成长双倍buff，其余细分开关不在此窗口展示
        if '新手任务' in self.pages:self.pages['新手任务']=tuple(k for k in self.pages['新手任务'] if k in NEWBIE_KEEP)
        keep={k for keys in self.pages.values() for k in keys}
        self.catalog={key:row for key,row in self.catalog.items() if key in keep}
        from my_daily_queue import ModuleQueue
        self.module_queue=ModuleQueue(self)
        self.path=Path(path) if path else ROOT/'my_daily_favorites.json';self.favorites=load_favorites(self.path,self.catalog)
        self.window=None;self.buttons=[];self.rows={}
    def entry_visible(self,key):
        from activity_availability import hidden_activity
        if hidden_activity(key):return False
        predicate=self.modules.get(key,{}).get('visible')
        return predicate is None or bool(predicate())
    def visible_favorites(self):
        from activity_availability import disabled_reason
        from activity_availability import hidden_activity
        keys=[k for k in self.favorites if k in self.catalog and not hidden_activity(k) and self.entry_visible(k)]
        return ordered_favorites(keys)
    def open(self):
        if self.window is not None and self.window.winfo_exists():self.window.deiconify();self.window.lift();return
        w=tk.Toplevel(self.app.root);self.window=w;w.title(self.TITLE+' · 造梦西游5 工具箱');w.geometry('900x620');w.minsize(680,420)
        self.status=tk.StringVar();ttk.Label(w,textvariable=self.status,wraplength=850).pack(anchor='w',padx=12,pady=8)
        bar=ttk.Frame(w);bar.pack(fill='x',padx=10)
        ttk.Button(bar,text='管理收藏任务',command=self.manage).pack(side='left',padx=4)
        b=ttk.Button(bar,text='执行本窗口所选',command=self.start_selected);b.pack(side='left',padx=4);self.buttons=[b]
        ttk.Button(bar,text='停止当前任务',command=self.app._stop).pack(side='left',padx=4)
        ttk.Button(bar,text='全部展开',command=lambda:self.set_details(False)).pack(side='left',padx=4)
        ttk.Button(bar,text='全部收起',command=lambda:self.set_details(True)).pack(side='left',padx=4)
        ttk.Label(w,text='仅执行收藏且勾选的非点券项目；点击标题查看策略，设置沿用原页面。',wraplength=850).pack(anchor='w',padx=12,pady=8)
        area=ttk.Frame(w);area.pack(fill='both',expand=True,padx=10,pady=6);canvas=tk.Canvas(area,highlightthickness=0);scroll=ttk.Scrollbar(area,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        self.body=ttk.Frame(canvas);item=canvas.create_window(0,0,window=self.body,anchor='nw');self.body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        self.render();self.tick()
    def render(self):
        if self.window is None or not self.window.winfo_exists():return
        for child in self.body.winfo_children():child.destroy()
        self.buttons=self.buttons[:1];self.rows={};self._detail_controls={}
        if not hasattr(self,'_detail_collapsed'):self._detail_collapsed={}
        visible=self.visible_favorites();self._visible_keys=tuple(visible)
        if not visible:ttk.Label(self.body,text='还没有收藏任务，点击“管理收藏任务”选择平时常做的项目。').pack(anchor='w',padx=8,pady=18)
        from activity_availability import disabled_reason
        for index,key in enumerate(visible):
            title,_,_,_,note=self.catalog[key]
            if key=='RUN_LIVENESS':note='在庆典/永久时装/八部天龙之前领取活跃积分和里程碑奖励。'
            row=ttk.Frame(self.body,padding=5,relief='groove');row.pack(fill='x',padx=4,pady=3)
            header=ttk.Frame(row);header.pack(fill='x')
            for label,direction in [('↑',-1),('↓',1)]:
                move=ttk.Button(header,text=label,width=3,command=lambda k=key,d=direction:self.move(k,d))
                move.pack(side='left',padx=1)
                if key in PINNED_TASKS or not 0<=index+direction<len(visible) or visible[index+direction] in PINNED_TASKS:move.configure(state='disabled')
            ttk.Checkbutton(header,text='执行',variable=self.app.var_checks[key]).pack(side='left',padx=4)
            collapsed=self._detail_collapsed.get(key,True)
            title_button=ttk.Button(header,text=('▸ ' if collapsed else '▾ ')+title,command=lambda k=key:self.toggle_detail(k))
            title_button.pack(side='left',padx=4)
            ttk.Button(header,text='打开设置',command=lambda k=key:self.open_settings(k)).pack(side='right',padx=3)
            b=ttk.Button(header,text='单独执行',command=lambda k=key:self.start([k]));b.pack(side='right',padx=3)
            if disabled_reason(key):b.configure(state='disabled')
            b._task_key=key;self.buttons.append(b)
            content=ttk.Frame(row,padding=(12,6))
            detail=tk.StringVar(value=note);ttk.Label(content,textvariable=detail,wraplength=760,justify='left').pack(anchor='w',fill='x');self.rows[key]=detail
            if not collapsed:content.pack(fill='x')
            self._detail_controls[key]=(title_button,content,title)
    def toggle_detail(self,key):
        collapsed=not self._detail_collapsed.get(key,True)
        self._detail_collapsed[key]=collapsed
        button,content,title=self._detail_controls[key]
        if collapsed:content.pack_forget()
        else:content.pack(fill='x')
        button.configure(text=('▸ ' if collapsed else '▾ ')+title)
    def set_details(self,collapsed):
        for key in self._detail_controls:
            if self._detail_collapsed.get(key,True)!=collapsed:self.toggle_detail(key)
    def move(self,key,direction):
        if getattr(getattr(self.app,'_personal_queue',None),'active',False) or self.app.running or getattr(self.app,'execution_gate',None) and self.app.execution_gate.busy:return
        visible=self.visible_favorites()
        if key not in visible or key in PINNED_TASKS:return
        index=visible.index(key);destination=index+direction
        if not 0<=destination<len(visible) or visible[destination] in PINNED_TASKS:return
        reordered=list(self.favorites);left=reordered.index(key);right=reordered.index(visible[destination]);reordered[left],reordered[right]=reordered[right],reordered[left]
        try:save_favorites(self.path,reordered)
        except OSError as exc:messagebox.showerror('排序保存失败',str(exc),parent=self.window);return
        self.favorites=ordered_favorites(reordered);self.render()
    def selected(self):return [k for k in self.visible_favorites() if self.app.var_checks[k].get()]
    def start_selected(self):self.start(self.selected())
    def start(self,keys):
        if getattr(getattr(self.app,'_personal_queue',None),'active',False) or self.app.running or getattr(self.app,'execution_gate',None) and self.app.execution_gate.busy:return
        if any(not self.entry_visible(key) for key in keys):return
        if not keys:messagebox.showinfo(self.TITLE,'请先勾选要执行的收藏任务。',parent=self.window);return
        if any(k in self.modules for k in keys):
            try:self.module_queue.start(keys)
            except (OSError,ValueError) as exc:messagebox.showerror('未执行',str(exc),parent=self.window)
        else:self.app._start(task_keys=set(keys),free_only=True)
    def open_settings(self,key):
        title=next((title for title,keys in self.pages.items() if key in keys),None)
        preferred={'RUN_ARENA':'关卡设置','RUN_PET_ARENA':'关卡设置','RUN_FOREST':'关卡设置','RUN_ELITE_STONE':'日常副本','RUN_FAIRY_REWARD':'幻兽派遣'}
        from my_daily_catalog import BY_KEY
        if key in BY_KEY:preferred[key]=BY_KEY[key][3]
        if key in self.modules:preferred[key]=self.modules[key]['page']
        if preferred.get(key)=='背包/仓库':self.app.bag_warehouse_page.open();return
        choices=[preferred.get(key),title]
        for wanted in choices:
            if not wanted:continue
            from my_daily_navigation import select_page
            if select_page(self.app,wanted):self.app.root.deiconify();self.app.root.lift();return
            for tab in self.app.main_notebook.tabs():
                if self.app.main_notebook.tab(tab,'text')==wanted:self.app.main_notebook.select(tab);self.app.root.deiconify();self.app.root.lift();return
            for name,outer in [('fun_activity_notebook','fun_activity_page'),('backup_function_notebook','backup_function_page')]:
                nested=getattr(self.app,name,None)
                if nested is not None:
                    for child in nested.tabs():
                        if nested.tab(child,'text')==wanted:
                            self.app.main_notebook.select(getattr(self.app,outer));nested.select(child);self.app.root.deiconify();self.app.root.lift();return
    def manage(self):
        d=tk.Toplevel(self.window);d.title('管理'+self.TITLE);d.geometry('760x560');vars={}
        area=ttk.Frame(d);area.pack(fill='both',expand=True);c=tk.Canvas(area,highlightthickness=0);s=ttk.Scrollbar(area,orient='vertical',command=c.yview);c.configure(yscrollcommand=s.set);s.pack(side='right',fill='y');c.pack(side='left',fill='both',expand=True);body=ttk.Frame(c);c.create_window(0,0,window=body,anchor='nw');body.bind('<Configure>',lambda e:c.configure(scrollregion=c.bbox('all')))
        from activity_availability import disabled_reason
        from collapsible_panels import CollapsiblePanel
        states=getattr(self,'_manage_collapse',{});self._manage_collapse=states
        panels=[];self._manage_panels=panels
        gated=[]
        toolbar=ttk.Frame(d);toolbar.pack(fill='x',before=area,padx=8,pady=5)
        def set_all(collapsed):
            for title,panel in panels:panel.set_collapsed(collapsed);states[title]=collapsed
        ttk.Button(toolbar,text='全部展开',command=lambda:set_all(False)).pack(side='left',padx=3)
        ttk.Button(toolbar,text='全部折叠',command=lambda:set_all(True)).pack(side='left',padx=3)
        for title,keys in self.pages.items():
            from activity_availability import hidden_activity
            keys=[k for k in keys if k in self.catalog and not hidden_activity(k)]
            if not keys:continue
            frame=ttk.LabelFrame(body,text=title,padding=6);frame.pack(fill='x',padx=8,pady=5)
            if title=='新手任务':tk.Label(frame,text=NEWBIE_TIP,fg='#c62828',font=('Microsoft YaHei',9,'bold')).pack(anchor='w',pady=(0,6))
            for key in keys:
                if key not in self.catalog:continue
                v=tk.BooleanVar(value=key in self.favorites);vars[key]=v
                target=frame
                if self.modules.get(key,{}).get('visible') is not None:
                    target=ttk.Frame(frame);target.pack(fill='x')
                check=ttk.Checkbutton(target,text=self.catalog[key][0]+('（'+disabled_reason(key)+'）' if disabled_reason(key) else ''),variable=v);check.pack(anchor='w')
                if self.modules.get(key,{}).get('visible') is not None:gated.append((key,check))
            panel=CollapsiblePanel(frame,collapsed=states.get(title,True));panels.append((title,panel))
            def toggle(title=title,panel=panel):
                panel.toggle();states[title]=panel.collapsed
            panel.button.configure(command=toggle)
        def save():
            chosen={k for k,v in vars.items() if v.get()}
            added=chosen-set(self.favorites)
            favorites=[k for k in self.favorites if k not in vars or k in chosen]+[k for k in self.catalog if k in chosen and k not in self.favorites]
            try:save_favorites(self.path,favorites)
            except OSError as e:messagebox.showerror('保存失败',str(e),parent=d);return
            self.favorites=favorites
            for key in added:self.app.var_checks[key].set(True)
            self.render();d.destroy()
        ttk.Button(d,text='保存收藏',command=save).pack(pady=8)
        def refresh_gated():
            if not d.winfo_exists():return
            for key,check in gated:
                if self.entry_visible(key):
                    if not check.winfo_manager():check.pack(anchor='w')
                else:check.pack_forget()
            d.after(250,refresh_gated)
        refresh_gated()
    def tick(self):
        if self.window is None or not self.window.winfo_exists():return
        busy=getattr(getattr(self.app,'_personal_queue',None),'active',False) or self.app.running or getattr(self.app,'execution_gate',None) and self.app.execution_gate.busy
        account=self.app.lbl_account.cget('text');self.status.set('%s｜当前槽%s｜%s'%(account,self.app.cmb_slot.get(),'任务运行中：与主界面共用执行锁' if busy else '空闲'))
        if getattr(self,'_visible_keys',())!=tuple(self.visible_favorites()):self.render()
        from activity_availability import disabled_reason
        for i,b in enumerate(self.buttons):
            if b.winfo_exists():b.configure(state='disabled' if busy or disabled_reason(getattr(b,'_task_key','')) else 'normal')
        for key,var in self.rows.items():
            note=disabled_reason(key) or self.catalog[key][4]
            if key=='RUN_LIVENESS':note='在庆典/永久时装/八部天龙之前领取活跃积分和里程碑奖励。'
            from my_daily_strategy import summary
            strategy=summary(self.app,key,self.modules)
            if strategy and not disabled_reason(key):note='策略：'+strategy
            var.set(note)
        self.window.after(250,self.tick)
