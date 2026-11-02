"""世界boss包房界面：用户自行选择账号，账号文件不写入发布默认值。"""
import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk,messagebox,filedialog
from world_boss_room import MODES,ROLES,validate
ROOT=Path(__file__).resolve().parent

class WorldBossRoomPage:
    def __init__(self,app,parent):
        self.app=app;self.window=None;self.members=[];self.job_path=None;self.queried_job=None
        self.button=ttk.Button(parent,text='世界boss包房界面',command=self.open)
        self.access_vars=app.spend_permissions.variables['dungeons']
        for var in self.access_vars:var.trace_add('write',lambda *_:self.refresh_access())
        self.refresh_access()
    def unlocked(self):
        return ''.join('1' if var.get() else '0' for var in self.access_vars)=='001'
    def refresh_access(self):
        if self.unlocked():
            if not self.button.winfo_manager():self.button.pack(anchor='w',padx=8,pady=(0,10))
        else:
            self.button.pack_forget()
            if self.window is not None and self.window.winfo_exists():self.window.withdraw()
    def open(self):
        if not self.unlocked():return
        if self.window is not None and self.window.winfo_exists():self.window.deiconify();self.window.lift();return
        self.window=tk.Toplevel(self.app.root);self.window.title('世界boss包房界面');self.window.geometry('1120x650');self.window.protocol('WM_DELETE_WINDOW',self.window.withdraw)
        body=ttk.Frame(self.window,padding=10);body.pack(fill='both',expand=True)
        top=ttk.Frame(body);top.pack(fill='x')
        ttk.Label(top,text='世界BOSS：').pack(side='left')
        choices=[str(x['id'])+' '+x['name'] for x in json.loads((ROOT/'world_boss_stages.json').read_text(encoding='utf-8-sig'))]
        self.boss=tk.StringVar(value=self.app.var_world_boss.get())
        ttk.Combobox(top,textvariable=self.boss,values=choices,state='readonly',width=26).pack(side='left')
        ttk.Label(top,text='房间ID（留空自动选足够空位的房间）：').pack(side='left',padx=8)
        self.room=tk.StringVar();ttk.Entry(top,textvariable=self.room,width=20).pack(side='left')
        counts=ttk.Frame(body);counts.pack(fill='x',pady=8)
        self.n=tk.StringVar(value='1');self.m=tk.StringVar(value='7')
        for title,var in (('拿阵法号',self.n),('挂机号',self.m)):
            ttk.Label(counts,text=title+'：').pack(side='left');ttk.Spinbox(counts,from_=0,to=10,textvariable=var,width=4).pack(side='left',padx=5)
        ttk.Button(counts,text='生成／重建账号行',command=self.build_rows).pack(side='left',padx=8)
        ttk.Label(counts,text='合计8～10个不同账号，每号一个槽位').pack(side='left')
        self.table=ttk.Frame(body);self.table.pack(fill='both',expand=True)
        footer=ttk.Frame(body);footer.pack(fill='x',pady=8)
        ttk.Button(footer,text='查询账号次数及房间',command=lambda:self.launch('query')).pack(side='left',padx=5)
        ttk.Button(footer,text='确认开始包房',command=lambda:self.launch('run')).pack(side='left',padx=5)
        ttk.Button(footer,text='停止包房并退出',command=self.stop).pack(side='left',padx=5)
        ttk.Label(body,text='建议达到对应世界BOSS要求的等级后再挑战，不建议使用低级号直接挑战。',wraplength=1060).pack(anchor='w',pady=(0,5))
        ttk.Label(body,text='拿阵法号默认达到目标占比后零伤害挂机；挂机号默认不提交伤害。伤害采用原世界BOSS的随机采样。仅使用免费次数，不自动购买。断线即停止；进房后退出再重进可能重置计伤。',wraplength=1060).pack(anchor='w')
        self.summary=tk.StringVar(value='先选择每个账号与槽位，再查询、确认开始。运行记录显示在主窗口日志。')
        ttk.Label(body,textvariable=self.summary,wraplength=1060).pack(anchor='w',pady=5)
        self.build_rows()
    def account_options(self):
        directory=Path(self.app.accounts_dir)
        return {p.stem:str(p.resolve()) for p in sorted(directory.glob('*.json')) if not p.name.endswith('.private.json')}
    def build_rows(self):
        try:
            n,m=int(self.n.get()),int(self.m.get())
            if min(n,m)<0 or not 8<=n+m<=10:raise ValueError()
        except ValueError:messagebox.showerror('包房','账号合计须为8～10',parent=self.window);return
        for child in self.table.winfo_children():child.destroy()
        self.members=[];self.options=self.account_options()
        headers=('类型','本地账号','导入','槽位','期望伤害／秒','目标占比%','运行方式')
        for col,title in enumerate(headers):ttk.Label(self.table,text=title).grid(row=0,column=col,padx=4,pady=4)
        for i,role in enumerate(['拿阵法号']*n+['挂机号']*m,1):
            row={'role':role,'account':tk.StringVar(),'slot':tk.StringVar(value='0'),'dps':tk.StringVar(value=self.app.var_world_dps.get()),'target':tk.StringVar(value=self.app.var_world_target.get()),'mode':tk.StringVar(value=MODES[0] if role=='拿阵法号' else MODES[2])}
            self.members.append(row);ttk.Label(self.table,text=role).grid(row=i,column=0,padx=4)
            combo=ttk.Combobox(self.table,textvariable=row['account'],values=list(self.options),state='readonly',width=19);combo.grid(row=i,column=1,padx=4,pady=5)
            ttk.Button(self.table,text='选择文件',command=lambda r=row,c=combo:self.choose_file(r,c)).grid(row=i,column=2,padx=4)
            ttk.Combobox(self.table,textvariable=row['slot'],values=list(range(8)),state='readonly',width=3).grid(row=i,column=3,padx=4)
            ttk.Entry(self.table,textvariable=row['dps'],width=12).grid(row=i,column=4,padx=4)
            ttk.Entry(self.table,textvariable=row['target'],width=7).grid(row=i,column=5,padx=4)
            ttk.Combobox(self.table,textvariable=row['mode'],values=MODES,state='readonly',width=22).grid(row=i,column=6,padx=4)
        self.queried_job=None
    def choose_file(self,row,combo):
        path=filedialog.askopenfilename(parent=self.window,title='选择已登录的单个账号文件',filetypes=[('账号JSON','*.json')])
        if not path:return
        name=Path(path).stem
        if name in self.options and self.options[name]!=path:name=str(Path(path))
        self.options[name]=path;combo.configure(values=list(self.options));row['account'].set(name)
    def job(self):
        result={'boss_id':int(self.boss.get().split()[0]),'room_id':self.room.get().strip(),'members':[]}
        for row in self.members:
            if row['account'].get() not in self.options:raise ValueError('请为每一行选择账号')
            result['members'].append({'account_file':self.options[row['account'].get()],'slot':int(row['slot'].get()),'role':row['role'],'dps':float(row['dps'].get()),'target':float(row['target'].get()),'mode':row['mode'].get()})
        validate(result);return result
    def launch(self,action):
        if not self.unlocked():return
        if self.app.running:return
        try:
            job=self.job()
            if action=='query':
                folder=ROOT/'world_boss_room_jobs';folder.mkdir(exist_ok=True)
                self.job_path=folder/('job_%s.json'%time.time_ns());self.job_path.write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8');self.queried_job=job
            else:
                if self.queried_job!=job or self.job_path is None:raise ValueError('设置已变更，请先查询当前配置')
                report=self.job_path.with_suffix('.report.json')
                data=json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
                if data.get('status')!='queried' or not data.get('eligible_rooms'):raise ValueError('请先完成查询，并确认存在可容纳全组的房间')
                n=sum(r['role']=='拿阵法号' for r in job['members']);m=len(job['members'])-n
                if not messagebox.askyesno('世界boss包房界面','确认以%s个拿阵法号＋%s个挂机号进入同一房间？\n每个账号按当前行设置执行，挑战可能消耗次数。'%(n,m),parent=self.window):return
            self.app._launch([str(ROOT/'world_boss_room.py'),'--job',str(self.job_path),'--action',action])
            self.summary.set('查询中，查看主窗口日志。' if action=='query' else '包房运行中，查看主窗口日志；停止请使用本界面的停止按钮。')
        except (ValueError,OSError,KeyError) as exc:messagebox.showerror('未执行',str(exc),parent=self.window)
    def stop(self):
        if self.job_path is not None:
            self.job_path.with_suffix('.stop').write_text('stop',encoding='utf-8');self.summary.set('已请求停止，正在退出各账号。')
