"""扩展功能的工具箱界面。所有操作复用主窗口的账号与进程管理。"""

import os

import tkinter as tk

from tkinter import ttk, messagebox



def attach(app, notebook, pages):

    app.feature_buttons = []

    app.ui_settings_fields = {}

    app.ui_confirmation_vars = []
    app.ui_settings_fields['迷宫/结算等待秒数']=(app.maze_target_controls.wait,None)
    app.ui_settings_fields['通天河/发船策略']=(app.var_ttr_escort_strategy,list(app.ttr_escort_strategies.values()))
    app.ui_settings_fields['通天河/仅抢满额奖励目标']=(app.var_ttr_full_reward,None)
    app.ui_settings_fields['神兽森林/扫荡前按需使用1个水晶']=(app.var_forest_auto_crystal,None)

    def page(title):

        target = (app.backup_function_notebook if title in ('抓宠', '联盟仓库') else

                  app.fun_activity_notebook if title in ('幻兽喂养','幻兽派遣') else notebook)

        outer = ttk.Frame(target)

        target.add(outer, text=title)

        if title == '抓宠':app.pet_capture_page = outer

        if title == '联盟仓库':app.union_warehouse_page = outer

        if title == '幻兽派遣':app.fairy_dispatch_page = outer

        canvas = tk.Canvas(outer, highlightthickness=0)

        bar = ttk.Scrollbar(outer, command=canvas.yview)

        canvas.configure(yscrollcommand=bar.set)

        bar.pack(side=tk.RIGHT, fill=tk.Y)

        canvas.pack(fill=tk.BOTH, expand=True)

        body = ttk.Frame(canvas, padding=8)

        window = canvas.create_window(0, 0, window=body, anchor='nw')

        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))

        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))

        canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta/120), 'units'))

        return body

    def frame(parent, title, hint):

        box = ttk.LabelFrame(parent, text=title, padding=6)

        box.pack(fill=tk.X, pady=5)

        ttk.Label(box, text=hint, wraplength=650).pack(anchor='w')

        return box

    def field(box, label, default='', choices=None, secret=False):

        row = ttk.Frame(box)

        row.pack(fill=tk.X, pady=2)

        ttk.Label(row, text=label, width=23).pack(side=tk.LEFT)

        var = tk.StringVar(value=default)

        widget = (ttk.Combobox(row, textvariable=var, values=choices, state='readonly', width=27)

                  if choices else ttk.Entry(row, textvariable=var, width=30, show='*' if secret else ''))

        widget.pack(side=tk.LEFT)

        if not secret:

            group=str(box.cget('text'))

            key=group+'/'+label

            if key in app.ui_settings_fields:key+=' #'+str(len(app.ui_settings_fields))

            app.ui_settings_fields[key]=(var,choices)

        return var

    def button(box, title, script, args):

        def run():

            if app.running:

                return

            try:

                argv = args()

            except (ValueError, TypeError) as exc:

                messagebox.showerror(title, str(exc))

                return

            if app._save_selected_slot():

                app._launch([os.path.join(os.path.dirname(__file__), script)] + argv)

        b = ttk.Button(box, text=title, command=run)

        b.pack(anchor='w', pady=3)

        app.feature_buttons.append(b)

    def positive(var):

        n = int(var.get())

        if n < 1:

            raise ValueError('次数必须为正整数')

        return str(n)



    box = frame(pages['日常任务2'], '月卡奖励', '领取已生效月卡奖励，不购买月卡。')

    scope = field(box, '领取范围', '当前存档', ['当前存档', '所有存档'])

    button(box, '查看月卡状态', 'monthcard_run.py', lambda: ['--all-slots'] if scope.get() == '所有存档' else [])

    button(box, '领取月卡奖励', 'monthcard_run.py', lambda: ['--apply'] + (['--all-slots'] if scope.get() == '所有存档' else []))

    box = frame(pages['日常任务1'], '善法堂', '给榜首赠送爱心，执行一次免费点赞；自动检查今日剩余次数。')

    button(box, '查看点赞状态', 'shanfa_run.py', lambda: [])

    button(box, '免费点赞一次', 'shanfa_run.py', lambda: ['--apply'])



    body = page('联盟仓库')

    box = frame(body, '联盟仓库 · 余额与库存', '先点刷新查看当前存档的蛮荒魂石、魂玉及联盟仓库材料。')

    app.union_summary = tk.StringVar(value='尚未读取仓库状态')

    ttk.Label(box,textvariable=app.union_summary,wraplength=680).pack(anchor='w',pady=4)

    app.union_stock = tk.Text(box,height=12,width=82,state=tk.DISABLED)

    app.union_stock.pack(fill=tk.X,pady=4)

    button(box,'刷新联盟仓库','union_warehouse.py',lambda: ['--action','status'])

    shop = frame(body,'购买蛮荒材料','购买前检查余额、库存与次数；仅在魂石／魂玉不足且已开启自动补足时，售出选中的背包材料。')

    import union_warehouse as uw

    entries = {('%s（%d）'%(row['name'],item_id)):item_id for item_id,row in sorted(uw.catalog().items())}

    item = field(shop,'材料',next(iter(entries)),list(entries))

    number = field(shop,'数量','1')

    pay = field(shop,'购买方式','蛮荒魂石/魂玉',['蛮荒魂石/魂玉','联盟贡献'])

    app.union_pay_var = pay

    auto_fund = tk.BooleanVar(value=False)

    app.union_auto_fund_var = auto_fund

    tk.Checkbutton(shop,text='魂石／魂玉不足时，自动售出下方选中材料补足',variable=auto_fund).pack(anchor='w',pady=3)

    from union_funding_ui import FundingChoices
    app.union_funding_choices = FundingChoices(app,shop,uw.catalog())
    ttk.Label(shop,text='按勾选材料的列表顺序补足；只用兑换货币匹配的材料，跳过本次购买材料。先检查总量是否足够，凑够即停，不使用贡献或点券。',wraplength=650).pack(anchor='w',pady=3)
    warehouse_password = field(shop,'二级密码（未设置可留空）',secret=True)

    def args(action):

        result = ['--action',action,'--item',str(entries[item.get()]),'--count',positive(number)]

        if action == 'buy':

            result += ['--pay','contribution' if pay.get()=='联盟贡献' else 'material']

            if auto_fund.get() and pay.get()=='蛮荒魂石/魂玉':

                donor_ids=app.union_funding_choices.value()
                if not donor_ids:raise ValueError('请先勾选自动售出的蛮荒材料')
                for donor_id in donor_ids:result += ['--auto-fund',str(donor_id)]
        result += ['--password',warehouse_password.get()]

        return result

    button(shop,'购买选中材料','union_warehouse.py',lambda: args('buy'))

    redevote = frame(body,'联盟补贡','只补本周已过去且未贡的日期。前两次用灵魂，第3次起用补贡券；券不足时自动跑一次星斗幻境免费领奖，再用星辰石在星斗商店换券（周限3张）。全程不使用点券。')

    button(redevote,'查看本周补贡计划','union_redevote.py',lambda: ['--dry-run'])

    button(redevote,'执行补贡（缺券自动星斗兑换）','union_redevote.py',lambda: [])

    ttk.Label(redevote,text='周一00:00周重置后没有可补日期；从周二起可补第1天。执行前请确认当前账号与存档。',wraplength=650).pack(anchor='w',pady=(0,2))





    celebration = frame(pages['活动副本'],'庆典任务 · 备用补药','默认先凑止血草炼制两次。补打上限后仍不足，开启备用补药才允许用灵魂购买缺少的回元露；需要二级密码。')
    app.var_celebration_spirit_backup = tk.BooleanVar(value=False)
    ttk.Checkbutton(celebration,text='允许灵魂补药（仅作为炼制不足后的备用）',variable=app.var_celebration_spirit_backup).pack(anchor='w',pady=3)
    app.ui_settings_fields['庆典任务/允许灵魂备用补药']=(app.var_celebration_spirit_backup,None)
    app.var_celebration_password = field(celebration,'二级密码（不保存）',secret=True)

    box = frame(pages['活动副本'], '许愿池', '先查看当前格子的奖励和消耗，再填 wishId。许愿会消耗对应资源。')

    from wish_pool_ui import WishPoolPanel
    app.wish_pool_panel = WishPoolPanel(app,box)
    app.feature_buttons.extend(app.wish_pool_panel.buttons)

    body = page('幻兽派遣')

    box = frame(body, '幻兽试炼 · 派遣', '任务槽位 1～3（不是奖励优先级）。免费刷新不足时停止；自动匹配两只幻兽，副手优先非派遣主幻兽种类，并优先用满足阶数的低阶幻兽。')

    daily_scope = field(box, '日常派遣范围', '全部可派档位', ['全部可派档位', '仅选中档位'])

    daily_slot_holder = ttk.Frame(box);daily_slot_holder.pack(fill=tk.X)

    daily_slot_row = ttk.Frame(daily_slot_holder)

    ttk.Label(daily_slot_row,text='日常任务槽位',width=23).pack(side=tk.LEFT)

    daily_pos = tk.StringVar(value='1')

    ttk.Combobox(daily_slot_row,textvariable=daily_pos,values=['1','2','3'],state='readonly',width=27).pack(side=tk.LEFT)

    def update_daily_slot(*_):

        if daily_scope.get() == '仅选中档位':daily_slot_row.pack(fill=tk.X,pady=2)

        else:daily_slot_row.pack_forget()

    daily_scope.trace_add('write',update_daily_slot);update_daily_slot()

    app.var_fairy_daily_scope = daily_scope

    app.var_fairy_daily_pos = daily_pos

    app.fairy_daily_slot_row = daily_slot_row

    from fairy_preferences_ui import FairyPreferenceSettings

    app.fairy_preferences = FairyPreferenceSettings(app, box)

    def fairy_daily_args():

        import json

        positions = [0,1,2] if daily_scope.get() == '全部可派档位' else [int(daily_pos.get())-1]

        return ['--positions', json.dumps(positions), '--preferences', json.dumps(app.fairy_preferences.value(),ensure_ascii=False), '--apply']

    button(box, '预览日常派遣策略', 'fairy_daily.py', lambda: [a for a in fairy_daily_args() if a!='--apply'])

    button(box, '一键领取奖励并重新派遣', 'fairy_daily.py', fairy_daily_args)

    ttk.Label(box,text='先领取所有已完成奖励，再派遣所选范围内的空闲档位。未完成任务保留；启用偏好后仅按策略使用剩余免费刷新，不召回、不购买次数或加速。',wraplength=850).pack(anchor='w',pady=4)

    manual = ttk.LabelFrame(box,text='手动操作（与日常派遣范围独立）',padding=6);manual.pack(fill=tk.X,pady=6)

    app.fairy_manual_box = manual

    pos = field(manual, '手动操作任务槽位', '1', ['1', '2', '3'])

    app.var_fairy_manual_pos = pos

    button(manual, '查看任务、幻兽与配额', 'fairy_run.py', lambda: [])

    button(manual, '免费刷新任务', 'fairy_run.py', lambda: ['--refresh', '--apply'])

    button(manual, '派遣选中档位', 'fairy_run.py', lambda: ['--collect', '--pos', str(int(pos.get())-1), '--apply'])

    button(manual, '领取所有已完成派遣', 'fairy_run.py', lambda: ['--reward', '--apply'])

    paid = field(manual, '点券操作', '立即完成（10点券）', ['立即完成（10点券）', '提前召回（100点券）', '购买次数（100点券）', '点券刷新'])

    confirm = tk.BooleanVar()

    app.ui_confirmation_vars.append(confirm)

    tk.Checkbutton(manual, text='允许执行所选点券操作', variable=confirm, fg='red').pack(anchor='w')

    def paid_args():

        app.spend_permissions.require('cultivation')

        if not confirm.get():

            raise ValueError('请勾选本次所选操作确认')

        flags = {'立即完成（10点券）':['--complete','--pos',str(int(pos.get())-1)], '提前召回（100点券）':['--reset','--pos',str(int(pos.get())-1)], '购买次数（100点券）':['--buy'], '点券刷新':['--refresh','--ticket']}

        return flags[paid.get()] + ['--apply']

    button(manual, '执行所选点券操作', 'fairy_run.py', paid_args)

    body = page('幻兽喂养')

    box = frame(body, '幻兽喂养', '查询后从下拉列表选择幻兽，无需手输ID。灵魂喂养消耗灵魂，妖元喂养消耗妖元。')

    from fairy_feed_ui import FairyFeedPanel

    app.fairy_feed_panel = FairyFeedPanel(app, box)

    app.feature_buttons.extend(app.fairy_feed_panel.buttons)



    body = page('免费洗练')

    from wash_free_ui import build as build_free_wash
    app.free_wash_sections = build_free_wash(body, frame, field, button, app)

    body = page('抓宠')

    box = frame(body, '诸星封印 · 挑战', '建议先打福星提高掉率。默认要求福星祝福有效；勾选下方选项可无福星挑战。部分关卡消耗诸星挑战券，不自动买券。')

    seal_stages = {'御马监':10001, '御花园':10002, '阆风幽境':10003, '天马苑':10011,

                   '灵花圃':10012, '清风廊':10013, '翠竹径':10004, '幽竹谷':10014}

    seal = field(box, '关卡', '御马监', list(seal_stages))

    button(box, '查看关卡消耗与状态', 'starseal_run.py', lambda: [str(seal_stages[seal.get()])])

    app.var_starseal_allow_no_fuxing = tk.BooleanVar(value=False)
    ttk.Checkbutton(box, text='允许无福星挑战', variable=app.var_starseal_allow_no_fuxing).pack(anchor='w', pady=3)

    button(box, '挑战选中关卡一次', 'starseal_run.py', lambda: [str(seal_stages[seal.get()]), '--apply'] + (['--allow-no-fuxing'] if app.var_starseal_allow_no_fuxing.get() else []))

    ticket_count = field(box, '购买挑战券数量', '1')

    ttk.Label(box, text='每张消耗1000斗宠币，点击购买才执行。', foreground='red').pack(anchor='w')

    button(box, '购买诸星挑战券', 'starseal_ticket.py', lambda: ['--count', positive(ticket_count)])

    from pet_capture_ui import attach as attach_capture, attach_training

    attach_capture(body, frame, field, button, positive, app)

    app.attach_pet_training = lambda parent: attach_training(parent, frame, field, button, positive, app)

