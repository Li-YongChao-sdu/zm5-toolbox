"""在主线程显示查询结果，明确确认后才允许指定目标挑战。"""
import json
import threading
from pathlib import Path
from tkinter import ttk, messagebox
from arena_target_confirm import Approval, description
from arena_targets import detail, wait_seconds
from arena_slot_mapping import parse_ui_slot, parse_rid, saved_account, query_slot_target, number_rid


MODE_CHOICES = (
    ('fixed', '推荐列表：随机选一人，连续挑战'),
    ('refresh', '推荐列表：每局刷新随机'),
    ('highest', '推荐列表：每局选最高战力'),
    ('lowest', '推荐列表：每局选最低战力'),
    ('rank_highest', '排行榜前120名：最高战力'),
    ('rank_random', '排行榜前120名：战力前N名随机'),
    ('specified', '指定对手：UID＋槽位'),
    ('borrowed', '借用未报名小存档的推荐列表'),
)


def timing_binding(app, handler):
    prefix = 'var_arena' if handler == 'arena' else 'var_pet_arena'
    def get(suffix):
        var = getattr(app, prefix + suffix, None)
        return wait_seconds(var.get() if var is not None else 22)
    return {'battle_wait': get('_battle_wait'), 'round_wait': get('_round_wait')}


class ModeControls:
    def __init__(self, mode, specified, borrowed):
        self.mode, self.specified, self.borrowed = mode, specified, borrowed

    @property
    def querying(self):
        return self.specified.querying or self.borrowed.querying

    def invalidate(self):
        self.specified.invalidate()
        self.borrowed.invalidate()

    def require(self):
        return (self.borrowed if self.mode.get() == 'borrowed' else self.specified).require()


class ArenaModePanel:
    def __init__(self, app, parent, handler, mode, uid, slot, rounds, top_n, account_file,
                 battle_wait=None, round_wait=None, source_account=None, source_slot=None,
                 target_input=None, explicit_rid=None):
        import tkinter as tk
        self.mode = mode
        self.access_vars = app.spend_permissions.variables['dungeons']
        self.labels = dict(MODE_CHOICES)
        self.keys = {label: key for key, label in MODE_CHOICES}
        self.display = tk.StringVar(master=parent)
        ttk.Label(parent, text='挑战方式：').grid(row=0, column=0, sticky='w', padx=6, pady=6)
        self.combo = ttk.Combobox(parent, textvariable=self.display,
                                  values=tuple(self.keys), state='readonly', width=39)
        self.combo.grid(row=0, column=1, sticky='w', padx=6, pady=6)
        self.combo.bind('<<ComboboxSelected>>', self.select)
        self.n_frame = ttk.Frame(parent)
        self.n_frame.grid(row=1, column=0, columnspan=2, sticky='w', padx=6)
        ttk.Label(self.n_frame, text='战力候选人数 N（10～100）：').pack(side='left')
        ttk.Spinbox(self.n_frame, from_=10, to=100, textvariable=top_n, width=5).pack(side='left', padx=6)
        self.rounds_frame = ttk.Frame(parent)
        self.rounds_frame.grid(row=2, column=0, columnspan=2, sticky='w', padx=6, pady=4)
        ttk.Label(self.rounds_frame, text='连续挑战上限：').pack(side='left')
        ttk.Combobox(self.rounds_frame, textvariable=rounds, values=(5, 10),
                     state='readonly', width=5).pack(side='left', padx=6)
        ttk.Label(self.rounds_frame, text='局（只使用当天剩余免费次数）').pack(side='left')
        self.target_frame = ttk.Frame(parent)
        self.target_frame.grid(row=3, column=0, columnspan=2, sticky='w', padx=6)
        if target_input is None:
            target_input = tk.StringVar(master=parent, value='r_number')
        if explicit_rid is None:
            explicit_rid = tk.StringVar(master=parent, value='')
        input_labels = {'r_number': '游戏UID＋实际r编号', 'rid': '完整实际rid'}
        input_display = tk.StringVar(master=parent)
        ttk.Label(self.target_frame, text='输入方式：').grid(row=0, column=0, sticky='w')
        input_combo = ttk.Combobox(self.target_frame, textvariable=input_display,
                                   values=list(input_labels.values()), state='readonly', width=34)
        input_combo.grid(row=0, column=1, columnspan=4, sticky='w', padx=6)
        input_combo.bind('<<ComboboxSelected>>', lambda _event: target_input.set(
            next(key for key, label in input_labels.items() if label == input_display.get())))
        slot_widgets = [ttk.Label(self.target_frame, text='游戏 UID：'),
                        ttk.Entry(self.target_frame, textvariable=uid, width=18),
                        ttk.Label(self.target_frame, text='实际r编号：'),
                        ttk.Entry(self.target_frame, textvariable=slot, width=5)]
        for column, widget in enumerate(slot_widgets):
            widget.grid(row=1, column=column, sticky='w', padx=6, pady=4)
        rid_widgets = [ttk.Label(self.target_frame, text='实际存档ID：'),
                       ttk.Entry(self.target_frame, textvariable=explicit_rid, width=30)]
        for column, widget in enumerate(rid_widgets):
            widget.grid(row=2, column=column, sticky='w', padx=6, pady=4)
        def refresh_input(*_):
            key = target_input.get()
            if key not in input_labels:
                key = 'r_number'
                slot.set('')
                target_input.set(key)
            input_display.set(input_labels[key])
            for widgets, visible in ((slot_widgets, key == 'r_number'), (rid_widgets, key == 'rid')):
                for widget in widgets:
                    widget.grid() if visible else widget.grid_remove()
        target_input.trace_add('write', refresh_input)
        refresh_input()
        from pet_arena_paid import PRESETS
        self.preset = tk.StringVar(master=parent, value='自定义RID')
        ttk.Label(self.target_frame, text='预设对手：').grid(row=3, column=0, sticky='w', padx=6)
        preset_combo = ttk.Combobox(self.target_frame, textvariable=self.preset,
                                   values=(*PRESETS, '自定义RID'), state='readonly', width=22)
        preset_combo.grid(row=3, column=1, columnspan=3, sticky='w', padx=6, pady=4)
        def select_preset(_event=None):
            if ''.join('1' if v.get() else '0' for v in self.access_vars) != '001':return
            rid = PRESETS.get(self.preset.get())
            if rid:
                target_input.set('rid')
                explicit_rid.set(rid)
        def sync_preset(*_):
            rid = explicit_rid.get() if target_input.get() == 'rid' else ''
            self.preset.set(next((label for label, value in PRESETS.items() if value == rid), '自定义RID'))
        preset_combo.bind('<<ComboboxSelected>>', select_preset)
        target_input.trace_add('write', sync_preset)
        explicit_rid.trace_add('write', sync_preset)
        sync_preset()
        specified = TargetControls(app, self.target_frame, handler, mode, uid, slot, rounds, account_file,
                                   target_input, explicit_rid)
        timing_frame = ttk.Frame(parent)
        timing_frame.grid(row=4, column=0, columnspan=2, sticky='w', padx=6, pady=5)
        for label, var in (('每局等待（秒）：', battle_wait), ('局间等待（秒）：', round_wait)):
            if var is None:
                var = tk.StringVar(master=parent, value='22')
            ttk.Label(timing_frame, text=label).pack(side='left')
            ttk.Spinbox(timing_frame, from_=0, to=3600, increment=1, textvariable=var, width=6).pack(side='left', padx=6)
        self.borrow_frame = ttk.Frame(parent)
        self.borrow_frame.grid(row=5, column=0, columnspan=2, sticky='w', padx=6)
        if source_account is None:
            source_account = tk.StringVar(master=parent, value='当前账号')
        if source_slot is None:
            source_slot = tk.StringVar(master=parent, value='0')
        borrowed = BorrowControls(app, self.borrow_frame, handler, mode, source_account,
                                  source_slot, rounds, account_file)
        self.control = ModeControls(mode, specified, borrowed)
        self.mode.trace_add('write', self.refresh)
        for var in self.access_vars:
            var.trace_add('write', self.refresh)
        self.refresh()

    def select(self, _event=None):
        self.mode.set(self.keys[self.display.get()])

    def refresh(self, *_):
        unlocked = ''.join('1' if v.get() else '0' for v in self.access_vars) == '001'
        choices = MODE_CHOICES if unlocked else tuple(item for item in MODE_CHOICES if item[0] == 'refresh')
        allowed = dict(choices)
        self.combo.configure(values=tuple(label for _, label in choices))
        key = self.mode.get()
        if key not in allowed:
            self.mode.set('refresh')
            key = 'refresh'
        self.display.set(self.labels[key])
        for frame, visible in (
                (self.n_frame, key == 'rank_random'),
                (self.rounds_frame, key in ('rank_highest', 'rank_random', 'specified', 'borrowed')),
                (self.target_frame, key == 'specified'),
                (self.borrow_frame, key == 'borrowed')):
            if visible:
                frame.grid()
            else:
                frame.grid_remove()


class TargetControls:
    def __init__(self, app, parent, handler, mode, uid, slot, rounds, account_file,
                 target_input=None, explicit_rid=None):
        import tkinter as tk
        self.target_input = target_input if target_input is not None else tk.StringVar(master=parent, value='r_number')
        self.explicit_rid = explicit_rid if explicit_rid is not None else tk.StringVar(master=parent, value='')
        self.query_mode = 'specified'
        self.app, self.handler = app, handler
        self.mode, self.uid, self.slot, self.rounds = mode, uid, slot, rounds
        self.account_file = account_file
        self.state = Approval()
        self.data = None
        self.querying = False
        self.query_button = ttk.Button(parent, text='查询对手', command=self.query)
        self.query_button.grid(row=5, column=0, sticky='w', padx=6, pady=4)
        self.confirm_button = ttk.Button(parent, text='确认此对手', command=self.confirm, state='disabled')
        self.confirm_button.grid(row=5, column=1, columnspan=2, sticky='w', padx=6)
        self.label = ttk.Label(parent, text='指定对手须先查询，再确认；确认后点击任务开始按钮。', wraplength=730)
        self.label.grid(row=6, column=0, columnspan=6, sticky='w', padx=6, pady=(0, 6))
        prefix = 'var_arena' if handler == 'arena' else 'var_pet_arena'
        variables = [mode, uid, slot, rounds, self.target_input, self.explicit_rid]
        variables.extend(getattr(app, prefix + suffix) for suffix in ('_battle_wait', '_round_wait')
                         if hasattr(app, prefix + suffix))
        for var in variables:
            var.trace_add('write', lambda *_: self.invalidate())

    def log(self, message):
        append = getattr(self.app, '_append_log', None)
        if append:
            title = '竞技场' if self.handler == 'arena' else '斗宠'
            kind = '借用列表' if self.query_mode == 'borrowed' else '指定对手'
            append('[%s·%s] %s' % (title, kind, message))

    def query_started(self, binding):
        if self.query_mode == 'borrowed':
            self.log('开始查询：出战A UID %s 槽%d；来源B UID %s 槽%d。只查询，未挑战。' %
                     (binding['actor_uid'], binding['actor_slot'], binding['source_uid'], binding['source_slot']))
        else:
            self.log('开始查询对手资料；尚未确认，不会挑战。')

    def query_completed(self, result):
        self.log('查询成功：' + self.describe(result))
        self.log('尚未确认。请核对后点击确认按钮；确认后还需点击任务开始按钮。')

    def invalidate(self):
        had_approval = self.state.approved is not None
        self.state.invalidate()
        if had_approval:
            self.log('设置或账号已变更，原确认已失效；请重新查询并确认。')
        self.data = None
        self.confirm_button.configure(state='disabled')
        self.label.configure(text='未确认：请查询对手并核对名字、角色或宠物阵容。')

    def binding(self):
        with open(self.account_file, encoding='utf-8') as stream:
            account = json.load(stream)
        if not account.get('uid') or not account.get('cookies'):
            raise ValueError('请先载入登录账号')
        binding = {'actor_uid': str(account['uid']), 'actor_slot': int(self.app.cmb_slot.get()),
                   'handler': self.handler, 'rounds': int(self.rounds.get()),
                   'target_input': self.target_input.get(), **timing_binding(self.app, self.handler)}
        if binding['target_input'] == 'r_number':
            binding.update(rid=number_rid(self.uid.get(), self.slot.get()),
                           target_uid=self.uid.get().strip(), r_number=int(self.slot.get().strip()))
        elif binding['target_input'] == 'slot':
            uid, slot = parse_ui_slot(self.uid.get(), self.slot.get())
            binding.update(target_uid=uid, target_slot=slot)
        elif binding['target_input'] == 'rid':
            binding['rid'] = parse_rid(self.explicit_rid.get())
        else:
            raise ValueError('请选择有效的对手输入方式')
        return account, binding

    def query(self):
        if self.app.running or self.querying or any(
                control.querying for control in getattr(self.app, 'arena_target_controls', {}).values()):
            messagebox.showinfo('查询对手', '请等待当前任务或查询完成。')
            return
        if self.mode.get() != self.query_mode:
            self.mode.set(self.query_mode)
        self.invalidate()
        try:
            account, binding = self.binding()
            payload = self.capture_query(account, binding)
        except (OSError, ValueError) as exc:
            self.log('查询未开始：' + str(exc))
            messagebox.showerror('查询对手', str(exc))
            return
        revision = self.state.revision
        self.querying = True
        self.query_button.configure(state='disabled')
        self.label.configure(text='正在查询；不会发起挑战或消耗挑战次数……')
        self.query_started(binding)
        def worker():
            result, error = None, None
            try:
                result = self.perform_query(payload, binding)
            except (ValueError, RuntimeError) as exc:
                error = str(exc)[:400] + '；未确认、未挑战。'
            except Exception as exc:
                error = '查询失败（%s），未确认、未挑战。' % type(exc).__name__
            self.app.root.after(0, lambda: self.finish(revision, binding, result, error))
        threading.Thread(target=worker, daemon=True).start()

    def capture_query(self, account, binding):
        payload = {'actor': account}
        if binding['target_input'] == 'slot':
            directory = getattr(self.app, 'accounts_dir', Path(self.account_file).parent / 'accounts')
            payload['target'] = saved_account(account, directory, binding['target_uid'])
        return payload

    def perform_query(self, payload, binding):
        actor = payload['actor']
        if binding['target_input'] == 'slot':
            return query_slot_target(actor, binding['actor_slot'], payload['target'],
                                     binding['target_slot'], self.handler)
        from teacher_trial import connect
        flow = None
        try:
            flow, _ = connect(actor, binding['actor_slot'])
            return detail(flow, self.handler, binding['rid'])
        finally:
            if flow:
                flow.disconnect()

    def accept_result(self, revision, binding, result):
        self.state.receive(revision, binding, result, self.handler)
        self.data = result

    def describe(self, data):
        text = description(data, self.handler)
        mapping = data.get('_ui_slot_mapping')
        if mapping:
            text = '查询界面槽位%d → 实际存档ID %s\n' % (mapping['slot'], mapping['rid']) + text
        return text

    def finish(self, revision, binding, result, error):
        self.querying = False
        self.query_button.configure(state='normal')
        try:
            _, current = self.binding()
        except (OSError, ValueError):
            self.invalidate()
            self.log('当前账号或设置已不可用，查询结果已丢弃；未确认、未挑战。')
            return
        if revision != self.state.revision or current != binding:
            self.invalidate()
            self.log('查询期间账号或设置变更，旧结果已丢弃；未确认、未挑战。')
            return
        if error:
            self.log('查询失败：' + error)
            self.label.configure(text=error)
            return
        try:
            self.accept_result(revision, binding, result)
        except (ValueError, RuntimeError) as exc:
            self.invalidate()
            self.label.configure(text=str(exc) + '；未确认、未挑战。')
            self.log('查询核对失败：' + str(exc) + '；未确认、未挑战。')
            return
        self.label.configure(text=self.describe(result) + '\n尚未确认，不会挑战。')
        self.confirm_button.configure(state='normal')
        self.query_completed(result)

    def confirmation_summary(self):
        return self.describe(self.data)

    def confirm(self):
        if self.app.running:
            return
        try:
            _, binding = self.binding()
            if not self.data or self.state.result is None:
                raise ValueError('请先查询对手')
            text = self.confirmation_summary()
            text += '\n\n由账号UID %s 的槽%d挑战，最多%d局免费次数。\n确认对手无误？' % (binding['actor_uid'], binding['actor_slot'], binding['rounds'])
            text += '\n每局等待%g秒，局间等待%g秒。' % (binding['battle_wait'], binding['round_wait'])
            if not messagebox.askyesno('确认借用列表' if self.query_mode == 'borrowed' else '确认指定对手', text):
                self.state.approved = None
                self.log('已取消确认；不会发起挑战。')
                self.label.configure(text=self.describe(self.data) + '\n未确认，不会挑战。')
                return
            self.state.confirm(binding)
            self.log('已确认，最多%d局；每局等待%g秒，局间等待%g秒。尚未开战，等待点击任务开始按钮。' %
                     (binding['rounds'], binding['battle_wait'], binding['round_wait']))
            self.label.configure(text=self.describe(self.data) + '\n已确认，点击任务开始按钮后执行。')
        except (OSError, ValueError) as exc:
            self.invalidate()
            self.log('无法确认：' + str(exc))
            messagebox.showerror('确认指定对手', str(exc))

    def require(self):
        _, binding = self.binding()
        return self.state.require(binding)


class BorrowControls(TargetControls):
    def __init__(self, app, parent, handler, mode, source_account, source_slot, rounds, account_file):
        super().__init__(app, parent, handler, mode, source_account, source_slot, rounds, account_file)
        self.query_mode = 'borrowed'
        self.accounts_dir = Path(getattr(app, 'accounts_dir', Path(account_file).parent / 'accounts'))
        ttk.Label(parent, text='提供列表的账号B：').grid(row=0, column=0, sticky='w')
        self.source_combo = ttk.Combobox(parent, textvariable=source_account, state='readonly', width=20,
                                        postcommand=self.refresh_accounts)
        self.source_combo.grid(row=0, column=1, sticky='w', padx=6)
        ttk.Label(parent, text='小存档槽位：').grid(row=0, column=2, sticky='w')
        ttk.Spinbox(parent, from_=0, to=7, textvariable=source_slot, width=5).grid(row=0, column=3, sticky='w')
        self.refresh_accounts()
        self.query_button.configure(text='查询借用列表')
        self.confirm_button.configure(text='确认使用此列表')
        self.label.configure(text='A使用主窗口当前账号和出战槽位；B须未报名。先查询列表，再确认。')

    def refresh_accounts(self):
        names = sorted(p.stem for p in self.accounts_dir.glob('*.json'))
        self.source_combo.configure(values=['当前账号'] + names)

    def source(self, actor):
        name = self.uid.get()
        if name == '当前账号':
            return dict(actor)
        allowed = {p.stem: p for p in self.accounts_dir.glob('*.json')}
        if name not in allowed:
            raise ValueError('请选择有效的已保存账号B')
        with allowed[name].open(encoding='utf-8') as stream:
            account = json.load(stream)
        if not account.get('uid') or not account.get('cookies'):
            raise ValueError('账号B缺少登录资料，请先登录并保存该账号')
        return account

    def binding(self):
        with open(self.account_file, encoding='utf-8') as stream:
            actor = json.load(stream)
        if not actor.get('uid') or not actor.get('cookies'):
            raise ValueError('请先载入出战账号A')
        text = self.slot.get().strip()
        if not text.isascii() or not text.isdigit() or not 0 <= int(text) <= 7:
            raise ValueError('小存档槽位须为0～7')
        source = self.source(actor)
        return actor, {'actor_uid': str(actor['uid']), 'actor_slot': int(self.app.cmb_slot.get()),
                       'handler': self.handler, 'rounds': int(self.rounds.get()),
                       'source_account': self.uid.get(), 'source_uid': str(source['uid']),
                       'source_slot': int(text), **timing_binding(self.app, self.handler)}

    def capture_query(self, actor, binding):
        source = self.source(actor)
        if str(source['uid']) != binding['source_uid']:
            raise ValueError('账号B已变更，请重新查询')
        if binding['source_uid'] == binding['actor_uid'] and binding['source_slot'] == binding['actor_slot']:
            raise ValueError('小存档B必须与出战存档A不同')
        return actor, source

    def perform_query(self, payload, binding):
        from arena_borrow import query_list
        actor, source = payload
        return query_list(actor, binding['actor_slot'], source, binding['source_slot'], self.handler,
                          progress=lambda message: self.app.root.after(0, self.log, message))

    def accept_result(self, revision, binding, result):
        if revision != self.state.revision:
            return
        self.state.result = dict(binding, **result)
        self.state.approved = None
        self.data = result

    def query_completed(self, result):
        self.log('查询完成：核对成功%d人，跳过%d人。' % (len(result['targets']), len(result.get('skipped') or [])))
        self.log('出战A：' + result['actor_summary'] + '；实际ID ' + result['actor_rid'])
        self.log('来源B：' + result['source_summary'] + '；实际ID ' + result['source_rid'])
        for index, target in enumerate(result['targets'], 1):
            self.log('C%d：%s（%s）\n%s' % (index, target['name'], target['rid'], target['summary']))
        for skipped in result.get('skipped') or []:
            self.log('跳过 %s：%s' % (skipped['rid'], skipped['reason']))
        self.log('尚未确认，不会挑战。核对名单后点击“确认使用此列表”，再点击任务开始按钮。')

    def confirmation_summary(self):
        data = self.data
        lines = ['出战A：' + data['actor_summary'], '列表来源B：' + data['source_summary'], '确认挑战以下对手：']
        lines.extend('%d. %s（%s）' % (i, target['name'], target['rid'])
                     for i, target in enumerate(data['targets'], 1))
        lines.append('A按名单顺序循环，B不消耗次数。')
        return '\n'.join(lines)

    def describe(self, data):
        lines = ['出战A：' + data['actor_summary'], '列表来源B：' + data['source_summary']]
        for index, target in enumerate(data['targets'], 1):
            summary = target['summary'].splitlines()
            roles = '；'.join(summary[2:])
            lines.append('%d. %s（%s） %s' % (index, target['name'], target['rid'], roles))
        if data.get('skipped'):
            lines.append('已跳过%d个无法核对、重复或自身目标。' % len(data['skipped']))
        lines.append('确认后由A按上述顺序循环挑战；B不消耗次数。')
        return '\n'.join(lines)
