"""配置更新页：检查服务器本周配置并解包到新目录。"""
import os,threading,json
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog
from game_config_sync import ROOT,sync,import_config
from game_version import latest_config_folder,xie_status_text


def latest_local():
    return latest_config_folder(ROOT)


class ConfigSyncPage:
    def __init__(self,app,notebook):
        self.app=app;self.running=False;self.lines=[];self.folder=''
        self.page=ttk.Frame(notebook,padding=12);notebook.add(self.page,text='配置更新')
        local=latest_local()
        self.status=tk.StringVar(value='本地最新：'+(local.name if local else '未找到已解包配置'))
        ttk.Label(self.page,textvariable=self.status,wraplength=900).pack(fill='x')
        ttk.Label(self.page,text='检查本周 cg1 及热更序号，或选择本地 cg1 文件自动解包。限时活动按最新 Activity 表及关联配置的北京时间开放区间判断；更新后原页面和“我的日常”立即生效。过期或未开放入口隐藏，后台停止执行；轮回挑战与领奖分别判断。',foreground='#a06000',wraplength=900).pack(fill='x',pady=4)
        self.settings_path=ROOT/'config_sync_settings.json'
        try:settings=json.loads(self.settings_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):settings={}
        if not isinstance(settings,dict):settings={}
        self.auto=tk.BooleanVar(value=settings.get('auto_check_on_start') is True)
        ttk.Checkbutton(self.page,text='启动时自动检查并解析本周 cg1',variable=self.auto,command=self.save_settings).pack(anchor='w')
        row=ttk.Frame(self.page);row.pack(fill='x',pady=4)
        self.start_button=ttk.Button(row,text='检查并更新配置',command=self.start,width=20);self.start_button.pack(side='left')
        self.import_button=ttk.Button(row,text='选择本地 cg1 文件',command=self.choose_file,width=20);self.import_button.pack(side='left',padx=6)
        ttk.Button(row,text='打开输出目录',command=self.open_folder,width=16).pack(side='left',padx=6)
        self.text=tk.Text(self.page,height=14,wrap='none');self.text.pack(fill='both',expand=True,pady=6)
        self.page.after(500,self.poll_activity)
        if self.auto.get():self.page.after(1000,self.start)

    def save_settings(self):
        self.settings_path.write_text(json.dumps({'auto_check_on_start':self.auto.get()}),encoding='utf-8')

    def poll_activity(self):
        callback=getattr(self.app,'refresh_xie_activity',None)
        if callback:callback()
        self.page.after(60000,self.poll_activity)

    def choose_file(self):
        if self.running:return
        path=filedialog.askopenfilename(parent=self.page,title='选择 cg1 配置包',filetypes=[('cg1 配置包','cg1_*.swf')])
        if path:self.start(path)

    def start(self,path=None):
        if self.running:return
        self.running=True;self.start_button.configure(state='disabled')
        self.import_button.configure(state='disabled')
        self.text.delete('1.0','end');self.lines=[];self.status.set('正在检查最新配置…')
        threading.Thread(target=self.work,args=(path,),daemon=True).start()
        self.page.after(200,self.flush)

    def work(self,path=None):
        try:
            logger=lambda s:self.lines.append(s)
            result=import_config(path,log=logger) if path else sync(log=logger)
        except Exception as exc:
            self.lines.append('失败：'+str(exc))
        else:
            self.folder=result['folder'];self.lines.append('完成：%s，共 %d 张表'%(result['name'],result['tables']))
        self.lines.append(None)

    def flush(self):
        while self.lines:
            line=self.lines.pop(0)
            if line is None:
                self.running=False;self.start_button.configure(state='normal');self.refresh()
                self.import_button.configure(state='normal')
                continue
            self.text.insert('end',line+'\n');self.text.see('end')
        if self.running:self.page.after(200,self.flush)

    def refresh(self):
        self.status.set(xie_status_text())
        callback=getattr(self.app,'refresh_xie_activity',None)
        if callback:callback()

    def open_folder(self):
        target=self.folder or (str(latest_local() or ''))
        if target and Path(target).is_dir():os.startfile(target)
