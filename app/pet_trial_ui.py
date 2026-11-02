"""灵宠试炼路由工具页。"""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
ROOT = Path(__file__).resolve().parent

def reference_rows(directory):
    def read(name):
        return json.loads((directory / (name + '.json')).read_text(encoding='utf-8-sig'))
    layers, stages, rewards = read('PetChallengeLayer'), read('PetChallengDungeon'), read('Reward')
    rows = []
    for key, layer in sorted(layers.items(), key=lambda pair:int(pair[0])):
        values = []
        for sid in range(int(layer['startId']), int(layer['passId']) + 1):
            reward = rewards[str(stages[str(sid)]['rewardId'])]
            coins = dict(zip(str(reward['subType']).split(','), map(int, str(reward['count']).split(','))))
            if reward['type'] != 'coin':raise ValueError('奖励类型已变化，请核对配置')
            values.append((coins.get('trialStone', 0), coins.get('lingyu', 0)))
        if len(values) != 6 or len(set(values)) != 1:raise ValueError('同周天奖励存在差异，请逐关核对配置')
        rows.append((int(key), format(int(layer['powerLimit']), ','), format(values[0][0], ','), values[0][1]))
    return rows

class PetTrialPage:
    def __init__(self, app, notebook):
        self.app = app
        self.buttons = []
        self.page = ttk.Frame(notebook, padding=12)
        notebook.add(self.page, text='灵宠试炼')
        ttk.Label(self.page, text='灵宠试炼／周天', font=('', 13, 'bold')).pack(anchor='w', pady=6)
        ttk.Label(self.page, text='查询当前周天、阵容实体ID、六关状态、试炼石、免费重置次数和切层冷却。通关只补当前未通过的关卡，沿用游戏现有阵容。', wraplength=900).pack(anchor='w', pady=6)
        ttk.Label(self.page, text='前进前必须六关全通，战力及等级由服务器校验；后退将触发24小时切层冷却。重置仅允许今日剩余免费次数。', wraplength=900).pack(anchor='w', pady=6)
        ttk.Button(self.page, text='周天战力／每关奖励', command=self.show_reference).pack(anchor='w', pady=4)
        row = ttk.Frame(self.page)
        row.pack(anchor='w', pady=8)
        ttk.Label(row, text='每关开局至结算等待（秒）：').pack(side='left')
        self.wait = tk.StringVar(value='2')
        ttk.Entry(row, textvariable=self.wait, width=8).pack(side='left')
        for title, action in [('查询状态', 'status'), ('通关当前六关', 'clear'), ('前往下一周天', 'next'), ('仅免费重置当前周天', 'reset'), ('返回上一周天', 'previous')]:
            button = ttk.Button(self.page, text=title, command=lambda a=action: self.start(a))
            button.pack(anchor='w', pady=4)
            self.buttons.append(button)
        ttk.Label(self.page, text='每项操作独立执行，不自动前进、后退或重置。详细状态、服务器错误和原始记录路径显示在日志中。', wraplength=900).pack(anchor='w', pady=10)

    def show_reference(self):
        try:
            rows = reference_rows(ROOT / 'cg_config_out_cg1_20261019_1')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror('读取配置失败', str(exc), parent=self.page)
            return
        window = tk.Toplevel(self.page)
        window.title('周天战力／每关奖励')
        ttk.Label(window, text='同周天六关奖励相同；合计按通关六关计算，不含重置后的第二轮。').pack(anchor='w', padx=12, pady=8)
        table = ttk.Treeview(window, columns=('layer','power','beans','jade'), show='headings', height=21)
        for key, title, width in [('layer','周天',75),('power','战力限制',130),('beans','每小关奖励',230),('jade','六关合计',230)]:
            table.heading(key, text=title)
            table.column(key, width=width, anchor='center')
        for layer, power, beans, jade in rows:
            bean_count = int(beans.replace(',', ''))
            single = f'妖灵豆 {bean_count:,}；妖灵玉 {jade}'
            total = f'妖灵豆 {bean_count * 6:,}；妖灵玉 {jade * 6}'
            table.insert('', 'end', values=(layer, power, single, total))
        table.pack(fill='both', expand=True, padx=12, pady=(0,12))

    def start(self, action):
        if self.app.running or not self.app._save_selected_slot():
            return
        try:
            wait = float(self.wait.get())
            if not 0 <= wait <= 3600:
                raise ValueError('等待时间须为0～3600秒')
            if action in ('previous', 'reset'):
                text = '返回上一周天后，24小时内不能前进或后退。确认返回？' if action == 'previous' else '仅在今日有免费次数时重置当前周天，不付费、不自动再打。确认重置？'
                if not messagebox.askyesno('灵宠试炼', text, parent=self.page):
                    return
            self.app._launch([str(ROOT / 'pet_trial_tool.py'), '--action', action, '--wait', str(wait)])
        except ValueError as exc:
            messagebox.showerror('未执行', str(exc), parent=self.page)
