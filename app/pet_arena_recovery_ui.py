"""点券斗宠页内的历史次数找回入口，复用对手、间隔和本页点券权限。"""
import json
import math
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

ROOT = Path(__file__).resolve().parent
SCOPES = {'全部可找回历史日': 'all', **{'周'+n: str(i) for i, n in enumerate('一二三四五六', 1)}}


class PetArenaRecoveryPanel:
    def __init__(self, owner):
        self.owner, self.app, self.data = owner, owner.app, None
        self.box = ttk.LabelFrame(owner.box, text='历史次数找回并挑战', padding=5)
        self.scope = tk.StringVar(value='全部可找回历史日')
        self.password = tk.StringVar(value='')
        self.password_owner = None
        self.summary = tk.StringVar(value='先查询可找回日期、次数和费用；先打完现有次数，再逐日找回并打完。')
        row = ttk.Frame(self.box); row.pack(anchor='w')
        ttk.Combobox(row, textvariable=self.scope, values=list(SCOPES), width=20,
                     state='readonly').pack(side='left')
        ttk.Label(row, text='二级密码：').pack(side='left', padx=(8, 0))
        ttk.Entry(row, textvariable=self.password, show='*', width=14).pack(side='left')
        for label, action in (('查询找回费用', 'query'), ('确认找回并挑战', 'run'), ('继续找回任务', 'resume')):
            button = ttk.Button(row, text=label, command=lambda a=action: self.launch(a))
            button.pack(side='left', padx=4)
            owner.buttons.append(button)
        ttk.Label(self.box, textvariable=self.summary, wraplength=900).pack(anchor='w', pady=4)
        ttk.Label(self.box, text='沿用上方对手及等待间隔。按历史日整批找回，费用计入本页点券预算；密码不保存，断线先核对再继续。',
                  wraplength=900).pack(anchor='w')
        self.scope.trace_add('write', lambda *_: self.invalidate())
        self.password.trace_add('write', self.bind_password)
        self.app.cmb_slot.bind('<<ComboboxSelected>>', self.clear, add='+')
        self.refresh()

    def clear(self, *_):
        self.password.set('')
        self.invalidate()

    def bind_password(self, *_):
        try:
            self.password_owner = self.binding()[:2] if self.password.get() else None
        except (OSError, ValueError, KeyError):
            self.password_owner = None

    def refresh(self):
        if self.owner.handler() in ('arena','petArena'):
            self.box.pack(fill='x', pady=6)
        else:
            self.box.pack_forget()

    def invalidate(self):
        self.data = None
        self.summary.set('请查询当前账号、槽位、对手和历史日的找回费用。')
        self.refresh()

    def binding(self):
        a = json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
        return str(a.get('username', '')), int(self.app.cmb_slot.get()), self.owner.selected_rid(), SCOPES[self.scope.get()]

    def matches(self, d):
        return d.get('handler','petArena') == self.owner.handler() and (d['account'], d['slot'], d['target'], d['scope']) == self.binding()

    def render(self, data):
        if data.get('handler','petArena') != self.owner.handler() or not self.matches(data):
            self.clear()
            return
        self.data = data
        s, p = data['state'], data['plan']
        batches = '；'.join('周%s：%s次/%s点券' % ('一二三四五六'[d['day']-1], d['count'], d['cost']) for d in p['days'])
        text = '槽%s｜%s｜现有%s次｜点券%s｜单次找回%s点券\n%s\n合计%s点券，含现有次数共%s局' % (
            data['slot'], data['target_label'], s['remaining'], s['ticket'], p['price'],
            batches or '所选历史日无可找回次数', p['cost'], p['rounds'])
        if data.get('resume'):
            r = data['resume']
            text += '\n未完成找回任务：%s/%s局，剩余费用上限%s点券；继续前核对服务器。' % (r['completed'], r['rounds'], r['cost'])
        self.summary.set(text)

    def launch(self, action):
        if self.app.running or not self.app._save_selected_slot():
            return
        try:
            account, slot, target, scope = self.binding()
            args = [str(ROOT/'pet_arena_recovery.py'), '--action', action,
                    '--handler', self.owner.handler(), '--target', target, '--scope', scope]
            extra = {}
            if action != 'query':
                if self.password.get() and self.password_owner != (account, slot):
                    self.password.set('')
                    raise ValueError('账号或槽位已切换，请重新填写本存档的二级密码')
                d = self.data
                if not d or not self.matches(d):
                    raise ValueError('请先查询当前账号、槽位、对手和找回范围')
                battle, interval = float(self.owner.battle.get()), float(self.owner.interval.get())
                if not all(math.isfinite(v) and low <= v <= 3600 for v, low in ((battle, 2), (interval, 8))):
                    raise ValueError('局内最低2秒、局间最低8秒，最长3600秒')
                if action == 'resume':
                    r = d.get('resume')
                    if not r or r['target'] != target or r['scope'] != scope:
                        raise ValueError('请选回未完成任务的原对手和原历史日范围，再查询')
                    cost, rounds = r['cost'], r['rounds'] - r['completed']
                else:
                    if d.get('resume'):
                        raise ValueError('该存档有未完成找回任务，请先核查并继续')
                    if not d['plan']['days']:
                        raise ValueError('没有可找回的历史日次数')
                    cost, rounds = d['plan']['cost'], d['plan']['rounds']
                self.app.spend_permissions.require('daily')
                if int(self.app.spend_permissions.budgets['daily'].get()) < max(1, cost):
                    raise ValueError('本页点券预算不足所选找回费用')
                if d['state']['ticket'] < cost:
                    raise ValueError('点券余额不足')
                if not messagebox.askyesno('确认找回并挑战',
                        '当前账号槽%s，挑战%s\n最多%s局，找回费用上限%s点券\n局内%g秒，局间%g秒\n先打已有次数，再逐日找回并打完，确认继续？' %
                        (slot, d['target_label'], rounds, cost, battle, interval), parent=self.box):
                    return
                args += ['--account', account, '--slot', str(slot), '--quote', d['quote'],
                         '--battle-wait', str(battle), '--round-wait', str(interval)]
                extra = {'ZM5_PET_RECOVERY_PASSWORD': self.password.get()}
                self.password.set('')
            self.data = None
            self.app._launch(args, extra_env=extra)
        except (ValueError, KeyError) as exc:
            messagebox.showerror('未执行', str(exc), parent=self.box)
