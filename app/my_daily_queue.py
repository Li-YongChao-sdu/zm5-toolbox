"""GUI 顺序队列：先资源准备，复用原模块命令，最后领取活跃奖励。"""
import json
from my_daily_execution import FATAL_EXIT, PREPARE, FINISH
from pathlib import Path
from tkinter import messagebox
ROOT=Path(__file__).resolve().parent

# 邮件领取依赖手动选中，不属于可自动完成项；结束汇总里不提示
SILENT_LABELS=frozenset(('领取选中邮件附件并删除',))

class ModuleQueue:
    def __init__(self,window):
        self.window=window;self.app=window.app;self.active=False;self.pending=[];self._finished=False
        original_launch=self.app._launch;original_stop=self.app._stop
        def launch(args,extra_env=None):
            if self.active:
                args=list(args)
                if Path(args[0]).name!='my_daily_runner.py':args=[str(ROOT/'my_daily_script.py')]+args
                self.app._my_daily_result=None
                from my_daily_password import prepare_launch
                args,extra_env=prepare_launch(args,extra_env,getattr(self,'_password',''))
            started=original_launch(args,extra_env=extra_env)
            if self.active and started is not False and self.app.running:self.launched=True
            return started
        def stop():
            self.cancel('用户停止了本批任务');return original_stop()
        self.app._launch=launch;self.app._stop=stop

    def identity(self):
        account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
        return str(account.get('uid')),str(account.get('username')),str(self.app.cmb_slot.get())

    def start(self,keys,password=''):
        owner=getattr(self.app,'_personal_queue',None)
        if self.active or (owner is not None and owner.active) or self.app.running or self.app.execution_gate.busy:return
        modules=self.window.modules;core=set(keys)-set(modules)
        self.binding=self.identity();self.pending=[];self.results=[];self.unexecuted=[];self._password=password;self._finished=False
        last=core & set(FINISH);core-=last
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
        if last:self.pending.append(('收尾领奖',lambda chosen=last:self.app._start(task_keys=chosen,free_only=True)))
        self.active=True;self.app._personal_queue=self;self.next()

    def cancel(self,reason):
        if self._finished:return
        self._finished=True
        if self.active:self.app._append_log('[我的日常] '+reason)
        self.unexecuted=[label for label,_ in self.pending]
        counts={kind:sum(r['status']==kind for r in getattr(self,'results',[])) for kind in ('complete','skipped','failed','fatal')}
        self.app._append_log('[我的日常汇总] 成功{complete}、跳过{skipped}、失败{failed}、中止{fatal}；未执行{n}项'.format(**counts,n=len(self.unexecuted)))
        problems=[(r['label'],'失败' if r['status']=='failed' else '中止',r.get('message') or '详见日志') for r in getattr(self,'results',[]) if r['status'] in ('failed','fatal')]
        self.active=False;self.pending=[];self._password=''
        if getattr(self.app,'_personal_queue',None) is self:self.app._personal_queue=None
        if problems or self.unexecuted:self.notify(reason,problems)

    def notify(self,reason,problems):
        problems=[item for item in problems if not any(tag in item[0] for tag in SILENT_LABELS)]
        unexecuted=[label for label in self.unexecuted if not any(tag in label for tag in SILENT_LABELS)]
        if not problems and not unexecuted:return
        lines=['执行结束：'+reason]
        if problems:
            lines.extend(['','未完成，请补提交：'])
            for label,kind,message in problems[:20]:lines.append('  - %s（%s）：%s'%(label,kind,message))
            if len(problems)>20:lines.append('  ...另有%d项'%(len(problems)-20))
        if unexecuted:
            lines.extend(['','未执行（本批停止或上一项中止）：'])
            for label in unexecuted[:20]:lines.append('  - '+label)
            if len(unexecuted)>20:lines.append('  ...另有%d项'%(len(unexecuted)-20))
        text='\n'.join(lines)
        try:self.app.root.after_idle(lambda:messagebox.showwarning('我的日常',text,parent=self.app.root))
        except Exception:pass

    def next(self):
        if not self.active:return
        if not self.pending:self.cancel('所选项目执行结束');return
        try:
            if self.identity()!=self.binding:
                self.cancel('账号或主存档已变化，本批停止');return
        except Exception as exc:
            self.cancel('无法确认账号绑定：'+str(exc));return
        label,command=self.pending.pop(0);self.current_label=label;self.launched=False
        self.app._append_log('[我的日常] 执行：'+label)
        try:
            command()
        except Exception as exc:
            self.results.append({'label':label,'status':'failed','message':str(exc)})
            self.app._append_log('[我的日常] 本项失败，继续后续：'+str(exc))
            if self.launched:
                self.app.root.after(100,self.poll)
            else:self.app.root.after_idle(self.next)
            return
        if not self.launched:
            self.results.append({'label':label,'status':'skipped','message':'未启动：条件不足、设置未完成或取消确认'})
            self.app._append_log('[我的日常] 本项未启动，跳过并继续后续：'+label)
            self.app.root.after_idle(self.next);return
        self.app.root.after(100,self.poll)

    def poll(self):
        if not self.active:return
        if self.app.running or self.app.execution_gate.busy:
            self.app.root.after(100,self.poll);return
        try:
            if self.identity()!=self.binding:
                self.cancel('账号或主存档已变化，本批停止');return
        except Exception as exc:
            self.cancel('无法确认账号绑定：'+str(exc));return
        code=getattr(self.app,'_my_daily_result',None)
        if code not in (0,1,2,3):
            self.results.append({'label':self.current_label,'status':'fatal','returncode':code,'message':getattr(self.app,'_my_daily_result_message','') or '请求未确认或触发付费保护，已停止本批'})
            self.cancel('上一项存在未确认请求、付费拦截或进程异常，停止本批；请核对日志');return
        status='complete' if code==0 else 'skipped' if code==3 else 'failed'
        self.results.append({'label':self.current_label,'status':status,'returncode':code,'message':getattr(self.app,'_my_daily_result_message','') if status=='failed' else ''})
        if status=='failed':self.app._append_log('[我的日常] 本项执行失败，已记录，继续后续：'+self.current_label)
        elif status=='skipped':self.app._append_log('[我的日常] 本项无需执行，继续后续：'+self.current_label)
        self.app.root.after_idle(self.next)
