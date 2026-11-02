"""配置更新页：检查服务器本周配置并解包到新目录。"""
import os,threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from game_config_sync import ROOT,sync


def latest_local():
    dirs=[p for p in ROOT.glob('cg_config_out_cg1_*') if p.is_dir()]
    return max(dirs,key=lambda p:p.name) if dirs else None


class ConfigSyncPage:
    def __init__(self,app,notebook):
        self.app=app;self.running=False;self.lines=[];self.folder=''
        self.page=ttk.Frame(notebook,padding=12);notebook.add(self.page,text='配置更新')
        local=latest_local()
        self.status=tk.StringVar(value='本地最新：'+(local.name if local else '未找到已解包配置'))
        ttk.Label(self.page,textvariable=self.status,wraplength=900).pack(fill='x')
        ttk.Label(self.page,text='版本规则：以 2026-10-26 为基准每 7 天递增，周内热更时序号 1→2→3；来源 ftp22 的 AMF 配置包。更新只写入新目录，不改各模块的读取路径。',foreground='#a06000',wraplength=900).pack(fill='x',pady=4)
        row=ttk.Frame(self.page);row.pack(fill='x',pady=4)
        self.start_button=ttk.Button(row,text='检查并更新配置',command=self.start,width=20);self.start_button.pack(side='left')
        ttk.Button(row,text='打开输出目录',command=self.open_folder,width=16).pack(side='left',padx=6)
        self.text=tk.Text(self.page,height=14,wrap='none');self.text.pack(fill='both',expand=True,pady=6)

    def start(self):
        if self.running:return
        self.running=True;self.start_button.configure(state='disabled')
        self.text.delete('1.0','end');self.lines=[];self.status.set('正在检查最新配置…')
        threading.Thread(target=self.work,daemon=True).start()
        self.page.after(200,self.flush)

    def work(self):
        try:
            result=sync(log=lambda s:self.lines.append(s))
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
                continue
            self.text.insert('end',line+'\n');self.text.see('end')
        if self.running:self.page.after(200,self.flush)

    def refresh(self):
        local=latest_local()
        self.status.set('本地最新：'+(local.name if local else '未找到已解包配置'))

    def open_folder(self):
        target=self.folder or (str(latest_local() or ''))
        if target and Path(target).is_dir():os.startfile(target)
