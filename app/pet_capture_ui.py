"""从 Pet.json 读取天马、灵花的筛选范围。"""
import json
import os
import tkinter as tk
from tkinter import ttk

FIELDS = [('hp','hpQualification','生命资质'),('atk','atkQualification','攻击资质'),
          ('def','defQualification','防御资质'),('rehp','reHpQualification','回血资质'),
          ('phy','physical','体质'),('bone','bone','根骨'),('cap','capacity','潜力')]
PETS = {'天马': (10001, {1:170111101,2:170121101}),
        '灵花': (10002, {1:170511101,2:170521101})}

def load_ranges(pet, stars):
    with open(os.path.join(os.path.dirname(__file__), 'feature_config', 'Pet.json'), encoding='utf-8') as f:
        table = json.load(f)
    rows = [table[str(PETS[pet][1][star])] for star in stars]
    return {key:(min(int(row[attr].split(';')[0]) for row in rows),
                 max(int(row[attr].split(';')[1]) for row in rows))
            for key, attr, _ in FIELDS}

def attach(parent, frame, field, button, positive, app):
    box = frame(parent, '自选抓宠 · 天马 / 灵花',
                '捕捉结果由服务器决定。符合全部条件才保留；不合格的新宠物自动放生，已有宠物不处理。达到保留数量或尝试上限后停止。')
    pet = field(box, '选择宠物', '天马', list(PETS))
    star = field(box, '选择星级', '2星', ['1星','2星','1星或2星'])
    sex = field(box, '选择性别', '母', ['不限','公','母'])
    gourds = {'木灵葫芦':101017001,'火灵葫芦':101017002,'紫金葫芦':101017003}
    gourd = field(box, '捕捉葫芦', '木灵葫芦', list(gourds))
    count = field(box, '目标保留数量', '1')
    attempts = field(box, '最大尝试次数', '20')
    reference = tk.StringVar()
    ttk.Label(box, textvariable=reference, wraplength=650).pack(anchor='w', pady=4)
    ranges = {}
    range_labels = {}
    for title, subset in [('选择资质',FIELDS[:4]),('选择天赋',FIELDS[4:])]:
        group = ttk.LabelFrame(box, text=title+'（自填上下限，留空不限）', padding=5)
        group.pack(fill=tk.X, pady=4)
        for key, attr, label in subset:
            row = ttk.Frame(group)
            row.pack(fill=tk.X, pady=2)
            low, high = tk.StringVar(), tk.StringVar()
            ttk.Entry(row,textvariable=low,width=8).pack(side=tk.LEFT)
            ttk.Label(row,text=' ≤ '+label+' ≤ ').pack(side=tk.LEFT)
            ttk.Entry(row,textvariable=high,width=8).pack(side=tk.LEFT)
            caption = tk.StringVar()
            ttk.Label(row,textvariable=caption).pack(side=tk.LEFT,padx=12)
            ranges[key] = (low,high)
            range_labels[key] = caption
    def stars():
        return [1,2] if star.get()=='1星或2星' else [int(star.get()[0])]
    def refresh(*_):
        defaults = load_ranges(pet.get(),stars())
        for key, caption in range_labels.items():
            if len(stars()) == 2:
                one, two = load_ranges(pet.get(),[1])[key], load_ranges(pet.get(),[2])[key]
                caption.set('范围：1星 %d～%d；2星 %d～%d' % (*one,*two))
            else:
                caption.set('范围：%d～%d' % defaults[key])
        reference.set('自填希望保留的上下限；旁边是配置范围。留空的一端不限，切换宠物或星级保留输入。')
    pet.trace_add('write',refresh)
    star.trace_add('write',refresh)
    refresh()
    app.pet_capture_settings = {'pet':pet,'star':star,'sex':sex,'ranges':ranges,'range_labels':range_labels}
    def args(apply=False):
        bounds = load_ranges(pet.get(),stars())
        argv = ['--stage',str(PETS[pet.get()][0]),'--gourd',str(gourds[gourd.get()]),
                '--total',positive(attempts),'--per-stage',positive(attempts),
                '--max-attempts',positive(attempts),'--keep-total',positive(count),
                '--star',str(min(stars())),str(max(stars()))]
        sex_values = {'不限':['1','2'],'公':['1','1'],'母':['2','2']}
        argv += ['--sex']+sex_values[sex.get()]
        for key, (low_var,high_var) in ranges.items():
            low = int(low_var.get()) if low_var.get().strip() else bounds[key][0]
            high = int(high_var.get()) if high_var.get().strip() else bounds[key][1]
            if low < 0 or low > high:
                label = next(label for k,attr,label in FIELDS if k==key)
                raise ValueError('%s上下限必须满足 0 ≤ X ≤ Y' % label)
            argv += ['--'+key,str(low),str(high)]
        return argv + (['--apply'] if apply else [])
    button(box,'查看抓宠预演','pet_catch_filter.py',lambda:args(False))
    button(box,'开始自选抓宠','pet_catch_filter.py',lambda:args(True))

def attach_training(parent, frame, field, button, positive, app):
    """刷益灵花独立内容，由旧活动页的五框开关控制显示。"""
    quick=frame(parent,'刷去益灵花 · 一键运行',
        '自动完成整个流程：抓天马 → 早停升级（达标3级潜能或潜能格已满即停，地图默认取最新已开放主线并排除七星殿、蓬丘）→ 保留所选潜能等级的宠物并放生本批其余宠物。循环轮数0表示持续运行；不使用点券，默认不遗忘潜能。')
    quick_holder=[]
    training_password=tk.StringVar()
    quick_row=ttk.Frame(quick);quick_row.pack(anchor='w',pady=5)
    quick_button=ttk.Button(quick_row,text='一键运行：抓宠 → 早停升级 → 保留3级',command=lambda:quick_holder[0]())
    quick_button.pack(side=tk.LEFT);app.feature_buttons.append(quick_button)
    ttk.Label(quick_row,text='  二级密码（有则填，无则留空）').pack(side=tk.LEFT,padx=(12,4))
    ttk.Entry(quick_row,textvariable=training_password,show='*',width=16).pack(side=tk.LEFT)
    ttk.Label(quick,text='密码仅本次运行使用，启动后自动清空；放生、遗忘需要二级密码的账号必须填写。日常只需点上方按钮；下方分步按钮仅用于单步调试。',foreground='gray',wraplength=650).pack(anchor='w')
    training = frame(parent,'刷益灵花 · 第一步：抓天马',
        '默认保留10只，可自选数量。只要求潜力≥4；不限制星级、性别、资质。已有宠物不处理，新抓不合格宠物自动放生。每只保留宠物的唯一ID写入独立清单，供后续步骤使用。')
    training_count = field(training,'目标保留数量','10')
    ttk.Label(training,text='二级密码在上方“一键运行”按钮旁填写。木灵葫芦耗尽时自动用灵魂购买10000个；当前单价2000灵魂，每次补购需2000万灵魂。不使用点券。宠物空格不足目标数量时停止。',foreground='red',wraplength=650).pack(anchor='w',pady=4)
    button(training,'查看第一步预演','pet_training_capture.py',lambda:['--count',positive(training_count)])
    def start_training_capture():
        if app.running:return
        try:argv=['--count',positive(training_count),'--apply']
        except (ValueError,TypeError) as exc:
            from tkinter import messagebox
            messagebox.showerror('抓天马',str(exc));return
        if app._save_selected_slot():
            password=training_password.get();training_password.set('')
            app._launch([os.path.join(os.path.dirname(__file__),'pet_training_capture.py')]+argv,
                extra_env={'ZM5_PET_CAPTURE_PASSWORD':password})
    start_button=ttk.Button(training,text='开始第一步：抓天马并保存ID',command=start_training_capture)
    start_button.pack(anchor='w',pady=3);app.feature_buttons.append(start_button)
    leveling=frame(parent,'刷益灵花 · 第二步：刷主线升级',
        '读取第一步清单。默认早停：每局结算后按服务器升级推送判定，潜能达到3级或潜能格已满立即停止，到101级也停。地图默认取最新已开放主线（排除七星殿80、蓬丘61）；旧两段为兼容保留，先75级再101级，耗时明显更长。')
    manifest=field(leveling,'宠物清单（留空自动选最新）','')
    def choose_manifest():
        from tkinter import filedialog
        name=filedialog.askopenfilename(title='选择第一步宠物清单',filetypes=[('宠物清单','*.json')])
        if name:manifest.set(name)
    browse=ttk.Button(leveling,text='选择第一步清单文件',command=choose_manifest);browse.pack(anchor='w',pady=3);app.feature_buttons.append(browse)
    map_id=field(leveling,'升级副本地图（0＝自动最新主线，可填78等）','0')
    mode=field(leveling,'出战方式','自动（单人1P／双人双宠）',['自动（单人1P／双人双宠）','仅1P','1P和2P'])
    bonus=tk.BooleanVar(value=True)
    ttk.Checkbutton(leveling,text='升级前领取免费寿星／在线经验增益（寿星到期仅使用剩余免费次数补领）',variable=bonus).pack(anchor='w',pady=4)
    if hasattr(app,'ui_settings_fields'):app.ui_settings_fields['潜能培养/免费经验增益']=(bonus,None)
    method=field(leveling,'培养方式','早停（推荐，实测约4分钟/朵）',['早停（推荐，实测约4分钟/朵）','旧两段75→101（效率低，仅兼容）'])
    def level_args(apply=False):
        argv=['--mode',{'自动（单人1P／双人双宠）':'auto','仅1P':'p1','1P和2P':'both'}[mode.get()]]
        if manifest.get().strip():argv+=['--manifest',manifest.get().strip()]
        raw=map_id.get().strip() or '0'
        if not raw.isdigit():raise ValueError('升级副本地图须填非负整数，0表示自动最新')
        if int(raw):argv+=['--map',raw]
        if not bonus.get():argv+=['--no-exp-buffs']
        if method.get().startswith('早停'):argv+=['--early-stop','--target-passive','3']
        return argv+(['--apply'] if apply else [])
    ttk.Label(leveling,text='双人档两只宠物分别获得完整经验。按当前实际经验计算局数；经验加成不同，所需局数也会不同。完成后恢复原出战宠物，不放生、不遗忘潜能。',wraplength=650).pack(anchor='w',pady=4)
    button(leveling,'查看第二步预演','pet_training_level.py',lambda:level_args(False))
    button(leveling,'开始第二步：出战并升级','pet_training_level.py',lambda:level_args(True))
    final=frame(parent,'刷益灵花 · 第三步：遗忘取花／筛选',
        '可以只培养保留，或遗忘本批≥3级且按当前VIP能返还益灵花的潜能。取花后按剩余潜能等级保留／放生；只处理第一步清单，原有宠物受保护。')
    action=field(final,'潜能处理','仅培养保留（不遗忘）',['仅培养保留（不遗忘）','自动遗忘换益灵花（消耗去灵花）'])
    retain=field(final,'保留剩余潜能等级','3级及以上',['3级及以上','2级及以上'])
    cycles=field(final,'循环轮数（0为持续循环）','0')
    ttk.Label(final,text='遗忘会永久删除对应潜能，每次消耗1朵去灵花。VIP0—2三级不返益灵花，会跳过；VIP3以上三级可返。按VIP配置预检数量并核对实际到账，去灵花不足不自动购买。取花后剩余潜能低于所选标准的本批宠物会放生。',wraplength=650,foreground='red').pack(anchor='w',pady=5)
    ttk.Label(final,text='一键运行会复用上方每批数量、出战方式、副本地图和二级密码。双人档默认双宠，各自获取完整经验；仅75／101级节点读取存档。保留宠物累计记录ID；空格不足、材料不足或异常停止。日志记录每批耗时、取花数量和保留／放生数量。',wraplength=650).pack(anchor='w',pady=5)
    def policy_args():
        return ['--retain-min',retain.get()[0]]+(['--harvest'] if action.get().startswith('自动遗忘') else [])
    def finalize_args(apply=False):
        argv=['--action','finalize']+policy_args()
        if manifest.get().strip():argv+=['--manifest',manifest.get().strip()]
        return argv+(['--apply'] if apply else [])
    button(final,'查看第三步预演','pet_training_cycle.py',lambda:finalize_args(False))
    def launch_final(argv):
        if app._save_selected_slot():
            password=training_password.get();training_password.set('')
            app._launch([os.path.join(os.path.dirname(__file__),'pet_training_cycle.py')]+argv,extra_env={'ZM5_PET_CAPTURE_PASSWORD':password})
    def process_current():
        if not app.running:launch_final(finalize_args(True))
    process_button=ttk.Button(final,text='仅处理当前批次：按所选方式取花／筛选',command=process_current)
    process_button.pack(anchor='w',pady=3);app.feature_buttons.append(process_button)
    def start_cycle():
        if app.running:return
        try:
            rounds=int(cycles.get())
            if rounds<0:raise ValueError('循环轮数不能小于0')
            argv=['--action','cycle','--count',positive(training_count),'--cycles',str(rounds)]+level_args(False)+policy_args()+['--apply']
        except (ValueError,TypeError) as exc:
            from tkinter import messagebox
            messagebox.showerror('潜能培养循环',str(exc));return
        launch_final(argv)
    if hasattr(app,'ui_settings_fields'):
        app.ui_settings_fields['刷益灵花/潜能处理']=(action,None)
        app.ui_settings_fields['刷益灵花/保留等级']=(retain,None)
        app.ui_settings_fields['刷益灵花/副本地图']=(map_id,None)
    quick_holder.append(start_cycle)
