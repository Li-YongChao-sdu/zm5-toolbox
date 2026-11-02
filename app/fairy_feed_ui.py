"""幻兽喂养下拉列表：按账号和存档保存稳定身份，仅服务器状态用于实际执行。"""
import json,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parent

class FeedListCache:
    def __init__(self,path):self.path=Path(path)
    def load(self):
        try:
            if self.path.stat().st_size>2*1024*1024:return {}
            value=json.loads(self.path.read_text(encoding='utf-8'))
            return value.get('entries',{}) if isinstance(value,dict) and value.get('version')==1 and isinstance(value.get('entries'),dict) else {}
        except (OSError,ValueError):return {}
    def get(self,binding):
        entry=self.load().get('%s:%s'%binding,{})
        return entry if isinstance(entry,dict) else {}
    def put(self,binding,rows,selected):
        entries=self.load();entries['%s:%s'%binding]={'fairies':rows,'selected':selected,'updated':time.time()}
        self.path.parent.mkdir(parents=True,exist_ok=True);temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps({'version':1,'entries':entries},ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(self.path)

class FairyFeedPanel:
    def __init__(self,app,parent,account_path=None,cache_path=None):
        self.app=app;self.parent=parent;self.account_path=Path(account_path) if account_path else ROOT/'account.local.json'
        self.cache=FeedListCache(cache_path or ROOT/'fairy_feed_cache'/'lists.json')
        self.binding=None;self.rows={};self._source_rows=[];self._quotas={};self.selected_id='';self.reload_job=None;self.buttons=[]
        self.display=tk.StringVar(master=app.root);self.summary=tk.StringVar(master=app.root,value='请查询当前账号及存档的幻兽列表')
        ttk.Label(parent,textvariable=self.summary,wraplength=850).pack(anchor='w',pady=4)
        row=ttk.Frame(parent);row.pack(fill='x',pady=3);ttk.Label(row,text='选择幻兽：',width=23).pack(side='left')
        self.combo=ttk.Combobox(row,textvariable=self.display,values=(),state='readonly',width=55);self.combo.pack(side='left')
        self.combo.bind('<<ComboboxSelected>>',self.select)
        row=ttk.Frame(parent);row.pack(fill='x',pady=3);ttk.Label(row,text='喂养角色：',width=23).pack(side='left')
        self.role=tk.StringVar(master=app.root,value='主角色（1p）')
        ttk.Combobox(row,textvariable=self.role,values=('主角色（1p）','副角色（2p）'),state='readonly',width=14).pack(side='left')
        self.role.trace_add('write',self.role_changed)
        ttk.Label(row,text='副角色次数仅用于副角色身上幻兽').pack(side='left',padx=8)
        row=ttk.Frame(parent);row.pack(fill='x',pady=3);ttk.Label(row,text='次数（空白=当日喂满）',width=23).pack(side='left')
        self.times=tk.StringVar(master=app.root);ttk.Entry(row,textvariable=self.times,width=20).pack(side='left')
        self.kind=tk.StringVar(master=app.root,value='灵魂')
        ttk.Combobox(row,textvariable=self.kind,values=('灵魂','妖元'),state='readonly',width=10).pack(side='left',padx=8)
        actions=ttk.Frame(parent);actions.pack(fill='x')
        for label,action in (('查询／刷新幻兽列表','query'),('喂养选中幻兽','feed'),('同时喂养1p和2p','feed_both')):
            button=ttk.Button(actions,text=label,command=lambda a=action:self.launch(a));button.pack(side='left',padx=(0,8),pady=4);self.buttons.append(button)
        ttk.Label(parent,text='列表按账号＋存档缓存，可下次直接选择；执行前会向服务器重新核对。服务器按幻兽所在角色计次：背包和主角色身上记主角色次数，只有副角色身上出战的幻兽记副角色次数。同时喂养会分别喂养1p、2p身上出战的幻兽。',wraplength=850).pack(anchor='w',pady=4)
        app.ui_settings_fields['幻兽喂养/次数（空白=当日喂满）']=(self.times,None)
        app.ui_settings_fields['幻兽喂养/喂养方式']=(self.kind,['灵魂','妖元'])
        app.ui_settings_fields['幻兽喂养/喂养角色']=(self.role,['主角色（1p）','副角色（2p）'])
        self.invalidate()
    def role_value(self):
        """当前选择的出战角色编号：0=主角色(1p)，1=副角色(2p)。"""
        return 0 if '主' in self.role.get() else 1
    def role_changed(self,*_args):
        self._rebuild(self.selected_id)
    def current_binding(self):
        account=json.loads(self.account_path.read_text(encoding='utf-8-sig'))
        uid=str(account.get('uid',''));slot=int(self.app.cmb_slot.get())
        if not uid.isdigit() or not 0<=slot<=7:raise ValueError('请先载入账号和存档')
        return uid,slot
    @staticmethod
    def clean_rows(rows):
        if not isinstance(rows,list) or len(rows)>1000:raise ValueError('幻兽列表格式无效')
        output=[];seen=set()
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('entityId'),str) or not row['entityId'] or row['entityId'] in seen:continue
            seen.add(row['entityId']);output.append({key:row.get(key) for key in ('entityId','name','level','step','source','role')})
        return output
    def _rebuild(self,selected=''):
        role=self.role_value();rows=[r for r in self._source_rows if r.get('role') in (None,role)]
        self.rows={};labels=[]
        for index,row in enumerate(rows,1):
            tag='' if row.get('source') in (None,'背包') else '·%s'%row.get('source')
            label='%s｜%s阶｜Lv%s%s（%s）'%(row.get('name') or '幻兽',row.get('step') if row.get('step') is not None else '?',row.get('level') if row.get('level') is not None else '?',tag,index)
            labels.append(label);self.rows[label]=row
        self.combo.configure(values=labels);self.selected_id='';self.display.set('')
        for label,row in self.rows.items():
            if row['entityId']==selected:self.display.set(label);self.selected_id=selected;break
    def _quota_text(self):
        quotas=self._quotas if isinstance(self._quotas,dict) else {}
        parts=[]
        for key,label in (('0','主角色'),('1','副角色')):
            item=quotas.get(key)
            if isinstance(item,dict):parts.append('%s剩%s次'%(label,item.get('left')))
        return '｜今日灵魂喂养 '+'，'.join(parts) if parts else '｜执行前自动核对最新状态'
    def fill(self,binding,rows,selected='',cached=False,quotas=None):
        self._source_rows=self.clean_rows(rows);self.binding=binding
        if isinstance(quotas,dict):self._quotas=quotas
        self._rebuild(selected)
        prefix='缓存列表' if cached else '服务器最新列表'
        self.summary.set('%s：槽%s，共%s只%s'%(prefix,binding[1],len(self.rows),self._quota_text()))
    def restore_cached(self):
        self.reload_job=None
        try:
            binding=self.current_binding();entry=self.cache.get(binding)
            self.fill(binding,entry.get('fairies',[]),entry.get('selected',''),cached=True)
            if not self.rows:self.summary.set('当前账号槽%s暂无缓存，请查询幻兽列表'%binding[1])
        except (OSError,ValueError,TypeError):self.summary.set('请先载入账号和存档，再查询幻兽列表')
    def invalidate(self):
        if self.reload_job is not None:
            try:self.app.root.after_cancel(self.reload_job)
            except tk.TclError:pass
        self.binding=None;self.rows={};self._source_rows=[];self._quotas={};self.selected_id='';self.display.set('');self.combo.configure(values=())
        self.summary.set('账号或存档已切换，正在读取对应缓存')
        self.reload_job=self.app.root.after_idle(self.restore_cached)
    def render(self,data):
        binding=(str(data['uid']),int(data['slot']))
        # Ignore delayed results from a different account/slot even if still queued.
        if binding!=self.current_binding():return False
        selected=self.selected_id if self.binding==binding else ''
        if not selected:selected=self.cache.get(binding).get('selected','')
        self.fill(binding,data['fairies'],selected,quotas=data.get('quotas') or ({'0':data.get('quota')} if data.get('quota') else None));self.save_selection();return True
    def save_selection(self):
        if self.binding is not None:
            try:self.cache.put(self.binding,list(self._source_rows),self.selected_id)
            except OSError:self.summary.set(self.summary.get()+'｜本地缓存写入失败，本次列表仍可用')
    def select(self,_event=None):
        if self.binding!=self.current_binding():self.invalidate();return
        row=self.rows.get(self.display.get());self.selected_id=(row or {}).get('entityId','');self.save_selection()
    def launch(self,action):
        if self.app.running or not self.app._save_selected_slot():return
        try:
            binding=self.current_binding();args=[str(ROOT/'fairy_feed_run.py'),'--expected-uid',binding[0],'--expected-slot',str(binding[1])]
            if action in ('feed','feed_both'):
                if self.binding!=binding:raise ValueError('账号或存档已变更，请重新选择对应幻兽')
                times=self.times.get().strip()
                if times:
                    count=int(times)
                    if count<=0:raise ValueError('喂养次数须为正整数或留空')
                if action=='feed':
                    row=self.rows.get(self.display.get())
                    if not row:raise ValueError('请先从下拉列表选择要喂养的幻兽')
                    args+=['--feed','--entity',row['entityId'],'--apply','--role',str(self.role_value())]
                    if times:args+=['--times',str(count)]
                    if self.kind.get()=='妖元':args.append('--item')
                    self.selected_id=row['entityId'];self.save_selection()
                else:
                    if self.kind.get()=='妖元':raise ValueError('妖元喂养不占角色次数，无需同时喂养')
                    targets={}
                    for role,label in ((0,'1p'),(1,'2p')):
                        body=[x for x in self._source_rows if x.get('role')==role]
                        left=(self._quotas.get(str(role)) or {}).get('left','?')
                        targets[label]='%s（剩%s次）'%(body[0]['name'],left) if body else '身上没有幻兽，跳过'
                    if not messagebox.askyesno('确认同时喂养','次数：%s\n1p：%s\n2p：%s\n确认执行？'%(times or '各自喂满',targets['1p'],targets['2p']),parent=self.parent):return
                    args+=['--feed','--both','--apply']
                    if times:args+=['--times',str(count)]
            self.app._launch(args)
        except (OSError,ValueError,KeyError) as exc:messagebox.showerror('未执行',str(exc),parent=self.parent)
