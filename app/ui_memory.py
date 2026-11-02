"""可选界面配置记忆。只保存已登记设置，不保存登录信息、确认框或任务状态。"""
import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox,filedialog

VERSION=1
EXCLUDED={'var_login_user','var_login_pwd','var_login_cookie','var_remember','var_paid_confirm',
          'var_daily_task_quota','var_daily_task_selection','var_wish_day','var_elite_sell_password'}

def read_settings(path):
    path=Path(path)
    if not path.exists():return {'version':VERSION,'enabled':False}
    if path.stat().st_size>512*1024:raise ValueError('配置文件过大')
    obj=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(obj,dict) or obj.get('version')!=VERSION or type(obj.get('enabled')) is not bool:
        raise ValueError('配置格式或版本不受支持')
    if obj.get('enabled') and not isinstance(obj.get('values'),dict):raise ValueError('缺少设置值')
    return obj

def write_settings(path,obj):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)

def valid_value(value,default,choices=None):
    if isinstance(default,bool):ok=type(value) is bool
    elif isinstance(default,int):ok=type(value) is int
    elif isinstance(default,float):ok=type(value) in (int,float) and math.isfinite(value)
    else:ok=isinstance(value,str) and len(value)<=4096
    return ok and (not choices or value in choices or value=='')

class SettingsMemory:
    def __init__(self,app,notebook,parent,path):
        self.app=app;self.root=app.root;self.notebook=notebook;self.path=Path(path)
        self.variables={};self.defaults={};self.choices={};self.pending=None;self.loading=True
        def add(key,var,choices=None):
            if not isinstance(var,tk.Variable) or str(var) in seen:return
            try:value=var.get()
            except tk.TclError:return
            seen.add(str(var));self.variables[key]=var;self.defaults[key]=value
            if choices:self.choices[key]=list(choices)
        seen=set()
        # 日常任务先恢复，其联动之后再恢复其它显式选项。
        for key,var in app.daily_task_vars.items():add('daily_task_vars/'+str(key),var)
        for name,value in vars(app).items():
            if name.startswith('var_') and name not in EXCLUDED:
                if isinstance(value,dict):
                    for key,var in value.items():add(name+'/'+str(key),var)
                elif isinstance(value,tk.Variable):add(name,value)
        for key,var in app.elite_vars.items():add('elite_vars/'+str(key),var)
        for title,(var,_) in app.single_task_choices.items():add('single_task/'+title,var)
        for key,(var,choices) in getattr(app,'ui_settings_fields',{}).items():add('feature/'+key,var,choices)
        capture=getattr(app,'pet_capture_settings',{})
        for key,pair in capture.get('ranges',{}).items():
            for side,var in zip(('min','max'),pair):add('capture/'+key+'/'+side,var)
        cup=getattr(app,'worldcup_page',None)
        for name in ('stage','area','count'):
            if cup:add('worldcup/'+name,getattr(cup,name))
        # 只读下拉选项必须仍存在，避免更新后恢复失效的关卡名称。
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child,ttk.Combobox):
                    binding=str(child.cget('textvariable'))
                    for key,var in self.variables.items():
                        if str(var)==binding:self.choices[key]=list(child.cget('values'))
                walk(child)
        walk(self.root)
        self.default_tab=notebook.tab(notebook.select(),'text')
        self.enabled=tk.BooleanVar(value=False)
        ttk.Checkbutton(parent,text='记住配置',variable=self.enabled,command=self.toggle).pack(side='left',padx=(16,4))
        self.reset_button=ttk.Button(parent,text='恢复默认',command=self.reset)
        self.reset_button.pack(side='left',padx=4)
        ttk.Button(parent,text='导入配置',command=self.import_config).pack(side='left',padx=4)
        ttk.Button(parent,text='导出配置',command=self.export_config).pack(side='left',padx=4)
        try:
            data=read_settings(self.path)
            if data['enabled']:
                self.enabled.set(True);self.restore(data.get('values',{}));self.select_tab(data.get('tab'))
        except (OSError,ValueError,TypeError) as exc:
            app._append_log('[配置记忆] 未恢复配置：'+str(exc))
        self.loading=False
        for var in self.variables.values():var.trace_add('write',lambda *_:self.schedule())
        notebook.bind('<<NotebookTabChanged>>',lambda e:self.schedule(),add='+')
        self.root.protocol('WM_DELETE_WINDOW',self.close)

    def select_tab(self,title):
        if title == '幻兽':title = '幻兽派遣'
        if title == '采集/妖王帖/藏宝':title = '宠物采集'
        backup_titles = ('灵宠试炼', '材料置换', '背包/仓库', '刷去益灵花', '抓宠', '宠物上推荐', '炼丹炉', '联盟仓库')
        nested_title = title if title in ('抓宠', '宠物采集', '妖王帖', '藏宝仙魄商店', '宠物上推荐', '藏宝洞', '炼丹炉', '黑市', '幻兽喂养', '幻兽派遣') + backup_titles else None
        nested_attribute = 'backup_function_notebook' if title in backup_titles else 'fun_activity_notebook'
        title={"日常任务":"日常任务1","周常副本":"周常副本／领奖","宠物采集":"趣味活动","妖王帖":"趣味活动","藏宝仙魄商店":"趣味活动","抓宠":"备用功能","宠物上推荐":"备用功能","藏宝洞":"趣味活动","炼丹炉":"备用功能","联盟仓库":"备用功能","黑市":"趣味活动","幻兽喂养":"趣味活动","幻兽派遣":"趣味活动","万能强化石":"日常副本","灵宠试炼":"备用功能","材料置换":"备用功能","背包/仓库":"备用功能","刷去益灵花":"备用功能"}.get(title,title)
        for tab in self.notebook.tabs():
            if self.notebook.tab(tab,'text')==title:
                self.notebook.select(tab)
                nested = getattr(self.app, nested_attribute, None)
                if nested_title and nested is not None:
                    for child in nested.tabs():
                        if nested.tab(child, 'text') == nested_title:nested.select(child);break
                return

    def restore(self,values):
        for key,var in self.variables.items():
            if key in values and valid_value(values[key],self.defaults[key],self.choices.get(key)):
                try:var.set(values[key])
                except tk.TclError:pass

    def schedule(self):
        if self.loading or not self.enabled.get():return
        if self.pending:self.root.after_cancel(self.pending)
        self.pending=self.root.after(500,self.save)

    def save(self):
        self.pending=None
        try:
            data={'version':VERSION,'enabled':bool(self.enabled.get())}
            if data['enabled']:
                values={}
                for key,var in self.variables.items():
                    try:value=var.get()
                    except tk.TclError:continue
                    if valid_value(value,self.defaults[key],self.choices.get(key)):values[key]=value
                data.update(values=values,tab=self.notebook.tab(self.notebook.select(),'text'))
            write_settings(self.path,data)
        except (OSError,ValueError,tk.TclError) as exc:
            self.app._append_log('[配置记忆] 保存失败：'+str(exc))

    def snapshot(self):
        values={}
        for key,var in self.variables.items():
            try:value=var.get()
            except tk.TclError:continue
            if valid_value(value,self.defaults[key],self.choices.get(key)):values[key]=value
        return {'version':VERSION,'enabled':True,'values':values,
                'tab':self.notebook.tab(self.notebook.select(),'text')}

    def export_config(self):
        path=filedialog.asksaveasfilename(parent=self.root,title='导出当前配置',defaultextension='.json',
                initialfile='工具箱配置.json',filetypes=[('配置文件','*.json')])
        if not path:return
        try:
            write_settings(path,self.snapshot())
            self.app._append_log('[配置导出] 已保存：'+path)
        except (OSError,ValueError,tk.TclError) as exc:
            messagebox.showerror('导出配置失败',str(exc),parent=self.root)

    def import_config(self):
        if self.app.running:
            messagebox.showinfo('导入配置','请先等待当前任务结束，再导入配置。',parent=self.root);return
        path=filedialog.askopenfilename(parent=self.root,title='导入配置',filetypes=[('配置文件','*.json')])
        if not path:return
        try:
            data=read_settings(path)
            if not isinstance(data.get('values'),dict):raise ValueError('该文件没有可导入的设置')
            invalid=[key for key,value in data['values'].items() if key in self.variables and not valid_value(value,self.defaults[key],self.choices.get(key))]
            if invalid:raise ValueError('配置包含无效参数：'+', '.join(invalid[:5]))
            if not messagebox.askyesno('导入配置','将使用文件中的设置覆盖当前配置。账号和存档保持当前选择，付费确认框将清空，不会自动执行任务。是否继续？',parent=self.root):return
            self.loading=True
            try:
                # Reset absent fields to defaults so separate profiles do not leak settings.
                self.restore(self.defaults);self.restore(data['values']);self.select_tab(data.get('tab'))
                guards=list(getattr(self.app,'var_paid_confirm',[]))
                guards.extend(getattr(self.app,'ui_confirmation_vars',[]))
                for obj,name in [(getattr(self.app,'worldcup_page',None),'visibility_flags'),(getattr(self.app,'old_activity_page',None),'flags')]:
                    if obj:guards.extend(getattr(obj,name,[]))
                for var in guards:var.set(False)
                if hasattr(self.app,'old_activity_page'):self.app.old_activity_page.update_visibility()
            finally:self.loading=False
            self.schedule()
            count=sum(key in self.variables for key in data['values'])
            self.app._append_log('[配置导入] 已恢复%d项设置：%s；未执行任务'%(count,path))
        except (OSError,ValueError,TypeError,tk.TclError) as exc:
            messagebox.showerror('导入配置失败',str(exc),parent=self.root)

    def toggle(self):
        self.save()
        self.app._append_log('[配置记忆] '+('已开启，设置变更及关闭窗口时自动保存' if self.enabled.get() else '已关闭并清除已保存的设置'))

    def reset(self):
        if self.app.running:
            messagebox.showinfo('恢复默认','请先停止正在执行的任务');return
        if not messagebox.askyesno('恢复默认','将恢复各页面的默认设置，清除解锁/付费确认勾选。是否继续？'):return
        self.loading=True
        try:
            self.restore(self.defaults);self.select_tab(self.default_tab)
            guards=list(getattr(self.app,'var_paid_confirm',[]))
            guards.extend(getattr(self.app,'ui_confirmation_vars',[]))
            for obj,name in [(getattr(self.app,'worldcup_page',None),'visibility_flags'),(getattr(self.app,'old_activity_page',None),'flags')]:
                if obj:guards.extend(getattr(obj,name,[]))
            for var in guards:var.set(False)
            if hasattr(self.app,'old_activity_page'):self.app.old_activity_page.update_visibility()
        finally:self.loading=False
        self.save();self.app._append_log('[配置记忆] 已恢复默认')

    def close(self):
        if self.pending:self.root.after_cancel(self.pending)
        # 未启用且没有配置文件时，不创建多余文件。
        if self.enabled.get() or self.path.exists():self.save()
        self.root.destroy()
