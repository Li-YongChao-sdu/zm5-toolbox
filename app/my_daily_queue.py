"""GUI 顺序队列：先资源准备，复用原模块命令，最后领取活跃奖励。"""
import json
from pathlib import Path
from tkinter import messagebox
ROOT=Path(__file__).resolve().parent

class ModuleQueue:
    def __init__(self,window):
        self.window=window;self.app=window.app;self.active=False;self.pending=[]
        original_launch=self.app._launch;original_stop=self.app._stop
        def launch(args,extra_env=None):
            if self.active:
                args=list(args)
                if Path(args[0]).name!='my_daily_runner.py':args=[str(ROOT/'my_daily_script.py')]+args
                self.app._my_daily_result=None
            started=original_launch(args,extra_env=extra_env)
            if self.active and started is not False and self.app.running:self.launched=True
            return started
        def stop():
            self.cancel('用户停止了本批任务');return original_stop()
        self.app._launch=launch;self.app._stop=stop

    def identity(self):
        account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
        return str(account.get('uid')),str(account.get('username')),str(self.app.cmb_slot.get())

    def start(self,keys):
        owner=getattr(self.app,'_personal_queue',None)
        if self.active or (owner is not None and owner.active) or self.app.running or self.app.execution_gate.busy:return
        modules=self.window.modules;core=set(keys)-set(modules)
        self.binding=self.identity();self.pending=[]
        last=core & {'RUN_LIVENESS'};core-=last
        if core:self.pending.append(('日常任务',lambda chosen=core:self.app._start(task_keys=chosen,free_only=True)))
        from my_daily_modules import check_non_ticket
        for key in keys:
            if key not in modules:continue
            row=modules[key]
            def run(row=row):
                check_non_ticket(self.app,row)
                if 'fun_label' in row:self.app.fun_batch_page.run([row['fun_label']])
                else:
                    button=row.get('button')
                    if button is not None and 'disabled' in button.state():raise ValueError('原页面入口当前不可用')
                    row['command']()
            self.pending.append((row['label'],run))
        if last:self.pending.append(('每日活跃',lambda:self.app._start(task_keys={'RUN_LIVENESS'},free_only=True)))
        self.active=True;self.app._personal_queue=self;self.next()

    def cancel(self,reason):
        if self.active:self.app._append_log('[我的日常] '+reason)
        self.active=False;self.pending=[]
        if getattr(self.app,'_personal_queue',None) is self:self.app._personal_queue=None

    def next(self):
        if not self.active:return
        if not self.pending:self.cancel('所选项目执行结束');return
        try:
            if self.identity()!=self.binding:raise ValueError('账号或主存档已变化，本批停止')
            label,command=self.pending.pop(0);self.launched=False
            self.app._append_log('[我的日常] 执行：'+label)
            command()
            if not self.launched:raise ValueError('该项未启动（取消确认、条件不足或设置未完成），本批停止')
        except Exception as exc:
            self.cancel(str(exc));return
        self.app.root.after(100,self.poll)

    def poll(self):
        if not self.active:return
        if self.app.running or self.app.execution_gate.busy:
            self.app.root.after(100,self.poll);return
        if getattr(self.app,'_my_daily_result',None)!=0:
            self.cancel('上一项未正常完成，保留后续项目；请核对日志后重新选择执行');return
        self.app.root.after_idle(self.next)
