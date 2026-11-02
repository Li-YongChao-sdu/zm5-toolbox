"""万能强化石独立工具页。"""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
ROOT = Path(__file__).resolve().parent

class EliteStonePage:
    def __init__(self, app, notebook=None, parent=None):
        self.app = app
        self.buttons = []
        if parent is None:
            self.page = ttk.Frame(notebook, padding=12)
            notebook.add(self.page, text='万能强化石')
        else:
            self.page = ttk.LabelFrame(parent, text='万能强化石 · 每日补齐4个', padding=12)
            self.page.pack(fill='x', padx=4, pady=6)
        ttk.Label(self.page, text='每日4个万能强化石', font=('', 13, 'bold')).pack(anchor='w', pady=6)
        ttk.Label(self.page, text='批量执行时先完成所选精英关卡，再按服务器今日已获取数量补齐4个。与精英关卡共用每关每日2次免费次数，已用次数不会重复计算；手动执行也会重新读取状态。', wraplength=850).pack(anchor='w', pady=6)
        ttk.Label(self.page, text='所有场景掉落均不拾取，只通关后免费翻牌。保留强化石；结算和翻牌新增的非强化石可售道具自动卖出，旧库存保留。背包满或出售失败时停止。', wraplength=850).pack(anchor='w', pady=6)
        row = ttk.Frame(self.page)
        row.pack(anchor='w', pady=8)
        ttk.Label(row, text='每场等待（秒）：').pack(side='left')
        self.wait = tk.StringVar(value='25')
        ttk.Entry(row, textvariable=self.wait, width=8).pack(side='left')
        ttk.Label(row, text='出售二级密码（如有）：').pack(side='left', padx=(15, 0))
        self.password = tk.StringVar()
        ttk.Entry(row, textvariable=self.password, show='*', width=18).pack(side='left')
        for title, query in [('查询今日数量', True), ('开始获取4个', False)]:
            button = ttk.Button(self.page, text=title, command=lambda q=query: self.start(q))
            button.pack(anchor='w', pady=4)
            self.buttons.append(button)
        ttk.Label(self.page, text='执行进度和出售结果显示在下方日志。', wraplength=850).pack(anchor='w', pady=10)

    def start(self, query):
        if self.app.running or not self.app._save_selected_slot():
            return
        try:
            wait = float(self.wait.get())
            if not 0 <= wait <= 3600:
                raise ValueError('每场等待须为0～3600秒')
            args = [str(ROOT / 'elite_stone_tool.py')]
            if query:
                args.append('--status')
            else:
                args += ['--wait', str(wait)]
            password = self.password.get()
            self.password.set('')
            self.app._launch(args, extra_env={'ZM5_STONE_SELL_PASSWORD': password})
        except ValueError as exc:
            messagebox.showerror('未执行', str(exc), parent=self.page)
