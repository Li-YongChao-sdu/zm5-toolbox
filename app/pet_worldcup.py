"""擂台名单、预测输入及用户确认后的竞猜；不提交比赛结算。"""
import json
import copy
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

PREFIX = 'scene.petWorldCupHandler.'


def snapshot_enabled(flags=(False, False, False)):
    """只有110额外读取观战快照；不使用本地时间决定阵容是否显示。"""
    return tuple(flags) == (True, True, False)


def export_allowed(match, use_snapshot=False):
    """普通模式只在名单接口已公开双方三宠时允许读取导出快照。"""
    if use_snapshot:return True
    users=match.get('users') or []
    return len(users)==2 and all(len((u.get('data') or {}).get('pets') or [])==3 for u in users)


def lineup_values(match, use_snapshot=False):
    teams = match.get('display_teams') if use_snapshot else None
    pets = ([p for team in teams for p in team['pets']] if teams else
            [p for u in match['users'] for p in (u.get('data', {}).get('pets') or
             [{'name': '当前已隐藏', 'fightPower': '未下发'}] * 3)])
    return [f"{p.get('name', '未知')} / {p.get('fightPower', '未知')}" for p in pets]


def read_lineups(flow, final, area, use_snapshot=False, still_enabled=None):
    config = check(flow.request(PREFIX + 'getWorldCupConfig', {}))
    reply = check(flow.request(PREFIX + ('getPetWorldCupData' if final else 'getPetWorldCupAreaData'), {} if final else {'area': area}))
    rows = matches(reply, final=final)
    if use_snapshot:
        for i, match in enumerate(rows):
            if still_enabled is not None and not still_enabled():
                break
            try:
                _, teams = read_snapshot(flow, match)
                match['display_teams'] = teams
            except Exception as exc:
                match['read_error'] = str(exc)
            if i + 1 < len(rows):
                time.sleep(1)
    return config, reply, rows


def read_snapshot(flow, match):
    route = 'beginPetWorldCupBattle' if match['isFinal'] else 'beginPetWorldCupAreaBattle'
    raw = check(flow.request(PREFIX + route, {k: match[k] for k in ('group', 'area', 'groupId')}))
    teams = [json.loads(v) if isinstance(v, str) else v for v in raw.get('data') or []]
    if len(teams) != 2 or any(len(t.get('pets') or []) != 3 for t in teams):
        raise RuntimeError('详细快照缺少双方六宠')
    if [t.get('rid') for t in teams] != [u['rid'] for u in match['users']]:
        raise RuntimeError('详细快照选手与名单不一致，请刷新')
    return raw, teams


def submit_guess(flow, match, side, period):
    if side not in (0, 1):
        raise ValueError('请选择主场或客场')
    config = check(flow.request(PREFIX + 'getWorldCupConfig', {}))
    phase = 1 if match['isFinal'] else 0
    if (config['data']['id'] != period or config['data']['area'] != phase
            or config['data']['group'] != match['group']):
        raise RuntimeError('擂台期数或轮次已变化，请重新读取名单')
    key = f"{phase}_{match['group']}"
    if (config.get('petWorldCupData', {}).get('guess') or {}).get(key):
        raise RuntimeError('本阶段本轮已经竞猜，不能重复提交')
    route = 'getPetWorldCupData' if match['isFinal'] else 'getPetWorldCupAreaData'
    current = check(flow.request(PREFIX + route, {} if match['isFinal'] else {'area': match['area']}))
    if current.get('group') != match['group']:
        raise RuntimeError('对阵轮次已变化，请重新读取名单')
    rid = match['users'][side]['rid']
    users = current['data'][match['group']].get('users') or []
    if not any(u.get('rid') == rid for u in users):
        raise RuntimeError('所选选手已不在当前名单')
    reply = check(flow.request(PREFIX + 'guessChampion',
                               {'rid': rid, 'select': 0 if match['isFinal'] else int(match['area'])}))
    if (reply.get('guess') or {}).get(key) != rid:
        # 不自动重试，避免响应不完整时重复提交。
        verified = check(flow.request(PREFIX + 'getWorldCupConfig', {}))
        if (verified.get('petWorldCupData', {}).get('guess') or {}).get(key) != rid:
            raise RuntimeError('已提交但无法核实竞猜记录，请在游戏内确认；不要重复提交')
    return rid


def check(reply):
    if not isinstance(reply, dict) or reply.get('code') != 200:
        raise RuntimeError(str(reply.get('error', '接口返回失败')) if isinstance(reply, dict) else '无效响应')
    return reply


def matches(reply, final=None):
    check(reply)
    is_final = bool(reply.get('isFinal')) if final is None else bool(final)
    area = reply.get('area', 0) if is_final else reply.get('area')
    if area is None:
        raise ValueError('分擂台名单缺少area分区字段，请重新读取')
    group = int(reply['group'])
    rounds = reply['data']
    if not 0 <= group < min(len(rounds), 4):
        return []
    users = rounds[group].get('users') or []
    count = (16, 8, 4, 2)[group]
    if len(users) != count:
        return []
    result = []
    for left in range(count // 2):
        right = count - left - 1
        pair = [users[left], users[right]]
        if any(not u.get('rid') for u in pair):
            continue
        result.append({'group': group, 'area': area,
                       'groupId': f'{group}_{left}_{right}',
                       'isFinal': is_final, 'users': pair,
                       'battle': rounds[group].get('battle', {}).get(f'{group}_{left}_{right}')})
    return result


def export_inputs(raw, match, folder, count=3):
    check(raw)
    count = int(count)
    if not 3 <= count <= 1000:
        raise ValueError('随机种子数量须为3～1000')
    users = [json.loads(x) if isinstance(x, str) else x for x in raw['data']]
    if len(users) != 2 or any(len(u.get('pets', [])) != 3 for u in users):
        raise ValueError('服务端未返回双方各三只宠物')
    if [u['rid'] for u in users] != [u['rid'] for u in match['users']]:
        raise ValueError('快照选手与所选对局不一致，请重新读取名单')
    ids = [p['entityId'] for u in users for p in u['pets']]
    if len(set(ids)) != 6:
        raise ValueError('宠物实体重复')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / '服务端原始快照.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
    # 仅修改模拟输入的展示名，原始快照和身份核对保持原样。
    users = copy.deepcopy(users)
    for side, user in enumerate(users):
        label = ('主场', '客场')[side]
        user['name'] = label
        for key in ('userName', 'username'):
            if key in user:
                user[key] = label
        for pet in user['pets']:
            pet['userName'] = label
            if 'username' in pet:
                pet['username'] = label
    # 原版随机递推模1000，选不同余数避免等价种子。
    seeds = secrets.SystemRandom().sample(range(1000), count)
    files = []
    battle = match.get('battle') or {}
    if isinstance(battle, list):
        battle = battle[0] if battle else {}
    raw_message = raw.get('message') or {}
    cg = raw_message.get('cg') or (battle.get('cg', '') if isinstance(battle, dict) else '')
    for seed in seeds:
        response = dict(raw, data=[json.dumps(u, ensure_ascii=False) for u in users],
                        message=dict(raw_message, randomSeed=seed, cg=cg), see=True)
        obj = {'format': 'zm5-local-replay-input-v1',
               'metadata': {'area': match['area'], 'groupId': match['groupId'],
                            'isFinal': match['isFinal'], 'battle': {'rnd': seed, 'cg': cg}},
               'response': response,
               'experiment': {'seedSource': 'local_random_not_official',
                              'statsBasis': 'raw_server_snapshot_native_calculation',
                              'orderBasis': 'game_formation', 'flashExecutionTested': False}}
        path = folder / f'预测检测_种子{seed}.json'
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
        files.append(path)
    (folder / '种子清单.json').write_text(json.dumps({'match': match, 'seeds': seeds}, ensure_ascii=False, indent=2), encoding='utf-8')
    return files


def export_standard_inputs(files):
    from arena_seed_to_build import convert, catalog, LAB, HERE, TABLES
    cat = catalog(LAB / 'ui' / 'catalog.mjs')
    outputs = []
    # 全部转换完成后才写入，避免部分成功被误认为完整导出。
    converted = []
    for source in files:
        obj = json.loads(Path(source).read_text(encoding='utf-8-sig'))
        cg = obj.get('response', {}).get('message', {}).get('cg') or obj.get('metadata', {}).get('battle', {}).get('cg', '')
        name = 'cg_config_out_' + Path(cg).stem
        config = next((p for p in (HERE / name, Path.home() / 'Downloads' / name)
                       if cg and all((p / (table + '.json')).is_file() for table in TABLES)), None)
        config_basis = 'snapshot_version'
        if config is None and not cg:
            candidates = [p for p in HERE.glob('cg_config_out_cg1_*')
                          if all((p / (table + '.json')).is_file() for table in TABLES)]
            config = max(candidates, key=lambda p: p.name) if candidates else None
            config_basis = 'latest_local_fallback_version_not_supplied'
        if config is None and obj.get('finalPanels'):
            config = HERE / 'cg_config_out_cg1_20261008_1'
            config_basis = 'provided_final_panels'
        if config is None:
            raise ValueError(f'找不到快照对应的完整配置 {cg or "（版本未下发）"}，无法安全转换标准版；原始JSON已保留')
        result = convert(obj, cat, config)
        result['names'] = ['主场', '客场']
        result['conversionMetadata'] = {'config': config.name, 'basis': config_basis,
                                        'snapshotCg': cg, 'warning': '服务器未下发配置版本，使用随包最新本地配置计算；不保证与服务器当前配置完全一致' if config_basis.startswith('latest_local') else ''}
        converted.append((Path(source).with_name(Path(source).stem + '_标准配队.json'), result))
    for target, result in converted:
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        outputs.append(target)
    return outputs


class WorldCupPage:
    def __init__(self, app, notebook, account_file, output_root):
        self.app, self.account_file, self.output_root = app, account_file, Path(output_root)
        self.rows = []
        self.config = None
        self.busy = False
        page = ttk.Frame(notebook, padding=10)
        notebook.add(page, text='擂台竞猜')
        bar = ttk.Frame(page)
        bar.pack(fill=tk.X)
        self.stage = tk.StringVar(value='分擂台')
        ttk.Combobox(bar, textvariable=self.stage, values=['分擂台', '总擂台'], state='readonly', width=9).pack(side=tk.LEFT)
        self.area = tk.StringVar(value='1')
        ttk.Label(bar, text='分区').pack(side=tk.LEFT, padx=(10, 2))
        self.area_box = ttk.Combobox(bar, textvariable=self.area, values=[str(i) for i in range(1, 17)], state='readonly', width=4)
        self.area_box.pack(side=tk.LEFT)
        self.stage.trace_add('write', lambda *_: self.area_box.configure(state='readonly' if self.stage.get() == '分擂台' else 'disabled'))
        self.refresh = ttk.Button(bar, text='读取/刷新阵容', command=self.load)
        self.refresh.pack(side=tk.LEFT, padx=8)
        self.count = tk.IntVar(value=3)
        ttk.Label(bar, text='随机种子数（至少3）').pack(side=tk.LEFT)
        ttk.Spinbox(bar, from_=3, to=1000, textvariable=self.count, width=5).pack(side=tk.LEFT, padx=4)
        self.detect = ttk.Button(bar, text='预测检测：导出JSON', command=self.export, state='disabled')
        self.detect.pack(side=tk.LEFT, padx=4)
        self.standard = ttk.Button(bar, text='导出标准版JSON（可改宠物/真灵）', command=lambda: self.export(standard=True), state='disabled')
        self.standard.pack(side=tk.LEFT, padx=4)
        visibility_bar = ttk.Frame(page)
        visibility_bar.pack(fill=tk.X, pady=(8, 0))
        self.visibility_flags = [tk.BooleanVar(value=False) for _ in range(3)]
        for variable in self.visibility_flags:
            ttk.Checkbutton(visibility_bar, variable=variable,
                            command=self.change_read_mode).pack(side=tk.LEFT, padx=(0, 8))
        guess_bar = ttk.Frame(page)
        guess_bar.pack(fill=tk.X, pady=(8, 0))
        self.guess_side = tk.IntVar(value=0)
        ttk.Radiobutton(guess_bar, text='竞猜主场选手', variable=self.guess_side, value=0).pack(side=tk.LEFT)
        ttk.Radiobutton(guess_bar, text='竞猜客场选手', variable=self.guess_side, value=1).pack(side=tk.LEFT, padx=8)
        self.guess_button = ttk.Button(guess_bar, text='提交竞猜', command=self.guess, state='disabled')
        self.guess_button.pack(side=tk.LEFT, padx=8)
        self.guess_status = tk.StringVar(value='竞猜机会按账号共享，同一阶段本轮仅一次；换存档不能重复竞猜。')
        ttk.Label(guess_bar, textvariable=self.guess_status).pack(side=tk.LEFT, padx=4)
        ttk.Label(page, text='竞猜次数按账号共享：同一账号在同一阶段本轮只能竞猜一次，切换存档不能再次竞猜。',
                  foreground='gray', wraplength=850).pack(fill=tk.X, pady=(4, 0))
        self.status = tk.StringVar(value='使用上方登录账号和存档。选中一场对局后导出，胜负需在训练室实际运行。')
        ttk.Label(page, textvariable=self.status, wraplength=850).pack(fill=tk.X, pady=8)
        columns = ('left1', 'left2', 'left3', 'right1', 'right2', 'right3')
        box = ttk.Frame(page)
        box.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(box, columns=columns, show='headings', selectmode='browse')
        for index, col in enumerate(columns):
            self.tree.heading(col, text=('主场' if index < 3 else '客场') + f'宠物{index % 3 + 1} / 战力')
            self.tree.column(col, width=155, minwidth=120)
        y = ttk.Scrollbar(box, orient=tk.VERTICAL, command=self.tree.yview)
        x = ttk.Scrollbar(box, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        y.pack(side=tk.RIGHT, fill=tk.Y)
        x.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(fill=tk.BOTH, expand=True)
        ttk.Label(page, text='预测检测只读取快照；竞猜须另行选择主场/客场并点击提交，不提交比赛结算。JSON保留装备、真灵、性格、技能等分项，由训练室原版引擎计算；随机种子不是官方种子。', wraplength=850, foreground='gray').pack(fill=tk.X, pady=8)
        help_box = ttk.LabelFrame(page, text='宠物模拟训练室使用说明', padding=8)
        help_box.pack(fill=tk.X)
        ttk.Label(help_box, justify=tk.LEFT, wraplength=850, text=(
            '1. 准备宠物对战研究室SWF及Fiddler（或同类请求转发工具），游戏客户端版本须与研究室SWF匹配。\n'
            '2. 在Fiddler AutoResponder中启用规则，将游戏实际请求的主SWF地址精确转发到本地研究室SWF；不要替换配置SWF。'
            'HTTPS请求需能被Fiddler正常捕获。\n'
            '3. 刷新游戏，登录并回到城镇，展开“研究室”，导入本页生成的一个“预测检测_种子*.json”。'
            '这是对战输入，不是手动配队方案；网页版编辑器请使用真实回放导入入口。\n'
            '4. 逐一运行至少3个种子，完成战斗后保存事件/胜负记录，再到研究室“试验结果”导入分析。'
            '只导出JSON不会自动产生预测胜负。\n'
            '5. 没有官方配置路径时沿用游戏当前加载配置；这些随机种子只用于本地试战，不代表官方比赛种子或结果。'
            '停用转发规则并刷新游戏，即可恢复原版客户端。'
        )).pack(fill=tk.X)
        self.selected_snapshot_mode = self.is_snapshot_mode()

    def is_snapshot_mode(self):
        return snapshot_enabled(tuple(v.get() for v in self.visibility_flags))

    def apply_visibility(self):
        advanced = self.is_snapshot_mode()
        for i, match in enumerate(self.rows):
            self.tree.item(str(i), values=lineup_values(match, advanced))
        self.detect.configure(state='normal' if any(export_allowed(m, advanced) for m in self.rows) and not self.busy else 'disabled')
        self.standard.configure(state='normal' if any(export_allowed(m, advanced) for m in self.rows) and not self.busy else 'disabled')

    def change_read_mode(self):
        advanced = self.is_snapshot_mode()
        changed = advanced != self.selected_snapshot_mode
        self.selected_snapshot_mode = advanced
        self.apply_visibility()
        if changed and self.rows and not self.busy and not self.app.running:
            self.load()

    def run(self, operation, done):
        if self.busy or self.app.running:
            messagebox.showinfo('擂台竞猜', '请等待当前操作结束')
            return
        try:
            account = json.loads(Path(self.account_file).read_text(encoding='utf-8'))
            slot = int(self.app.cmb_slot.get())
        except Exception:
            messagebox.showerror('擂台竞猜', '请先登录并选择存档')
            return
        self.busy = True
        self.app.running = True
        self.refresh.configure(state='disabled')
        self.detect.configure(state='disabled')
        self.standard.configure(state='disabled')
        self.guess_button.configure(state='disabled')
        self.status.set('正在读取服务器数据…')
        def worker():
            flow = None
            try:
                from teacher_trial import connect
                flow, _ = connect(account, slot)
                value = operation(flow)
                self.app.root.after(0, lambda: finish(value, None))
            except Exception as exc:
                self.app.root.after(0, lambda msg=str(exc): finish(None, msg))
            finally:
                if flow is not None:
                    flow.disconnect()
        def finish(value, error):
            self.busy = False
            self.app.running = False
            self.refresh.configure(state='normal')
            self.detect.configure(state='normal' if any(export_allowed(m,self.is_snapshot_mode()) for m in self.rows) else 'disabled')
            self.standard.configure(state='normal' if any(export_allowed(m,self.is_snapshot_mode()) for m in self.rows) else 'disabled')
            self.update_guess_state()
            if error:
                self.status.set('操作失败：' + error)
                self.app._append_log('[擂台竞猜] ' + error)
            else:
                done(value)
        threading.Thread(target=worker, daemon=True).start()

    def load(self):
        final = self.stage.get() == '总擂台'
        area = 0 if final else int(self.area.get()) - 1
        use_snapshot = self.is_snapshot_mode()
        def operation(flow):
            return read_lineups(flow, final, area, use_snapshot,
                                lambda: self.selected_snapshot_mode)
        def done(value):
            config, reply, rows = value
            self.config = config
            self.rows = rows
            self.tree.delete(*self.tree.get_children())
            for i, match in enumerate(self.rows):
                self.tree.insert('', 'end', iid=str(i), values=lineup_values(match, self.is_snapshot_mode()))
                if match.get('read_error'):
                    self.app._append_log('[擂台阵容] %s：%s' % (match['groupId'], match['read_error']))
            self.apply_visibility()
            loaded = sum('display_teams' in m for m in self.rows)
            mode = f'观战快照已读取{loaded}/{len(self.rows)}场' if use_snapshot else '已读取名单接口；缺失宠物显示未下发'
            self.status.set(f"第{config['data']['id']}期 · 当前轮次{reply['group']} · {mode}（{datetime.now():%H:%M:%S}）。")
            self.update_guess_state()
            if use_snapshot != self.is_snapshot_mode():
                self.app.root.after(0, self.load)
        self.run(operation, done)

    def update_guess_state(self):
        enabled = bool(self.rows and self.config and not self.busy)
        if self.config:
            phase = self.config['data']['area']
            group = self.config['data']['group']
            rid = (self.config.get('petWorldCupData', {}).get('guess') or {}).get(f'{phase}_{group}')
            self.guess_status.set(f'本账号本轮已竞猜：{rid}' if rid else '本账号本阶段本轮仅一次，换存档不能重复竞猜。')
            enabled = enabled and not rid and any(int(m['isFinal']) == phase and m['group'] == group for m in self.rows)
        self.guess_button.configure(state='normal' if enabled else 'disabled')

    def guess(self):
        selected = self.tree.selection()
        if not selected or not self.config:
            messagebox.showinfo('擂台竞猜', '请读取名单并选中一场对局')
            return
        match = self.rows[int(selected[0])]
        side = self.guess_side.get()
        user = match['users'][side]
        name = user.get('data', {}).get('name') or user['rid']
        period = self.config['data']['id']
        if not messagebox.askyesno('确认提交竞猜',
                f"第{period}期 · 第{match['group']}轮\n对局 {match['groupId']}\n"
                f"选择{'主场' if side == 0 else '客场'}选手：{name}\n"
                '这是实际竞猜；机会按账号共享，同一阶段本轮仅一次，换存档不能重复竞猜。确认提交？'):
            return
        def operation(flow):
            rid = submit_guess(flow, match, side, period)
            config = check(flow.request(PREFIX + 'getWorldCupConfig', {}))
            return rid, config
        def done(value):
            rid, self.config = value
            self.update_guess_state()
            self.status.set(f'竞猜记录已核实：{name}（{rid}）')
            self.app._append_log(f'[擂台竞猜] 已提交并核实：{name}（{rid}）')
        self.run(operation, done)

    def export(self, standard=False):
        try:
            selected = self.tree.selection()
            if not selected:
                raise ValueError('请先选中一场对局')
            count = self.count.get()
            if not 3 <= count <= 1000:
                raise ValueError('随机种子数量须为3～1000')
            match = self.rows[int(selected[0])]
            if not export_allowed(match,self.is_snapshot_mode()):
                raise ValueError('服务器名单尚未公开本场双方宠物，当前模式无法导出；公开后请刷新名单')
        except Exception as exc:
            messagebox.showerror('擂台竞猜', str(exc))
            return
        def operation(flow):
            raw, teams = read_snapshot(flow, match)
            folder = self.output_root / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            files = export_inputs(raw, match, folder, count)
            if standard:
                files = export_standard_inputs(files)
            return files, folder, teams
        def done(value):
            files, folder, teams = value
            match['display_teams'] = teams
            self.apply_visibility()
            if standard:
                notes = [json.loads(p.read_text(encoding='utf-8')).get('conversionMetadata', {}).get('warning') for p in files]
                if any(notes):
                    self.app._append_log('[标准版导出] '+next(n for n in notes if n))
            self.status.set(f'已生成{len(files)}个'+('标准配队JSON（可修改宠物/真灵）' if standard else '随机种子JSON')+f'：{folder}')
            self.app._append_log(f'[擂台预测检测] 已导出{len(files)}份：{folder}；尚未运行战斗，无胜负预测值。')
            os_open(folder)
        self.run(operation, done)


def os_open(folder):
    import os
    try:
        os.startfile(str(folder))
    except OSError:
        pass
