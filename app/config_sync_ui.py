"""配置更新页：检查服务器本周配置并解包到新目录。"""
import os,threading,json
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from game_config_sync import ROOT,sync,import_config,paused_until
from game_version import latest_config_folder,xie_status_text,config_is_stale


def latest_local():
    return latest_config_folder(ROOT)


class ConfigSyncPage:
    def __init__(self,app,notebook):
        self.app=app;self.running=False;self.lines=[];self.folder='';self.notified=False
        self.auto_run=False;self.last_error='';self.installed=''
        self.page=ttk.Frame(notebook,padding=12);notebook.add(self.page,text='配置更新')
        local=latest_local();stale=config_is_stale(local) if local else False
        pause=paused_until() if local else None
        preflight=os.environ.pop('ZM5_CONFIG_PREFLIGHT','0') == '1'
        self.status=tk.StringVar(value='本地最新：'+(local.name if local else '未找到已解包配置'))
        ttk.Label(self.page,textvariable=self.status,wraplength=900).pack(fill='x')
        ttk.Label(self.page,text='检查本周 cg1 及热更序号，或选择本地 cg1 文件自动解包。本地配置超过 8 天（以配置日期当天中午 12 点起算）会在启动时自动更新；若服务器本周还没有新包，则暂停到下一个配置日中午再检查。限时活动按最新 Activity 表及关联配置的北京时间开放区间判断；更新完成后重启程序完全生效。过期或未开放入口隐藏，后台停止执行；轮回挑战与领奖分别判断。',foreground='#a06000',wraplength=900).pack(fill='x',pady=4)
        self.settings_path=ROOT/'config_sync_settings.json'
        try:settings=json.loads(self.settings_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):settings={}
        if not isinstance(settings,dict):settings={}
        saved_auto=settings.get('auto_check_on_start') is True
        self.auto=tk.BooleanVar(value=saved_auto or local is None or stale)
        if local is None:
            self.status.set('本地未找到配置表：启动后自动从官方资源服下载并解压')
        elif pause:
            self.status.set('本地最新：%s（本周服务器暂无新包，下次检查：%s）'
                            %(local.name,pause.strftime('%m-%d %H:%M')))
        elif stale:
            self.status.set('本地最新：%s（已超过 8 天，启动后自动更新）'%local.name)
        ttk.Checkbutton(self.page,text='启动时自动检查并解析本周 cg1',variable=self.auto,command=self.save_settings).pack(anchor='w')
        row=ttk.Frame(self.page);row.pack(fill='x',pady=4)
        self.start_button=ttk.Button(row,text='检查并更新配置',command=self.start,width=20);self.start_button.pack(side='left')
        self.import_button=ttk.Button(row,text='选择本地 cg1 文件',command=self.choose_file,width=20);self.import_button.pack(side='left',padx=6)
        ttk.Button(row,text='打开输出目录',command=self.open_folder,width=16).pack(side='left',padx=6)
        self.text=tk.Text(self.page,height=14,wrap='none');self.text.pack(fill='both',expand=True,pady=6)
        self.page.after(500,self.poll_activity)
        if self.auto.get() and pause is None and not preflight:
            self.page.after(1000,lambda:self.start(auto=True))
            if local is None:self.page.after(1200,self.notice_missing)
            elif stale and not saved_auto:self.page.after(1200,self.notice_stale)

    def notice_stale(self):
        """本地配置过期且未勾选自动检查时，提示本次启动会强制更新。"""
        if self.notified or not config_is_stale(latest_local()):return
        self.notified=True
        messagebox.showinfo('配置表更新','本地配置已超过 8 天，已开始后台自动下载更新。\n下载完成后请重启程序。',parent=self.page.winfo_toplevel())

    def notice_missing(self):
        """缺少配置表且自动下载已启动时，只提示一次，避免用户误以为程序卡住。"""
        if self.notified or latest_local() is not None:return
        self.notified=True
        messagebox.showinfo('配置表下载','本地未找到配置表，已开始后台自动下载。\n下载完成后请重启程序；期间抓宠范围、联盟仓库、玉珠商店等功能暂不可用。',parent=self.page.winfo_toplevel())

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

    def start(self,path=None,auto=False):
        if self.running:return
        self.running=True;self.auto_run=auto and path is None
        self.last_error='';self.installed=''
        self.start_button.configure(state='disabled')
        self.import_button.configure(state='disabled')
        self.text.delete('1.0','end');self.lines=[];self.status.set('正在检查最新配置…')
        threading.Thread(target=self.work,args=(path,),daemon=True).start()
        self.page.after(200,self.flush)

    def work(self,path=None):
        try:
            logger=lambda s:self.lines.append(s)
            result=import_config(path,log=logger) if path else sync(log=logger)
        except Exception as exc:
            self.last_error=str(exc)
            self.lines.append('失败：'+self.last_error)
        else:
            self.folder=result['folder']
            if result.get('up_to_date'):
                self.lines.append('服务器暂无新包，本周暂停检查；下次 %s'
                                  %datetime.fromisoformat(result['paused_until']).strftime('%m-%d %H:%M'))
            else:
                self.installed=result['name'].replace('.swf','')
                self.lines.append('完成：%s，共 %d 张表'%(result['name'],result['tables']))
        self.lines.append(None)

    def flush(self):
        while self.lines:
            line=self.lines.pop(0)
            if line is None:
                self.running=False;self.start_button.configure(state='normal');self.refresh()
                self.import_button.configure(state='normal')
                if self.auto_run:self.notify_result()
                self.auto_run=False
                continue
            self.text.insert('end',line+'\n');self.text.see('end')
        if self.running:self.page.after(200,self.flush)

    def notify_result(self):
        """自动更新结束提示一次；手动更新只写日志，不弹窗打断。"""
        if self.last_error:
            messagebox.showwarning('配置表更新','自动更新失败，继续使用本地配置。\n%s'
                                    %self.last_error[:200],parent=self.page.winfo_toplevel())
        elif self.installed:
            messagebox.showinfo('配置表更新','配置表已更新到 %s，重启后完全生效。'
                                %self.installed,parent=self.page.winfo_toplevel())

    def refresh(self):
        local=latest_local();pause=paused_until() if local else None
        if pause:
            self.status.set('本地最新：%s（本周服务器暂无新包，下次检查：%s）'
                            %(local.name,pause.strftime('%m-%d %H:%M')))
        else:
            self.status.set(xie_status_text())
        callback=getattr(self.app,'refresh_xie_activity',None)
        if callback:callback()

    def open_folder(self):
        target=self.folder or (str(latest_local() or ''))
        if target and Path(target).is_dir():os.startfile(target)
