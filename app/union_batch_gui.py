"""独立的联盟多账号窗口，不依赖工具箱GUI。"""
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

HERE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def network_error_label(exc):
    import urllib.error,socket,ssl
    reason=getattr(exc,'reason',exc)
    if isinstance(exc,urllib.error.HTTPError):return '登录接口HTTP错误（%s）'%exc.code
    if isinstance(reason,socket.gaierror):return 'DNS解析失败，请检查节点或网络'
    if isinstance(reason,(TimeoutError,socket.timeout)):
        return '登录接口TLS握手超时，请检查或更换节点' if 'handshake' in str(reason).lower() else '网络连接超时，请检查节点'
    if isinstance(reason,ssl.SSLError):return 'TLS安全连接失败，请检查节点或证书'
    return '连接或存档响应异常（%s）'%type(exc).__name__


class SlotPicker(ttk.Combobox):
    def get(self):
        return super().get().split(' ',1)[0]


def describe_slots(records):
    if not isinstance(records,list):raise ValueError('未读取到存档列表')
    choices=[];lines=[]
    for row in records:
        slot=row.get('index');status=row.get('status')
        if type(slot) is not int or not 0<=slot<=7:continue
        roles=['%s Lv%s'%(p.get('name') or p.get('charId','角色'),p.get('level','?')) for p in (row.get('p1'),row.get('p2')) if isinstance(p,dict) and p]
        label='%s %s [%s]'%(slot,' + '.join(roles) or '无角色',{0:'空',1:'有角色',3:'冻结'}.get(status,'状态未知'))
        lines.append(label)
        if status==1 and roles:choices.append(label)
    return choices,lines


class UnionBatchWindow:
    def __init__(self, root):
        self.root = root
        self.restoring = False
        self.settings_path = HERE / "union_batch_settings.json"
        self.login_busy = False
        self.dog_overview = {}
        try:self.account_history=json.loads((HERE/'union_account_history.private.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):self.account_history={}
        self.jobs = {}
        self.files = {}
        self.proc = None
        self.batch_path = None
        self.messages = queue.Queue()
        root.title("联盟多账号 · 贡献 / 九灵元圣 / 药园 / 狗卡")
        root.geometry("850x780")
        root.minsize(640, 480)
        viewport = ttk.Frame(root)
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        viewport.grid(row=0, column=0, sticky="nsew")
        viewport.rowconfigure(0, weight=1)
        viewport.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewport, highlightthickness=0)
        vertical = ttk.Scrollbar(viewport, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(viewport, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        outer = ttk.Frame(self.canvas, padding=12)
        self.scroll_body = outer
        self.body_window = self.canvas.create_window(0, 0, window=outer, anchor="nw")
        def resize(_event=None):
            self.canvas.itemconfigure(self.body_window, width=max(self.canvas.winfo_width(), outer.winfo_reqwidth()))
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        outer.bind("<Configure>", resize)
        self.canvas.bind("<Configure>", resize)
        root.bind("<MouseWheel>", self.scroll_wheel, add="+")
        root.bind("<Shift-MouseWheel>", self.scroll_wheel, add="+")
        row = ttk.Frame(outer)
        row.pack(fill="x")
        ttk.Label(row, text="已保存账号").pack(side="left")
        self.account = ttk.Combobox(row, state="readonly", width=24)
        self.account.pack(side="left", padx=6)
        ttk.Button(row, text="刷新", command=self.refresh).pack(side="left")
        ttk.Label(row, text="存档").pack(side="left", padx=(12, 4))
        self.slot = SlotPicker(row, values=list(range(8)), state="readonly", width=35)
        self.slot.set("0")
        self.slot.pack(side="left")
        ttk.Button(row,text="读取存档",command=self.query_slots).pack(side="left",padx=4)
        ttk.Button(row, text="添加", command=self.add_selected).pack(side="left", padx=6)
        ttk.Button(outer,text="恢复当前名单旧槽位 / 标记新旧",command=self.restore_known_slots).pack(anchor="w",pady=4)
        ttk.Button(row, text="导入专用账号文件", command=self.import_file).pack(side="left")
        from union_batch_login import open_login
        ttk.Button(outer,text="独立登录（账密 / Cookie）",command=lambda:open_login(self)).pack(anchor="w",pady=4)
        area = ttk.Frame(outer, width=780, height=225)
        area.pack(anchor="w", pady=8)
        area.grid_propagate(False)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda event: area.configure(width=max(200, event.width-24)), add="+")
        from union_boss_batch import DOG_NAMES
        columns=('account','slot','state','used','bonus','gift_today')+tuple('dog_'+str(n) for n in range(1,12))+('origin',)
        self.table = ttk.Treeview(area, columns=columns, show="headings", height=8)
        headers=('执行账号','槽位','查询状态','已抽次数','额外次数','今日赠送')+DOG_NAMES+('账号来源',)
        for key,title in zip(columns,headers):
            self.table.heading(key,text=title);self.table.column(key,width=160 if key=='account' else 95,stretch=False)
        self.table.tag_configure('giftable',foreground='#14532d',background='#dcfce7')
        self.table.tag_configure('failed',foreground='#991b1b',background='#fee2e2')
        self.table.bind('<<TreeviewSelect>>',lambda *_:self.show_dog_detail())
        scroll = ttk.Scrollbar(area, command=self.table.yview)
        table_horizontal = ttk.Scrollbar(area, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=table_horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        table_horizontal.grid(row=1, column=0, sticky="ew")
        self.task_tabs = ttk.Notebook(outer)
        self.task_tabs.pack(fill='both', expand=True, pady=6)
        dog_page = ttk.Frame(self.task_tabs, padding=6)
        union_page = ttk.Frame(self.task_tabs, padding=6)
        self.task_tabs.add(dog_page, text='狗卡')
        self.task_tabs.add(union_page, text='联盟事务')
        outer = dog_page
        overview_buttons=ttk.Frame(outer);overview_buttons.pack(fill='x')
        self.dog_filter=tk.StringVar(value='全部')
        ttk.Label(overview_buttons,text='今日赠送：').pack(side='left')
        filter_combo=ttk.Combobox(overview_buttons,textvariable=self.dog_filter,values=('全部','今日已赠送','今日未赠送'),state='readonly',width=14);filter_combo.pack(side='left',padx=4)
        self.dog_filter.trace_add('write',lambda *_:self.apply_dog_filter())
        self.dog_activation_filter=tk.StringVar(value='全部')
        ttk.Label(overview_buttons,text='激活分类：').pack(side='left',padx=(8,0))
        ttk.Combobox(overview_buttons,textvariable=self.dog_activation_filter,values=('全部','已激活博美汪','已激活斗牛汪','两种都未激活'),state='readonly',width=16).pack(side='left',padx=4)
        self.dog_activation_filter.trace_add('write',lambda *_:self.apply_dog_filter())
        ttk.Button(overview_buttons,text='刷新全部狗卡',command=lambda:self.start(action_override='dog_status')).pack(side='left',padx=3)
        ttk.Button(overview_buttons,text='刷新所选狗卡',command=self.refresh_selected_dogs).pack(side='left',padx=3)
        ttk.Label(outer,text='卡片格式：数量 / 激活状态；绿色行表示有可赠送余卡。横向滚动查看全部品种。').pack(anchor='w')
        self.dog_detail=tk.StringVar(value='选中账号查看狗卡明细。')
        ttk.Label(outer,textvariable=self.dog_detail,wraplength=780).pack(anchor='w',pady=4)
        details=ttk.LabelFrame(outer,text='所选账号狗卡明细');details.pack(fill='x',pady=4)
        self.dog_detail_table=ttk.Treeview(details,columns=('name','count','active','gift'),show='headings',height=11)
        for key,title in [('name','狗卡'),('count','数量'),('active','激活状态'),('gift','可赠送数量')]:
            self.dog_detail_table.heading(key,text=title);self.dog_detail_table.column(key,width=150,anchor='center')
        self.dog_detail_table.tag_configure('giftable',foreground='#14532d',background='#dcfce7')
        self.dog_detail_table.tag_configure('active',foreground='#1e40af',background='#eff6ff')
        self.dog_detail_table.tag_configure('ready',foreground='#9a3412',background='#ffedd5')
        self.dog_detail_table.tag_configure('empty',foreground='#6b7280')
        self.dog_detail_table.pack(fill='x')
        ttk.Label(details,text='✓ 已激活（蓝）；○ 未激活有卡（橙）；★ 可赠送（绿）；无卡未激活（灰）').pack(anchor='w',padx=4,pady=4)

        ttk.Button(outer, text="移除选中账号", command=self.remove).pack(anchor="w")
        chain=ttk.LabelFrame(outer,text='按当前筛选结果接力（每账号今日最多额外抽一次）',padding=6);chain.pack(fill='x',pady=6)
        from union_boss_batch import DOG_NAMES
        self.chain_card=tk.StringVar(value=DOG_NAMES[1]);self.chain_seed=tk.StringVar(value='输入兑换码');self.chain_code=tk.StringVar()
        ttk.Combobox(chain,textvariable=self.chain_card,values=(DOG_NAMES[1], DOG_NAMES[0], *DOG_NAMES[2:]),state='readonly',width=14).pack(side='left',padx=3)
        ttk.Combobox(chain,textvariable=self.chain_seed,values=('输入兑换码','使用名单中余卡'),state='readonly',width=18).pack(side='left',padx=3)
        ttk.Entry(chain,textvariable=self.chain_code,show='*',width=20).pack(side='left',padx=3)
        ttk.Button(chain,text='一键接力＋额外抽卡',command=lambda:self.start(action_override='dog_chain',job_keys=self.table.get_children())).pack(side='left',padx=3)
        ttk.Button(chain,text='查看上次链末码',command=self.view_chain_code).pack(side='left',padx=3)
        single=ttk.LabelFrame(dog_page,text='单账号操作（先选中上方一个账号）',padding=6)
        single.pack(fill='x',pady=6)
        self.single_card=tk.StringVar(value=DOG_NAMES[0])
        picker=ttk.Frame(single);picker.grid(row=0,column=0,columnspan=2,sticky='w',pady=4)
        ttk.Label(picker,text='单账号卡种：').pack(side='left')
        ttk.Combobox(picker,textvariable=self.single_card,values=(DOG_NAMES[1],DOG_NAMES[0],*DOG_NAMES[2:]),state='readonly',width=16).pack(side='left',padx=4)
        self.single_code=tk.StringVar()
        ttk.Entry(single,textvariable=self.single_code,show='*',width=26).grid(row=1,column=0,padx=3,pady=3)
        ttk.Button(single,text='使用兑换码',command=lambda:self.single_dog_action('redeem')).grid(row=1,column=1,padx=3)
        ttk.Button(single,text='仅生成赠送码',command=lambda:self.single_dog_action('gift')).grid(row=2,column=0,padx=3,pady=3)
        ttk.Button(single,text='生成码＋额外抽卡',command=lambda:self.single_dog_action('gift_draw')).grid(row=2,column=1,padx=3)
        ttk.Button(single,text='查询该账号服务器兑换码',command=self.view_single_codes).grid(row=3,column=0,columnspan=2,sticky='w',pady=3)
        ttk.Button(single,text='激活所选卡种',command=lambda:self.single_dog_action('single_activate')).grid(row=4,column=0,sticky='w',pady=3)
        options = ttk.LabelFrame(union_page, text="执行设置", padding=8)
        options.pack(fill="x", pady=8)
        ttk.Button(options, text="设置选中账号二级密码（仅购买种子使用）", command=self.set_garden_password).pack(anchor="w")
        self.action = tk.StringVar(value="boss")
        ttk.Radiobutton(options, text="联盟贡献（每号一次，消耗1000灵魂）", variable=self.action, value="devote").pack(anchor="w")
        ttk.Radiobutton(options, text="联盟Boss · 九灵元圣", variable=self.action, value="boss").pack(anchor="w")
        ttk.Radiobutton(options, text="联盟药园（查看 / 收获 / 种植）", variable=self.action, value="garden").pack(anchor="w")
        ttk.Button(dog_page, text="每日免费抽狗卡（每号尝试1次，跨存档共享）", command=lambda:self.start(action_override="dog")).pack(anchor="w")
        ttk.Label(dog_page, text="狗卡仅普通抽取并核对到账，不购买、不赠送、不兑换；次数用完则跳过。", foreground="gray", wraplength=700).pack(anchor="w")
        ttk.Button(dog_page,text="查询狗卡库存 / 可赠送",command=lambda:self.start(action_override="dog_status")).pack(anchor="w",pady=4)
        from union_boss_batch import DOG_NAMES
        dogbox=ttk.LabelFrame(dog_page,text='选择要激活的狗卡',padding=4);dogbox.pack(fill='x',pady=4)
        self.dog_activation={}
        for n,name in enumerate(DOG_NAMES,1):
            value=tk.BooleanVar(value=n==1);self.dog_activation['dog_activate_'+str(n)]=value
            ttk.Checkbutton(dogbox,text=name,variable=value).grid(row=(n-1)//4,column=(n-1)%4,sticky='w',padx=5)
        ttk.Button(dogbox,text='并行激活所选狗卡',command=lambda:self.start(action_override='dog_activate')).grid(row=3,column=0,columnspan=4,sticky='w',pady=4)
        garden = ttk.LabelFrame(options, text="药园设置", padding=6)
        garden.pack(fill="x", pady=6)
        self.garden_pick = tk.BooleanVar(value=False)
        self.garden_uproot = tk.BooleanVar(value=False)
        ttk.Checkbutton(garden, text="一键免费采摘成熟植物", variable=self.garden_pick).pack(anchor="w")
        ttk.Checkbutton(garden, text="铲除已无领取次数的植物", variable=self.garden_uproot).pack(anchor="w")
        from union_garden import catalog
        plants = sorted(catalog().values(), key=lambda row: row.get("order", 0))
        self.garden_seeds = {"不种植（仅查看或处理）": 0}
        self.garden_seeds.update({"%s（基础成熟%s小时）" % (row["name"], row["cd"]): row["id"] for row in plants})
        self.garden_seed = ttk.Combobox(garden, values=list(self.garden_seeds), state="readonly", width=38)
        self.garden_seed.set(next(iter(self.garden_seeds)))
        self.garden_seed.pack(anchor="w", pady=4)
        self.garden_mode = tk.StringVar(value="direct")
        ttk.Radiobutton(garden, text="直接种植（使用已有种子）", variable=self.garden_mode, value="direct").pack(anchor="w")
        ttk.Radiobutton(garden, text="贡献购买并种植（需逐个账号设置二级密码）", variable=self.garden_mode, value="buy").pack(anchor="w")
        counts = ttk.Frame(garden); counts.pack(fill="x")
        ttk.Label(counts, text="每号种植数量（0为全部空地）").pack(side="left")
        self.garden_count = tk.StringVar(value="1")
        ttk.Spinbox(counts, from_=0, to=99, width=5, textvariable=self.garden_count).pack(side="left", padx=6)
        buttons = ttk.Frame(garden); buttons.pack(fill="x", pady=4)
        for title, op in [("查看状态", "view"), ("一键免费采摘", "pick"), ("铲除耗尽植物", "uproot"), ("执行种植", "plant")]:
            ttk.Button(buttons, text=title, command=lambda action=op: self.start(action)).pack(side="left", padx=2)
        ttk.Label(garden, text="采摘→铲除→种植。仍有普通收获或琼浆次数的植物保留；仅种已开放空地，不催熟。二级密码仅临时使用，不保存到账号文件。", wraplength=700).pack(anchor="w")
        self.idle = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="累计伤害达到Boss最大血量0.2%后挂机，等待结算", variable=self.idle).pack(anchor="w", pady=4)
        damage = ttk.Frame(options)
        damage.pack(fill="x")
        ttk.Label(damage, text="每秒期望伤害").pack(side="left")
        self.dps = tk.StringVar()
        ttk.Entry(damage, textvariable=self.dps, width=14).pack(side="left", padx=6)
        ttk.Label(damage, text="默认使用当前面板/技能估算模型；此输入为备用参数").pack(side="left")
        ttk.Label(options, text="未勾选挂机则持续按期望伤害攻击。挂机每秒随机0～10000。奖励在游戏邮件领取。",
                  wraplength=600, foreground="gray").pack(anchor="w", pady=(6, 0))
        self.footer = ttk.Frame(root, padding=(12, 6, 12, 10))
        self.footer.grid(row=1, column=0, sticky="ew")
        controls = ttk.Frame(self.footer)
        controls.pack(fill="x", pady=(0, 6))
        self.start_button = ttk.Button(controls, text="开始并行执行", command=lambda: self.start(action_override="dog" if self.task_tabs.index(self.task_tabs.select()) == 0 else (self.action.get() if self.action.get() != "dog" else "boss")))
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="停止全部", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        ttk.Label(controls, text="同一账号只添加一个存档").pack(side="left")
        self.log = ScrolledText(self.footer, height=7, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)
        self.refresh()
        self.restore_selection()
        for variable in self.execution_variables().values():
            variable.trace_add('write', lambda *_:self.save_selection())
        self.garden_seed.bind('<<ComboboxSelected>>',lambda *_:self.save_selection())
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def accept_login(self, account, remember=True):
        uid=str(account['uid'])
        existing=next((key for key,row in self.jobs.items() if row['uid']==uid),None)
        if remember:
            folder=HERE/'union_accounts';folder.mkdir(exist_ok=True)
            target=folder/(uid+'.json');tmp=target.with_suffix('.tmp')
            tmp.write_text(json.dumps(account,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(target)
            row={'uid':uid,'slot':int(self.slot.get()),'path':str(target.resolve())}
        else:
            row={'uid':uid,'slot':int(self.slot.get()),'path':'','session_account':account}
        if existing is None:existing=self.table.insert('', 'end', values=(account['username'],row['slot']))
        else:self.table.item(existing,values=(account['username'],row['slot']))
        self.jobs[existing]=row;self.refresh();self.save_selection()
        self.messages.put('独立登录成功：'+('已保存到专用账号目录' if remember else '仅本次使用，未保存凭据'))

    def query_slots(self):
        if self.proc is not None or self.login_busy:return
        try:
            selected=self.table.selection()
            row=self.jobs.get(selected[0]) if selected else None
            if row:
                account=row.get('session_account') or json.loads(Path(row['path']).read_text(encoding='utf-8-sig'))
            else:
                path=self.files.get(self.account.get())
                if not path:raise ValueError('请先选择账号，或选中执行列表中的临时账号')
                account=json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError,KeyError) as exc:
            messagebox.showerror('读取存档','请先选择有效账号');return
        self.login_busy=True
        def show(records,error):
            self.login_busy=False
            if error:self.messages.put(error);return
            choices,lines=describe_slots(records)
            self.slot.configure(values=choices)
            current=self.slot.get()
            chosen=next((v for v in choices if v.split(' ',1)[0]==current),choices[0] if choices else '')
            self.slot.set(chosen)
            self.messages.put('存档列表（仅查询，未进入存档）：\n'+'\n'.join(lines))
            if not choices:self.messages.put('此账号没有可用角色存档。')
        def work():
            flow=None
            try:
                from teacher_trial import GATES,GameLoginFlow,fetch_game_token,checked
                token=fetch_game_token(account['uid'],account['username'],account['cookies'])
                records=None
                for gate in GATES[:3]:
                    try:
                        flow=GameLoginFlow(uid=account['uid'],token=token)
                        host,port=flow.query_entry(gate,3010);checked(flow.auth(host,port),'认证')
                        home=checked(flow.request('connector.roleHandler.getUserInfo',{}),'查询存档')
                        records=(home.get('user') or {}).get('records');describe_slots(records);break
                    except Exception:
                        if flow:flow.disconnect();flow=None
                if records is None:raise ValueError('存档查询失败')
                self.messages.put(('callback',lambda:show(records,None)))
            except Exception as exc:
                error='存档查询失败：%s；未进入角色或执行任务'%network_error_label(exc)
                self.messages.put(('callback',lambda:show(None,error)))
            finally:
                if flow:flow.disconnect()
        threading.Thread(target=work,daemon=True).start()

    def apply_dog_filter(self):
        if not hasattr(self,'dog_filter'):return
        choice=self.dog_filter.get()
        for key,row in self.jobs.items():
            self.table.set(key,'origin','旧账号' if row['uid'] in self.account_history else '新加入（旧名单外）')
            data=self.dog_overview.get(key)
            known=bool(data and data.get('status')=='ok' and data.get('slot')==row['slot'])
            gifted=known and int((data.get('daily') or {}).get('addDouble11LotteryCnt',0))>0
            visible=choice=='全部' or known and ((choice=='今日已赠送' and gifted) or (choice=='今日未赠送' and not gifted))
            category=self.dog_activation_filter.get() if hasattr(self,'dog_activation_filter') else '全部'
            if category!='全部':
                cards=data.get('cards',[]) if known else []
                eligible=len(cards)>=2 and ((category=='已激活博美汪' and cards[0]['active']) or (category=='已激活斗牛汪' and cards[1]['active']) or (category=='两种都未激活' and not cards[0]['active'] and not cards[1]['active']))
                visible=visible and bool(eligible)
            if visible:self.table.move(key,'','end')
            else:
                self.table.selection_remove(key);self.table.detach(key)
        if hasattr(self,'dog_detail'):self.show_dog_detail()

    def single_dog_action(self, action):
        keys=self.table.selection()
        if len(keys)!=1:
            messagebox.showerror('选择账号','请只选中一个账号',parent=self.root);return
        self.start(action_override='dog_'+action,job_keys=keys)

    def view_single_codes(self):
        keys=self.table.selection()
        if len(keys)!=1:
            messagebox.showerror('选择账号','请只选中一个账号',parent=self.root);return
        self.start(action_override='dog_codes',job_keys=keys)

    def show_server_codes(self,data):
        if not any(row['uid']==str(data.get('uid')) and row['slot']==data.get('slot') for row in self.jobs.values()):return
        rows=data.get('rows',[])
        win=tk.Toplevel(self.root);win.title('服务器兑换码 · 槽'+str(data['slot']));win.geometry('600x300')
        ttk.Label(win,text='本次实时查询结果；服务器未提供的使用状态不作推断。').pack(anchor='w',padx=8,pady=6)
        table=ttk.Treeview(win,columns=('card','code'),show='headings',height=7)
        for k,title in [('card','卡种'),('code','兑换码')]:table.heading(k,text=title);table.column(k,width=240)
        for i,values in enumerate(rows):table.insert('','end',iid=str(i),values=values)
        table.pack(fill='both',expand=True,padx=8)
        if not rows:ttk.Label(win,text='服务器本次返回的兑换码列表为空。').pack()
        def use():
            chosen=table.selection()
            if chosen:self.single_code.set(rows[int(chosen[0])][1]);win.destroy()
        ttk.Button(win,text='填入领取框（不自动领取）',command=use).pack(pady=6)

    def view_chain_code(self):
        card=__import__('union_boss_batch').DOG_NAMES.index(self.chain_card.get())+1
        members={(row['uid'],row['slot']) for key,row in self.jobs.items() if key in self.table.get_children()}
        for path in sorted((HERE/'dog_chain_reports').glob('*.private.json'),reverse=True):
            report=json.loads(path.read_text(encoding='utf8'))
            if report.get('card')==card and report.get('status')=='complete' and report.get('current_code') and members.intersection({(x['uid'],x['slot']) for x in report.get('members',[])}):
                self.chain_code.set(report['current_code']);self.chain_seed.set('输入兑换码');return
        messagebox.showinfo('链末码','没有匹配当前名单和卡种的已完成接力码',parent=self.root)

    def refresh_selected_dogs(self):
        keys=self.table.selection()
        if not keys:messagebox.showinfo('未选择','请选择需要刷新的账号',parent=self.root);return
        self.start(action_override='dog_status',job_keys=keys)

    def render_dog_overview(self,data):
        key=next((key for key,row in self.jobs.items() if row['uid']==str(data.get('uid')) and row['slot']==data.get('slot')),None)
        if key is None:return
        self.dog_overview[key]=data
        values=list(self.table.item(key,'values'))[:2]
        if data.get('status')!='ok':
            self.table.item(key,values=values+['失败：'+data.get('error','查询失败'),'','','未知'],tags=('failed',));self.apply_dog_filter();self.show_dog_detail();return
        daily=data.get('daily') or {};cards=data['cards']
        cells=[str(c['count'])+' / '+('✓已激活' if c['active'] else '○未激活')+(' ★' if c['giftable']>0 else '') for c in cards]
        self.table.item(key,values=values+['已刷新',daily.get('double11LotteryCnt',0),daily.get('addDouble11LotteryCnt',0),'今日已赠送' if int(daily.get('addDouble11LotteryCnt',0))>0 else '今日未赠送']+cells,tags=('giftable',) if any(c['giftable'] for c in cards) else ())
        self.apply_dog_filter()
        self.show_dog_detail()

    def show_dog_detail(self):
        selection=self.table.selection()
        self.dog_detail_table.delete(*self.dog_detail_table.get_children())
        if not selection:self.dog_detail.set('请选择账号；筛选未知账号前，请先刷新全部狗卡。');return
        data=self.dog_overview.get(selection[0]);row=self.jobs.get(selection[0])
        if not data or not row or row['slot']!=data.get('slot'):
            self.dog_detail.set('该账号尚未查询，或槽位已改变，请刷新。');return
        if data.get('status')!='ok':self.dog_detail.set(data.get('error','查询失败'));return
        cards=data['cards']
        self.dog_detail.set('已激活%s/11种；有卡未激活%s种；有可赠送余卡%s种。'%(sum(c['active'] for c in cards),sum(not c['active'] and c['count']>0 for c in cards),sum(c['giftable']>0 for c in cards)))
        for n,c in enumerate(cards,1):
            tag='giftable' if c['giftable']>0 else ('active' if c['active'] else ('ready' if c['count']>0 else 'empty'))
            self.dog_detail_table.insert('', 'end',iid=str(n),values=(c['name'],c['count'],'✓ 已激活' if c['active'] else '○ 未激活',str(c['giftable'])+('张 ★ 可赠送' if c['giftable'] else '')),tags=(tag,))

    def execution_variables(self):
        return {**{key:getattr(self,key) for key in ('action','garden_pick','garden_uproot','garden_mode','garden_count','idle','dps','dog_filter','dog_activation_filter','chain_card','chain_seed','single_card')},**self.dog_activation}

    def save_selection(self):
        if self.restoring:return
        rows=[{"path":r["path"],"slot":r["slot"],"uid":r["uid"]} for r in self.jobs.values() if not r.get("session_account")]
        try:
            tmp=self.settings_path.with_suffix('.tmp')
            tmp.write_text(json.dumps({"accounts":rows,"execution":{**{key:variable.get() for key,variable in self.execution_variables().items()},'garden_seed_id':self.garden_seeds.get(self.garden_seed.get(),0)}},ensure_ascii=False,indent=2),encoding='utf8')
            tmp.replace(self.settings_path)
        except OSError:
            self.messages.put('账号选择未能保存，请检查配置目录写入权限。')

    def restore_selection(self):
        if not self.settings_path.exists():return
        self.restoring=True
        original_slot=self.slot.get()
        skipped=0
        try:
            saved=json.loads(self.settings_path.read_text(encoding='utf-8-sig'))
            settings=saved.get('execution',{})
            if isinstance(settings,dict):
                for key,variable in self.execution_variables().items():
                    if key not in settings:continue
                    value=settings[key]
                    # 狗卡状态仅在本次查询后可信，启动时先显示已保存的完整名单。
                    if key in ('dog_filter','dog_activation_filter'):
                        variable.set('全部')
                        continue
                    if key=='action' and value not in ('boss','devote','garden','dog'):continue
                    if key=='garden_mode' and value not in ('direct','buy'):continue
                    if key=='dog_filter' and value not in ('全部','今日已赠送','今日未赠送'):continue
                    if key=='dog_activation_filter' and value not in ('全部','已激活博美汪','已激活斗牛汪','两种都未激活'):continue
                    if key=='chain_seed' and value not in ('输入兑换码','使用名单中余卡'):continue
                    if key in ('chain_card','single_card') and value not in __import__('union_boss_batch').DOG_NAMES:continue
                    if key in ('garden_pick','garden_uproot','idle') or key.startswith('dog_activate_'):
                        if not isinstance(value,bool):continue
                    elif not isinstance(value,str):continue
                    variable.set(value)
                seed=next((label for label,value in self.garden_seeds.items() if value==settings.get('garden_seed_id')),None)
                if seed:self.garden_seed.set(seed)
            rows=saved.get('accounts',[])
            if not isinstance(rows,list):raise ValueError('账号列表格式不正确')
            for row in rows:
                try:
                    path=Path(row['path']);slot=int(row['slot'])
                    if not 0<=slot<=7:raise ValueError('无效槽位')
                    account=json.loads(path.read_text(encoding='utf-8-sig'))
                    if str(account.get('uid'))!=str(row['uid']):raise ValueError('文件账号已变化')
                    self.slot.set(str(slot));before=len(self.jobs)
                    # 失效文件只略过，避免启动时弹出一串错误框。
                    cookies=account.get('cookies') or {}
                    if not isinstance(cookies,dict) or not all(cookies.get(k) for k in ('Pauth','Uauth','Xauth','USESSIONID')):raise ValueError('凭据不完整')
                    if any(r['uid']==str(account['uid']) for r in self.jobs.values()):continue
                    self.add_path(path)
                    if len(self.jobs)==before:skipped+=1
                except (OSError,ValueError,KeyError,TypeError):skipped+=1
            self.messages.put('已恢复%s个账号及槽位；未启动任何任务。'%len(self.jobs))
            if skipped:self.messages.put('另有%s条账号配置失效或文件缺失，已跳过；请重新添加。'%skipped)
        except (OSError,ValueError,TypeError):
            self.messages.put('账号选择配置读取失败，请重新添加账号。')
        finally:
            self.slot.set(original_slot);self.restoring=False
            self.apply_dog_filter()

    def scroll_wheel(self, event):
        # 日志、账号表和下拉框保留自己的滚动行为。
        if event.widget.winfo_class() in ('Text', 'Treeview', 'TCombobox', 'TSpinbox'):
            return
        delta = int(event.delta)
        if not delta:return
        units = -max(1, abs(delta)//120) if delta > 0 else max(1, abs(delta)//120)
        if event.state & 1:self.canvas.xview_scroll(units, "units")
        else:self.canvas.yview_scroll(units, "units")
        return "break"

    def refresh(self):
        self.files = {}
        for directory, prefix in ((HERE/'union_accounts', '专用'), (HERE/'accounts', '主程序')):
            for path in sorted(directory.glob('*.json')):
                self.files[prefix+' · '+path.stem]=path
        self.account.configure(values=list(self.files))
        if self.account.get() not in self.files:
            self.account.set(next(iter(self.files), ""))

    def add_selected(self):
        path = self.files.get(self.account.get())
        if path:
            self.add_path(path)

    def import_file(self):
        path = filedialog.askopenfilename(title="选择已保存的账号文件", filetypes=[("账号文件", "*.json")])
        if path:
            self.import_private_account(Path(path))

    def import_private_account(self, path):
        if self.proc is not None:return
        try:
            account=json.loads(Path(path).read_text(encoding='utf-8-sig'))
            uid=str(account['uid'])
            if not uid.isdecimal() or not isinstance(account.get('cookies'),dict):raise ValueError()
            if not all(account['cookies'].get(k) for k in ('Pauth','Uauth','Xauth','USESSIONID')):raise ValueError()
            # 沿用现有账号凭据格式；不复制二级密码等额外字段。
            saved={k:account[k] for k in ('uid','username','cookies')}
            folder=HERE/'union_accounts';folder.mkdir(exist_ok=True)
            target=folder/(uid+'.json');tmp=target.with_suffix('.tmp')
            tmp.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(target)
            self.refresh()
            self.account.set('专用 · '+uid)
            existing=next((row for row in self.jobs.values() if row['uid']==uid),None)
            if existing is not None:
                existing['path']=str(target.resolve());self.save_selection()
            else:self.add_path(target)
            self.messages.put('账号已保存到多账号专用目录，未加入主工具箱账号列表。')
        except (OSError,ValueError,KeyError,TypeError):
            messagebox.showerror('导入失败','请选择有效的工具箱账号文件；专用账号没有写入主程序目录。')

    def add_path(self, path):
        if self.proc is not None:
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            uid = str(data["uid"])
            cookies = data["cookies"]
            if not all(cookies.get(k) for k in ("Pauth", "Uauth", "Xauth", "USESSIONID")):
                raise ValueError()
            slot = int(self.slot.get())
            existing=next((key for key,row in self.jobs.items() if row['uid']==uid),None)
            if existing is not None:
                row=self.jobs[existing]
                changed=row['slot']!=slot
                row.update(path=str(path.resolve()),slot=slot)
                row.pop('session_account',None)
                if changed:row.pop('garden_password',None)
                self.table.item(existing,values=(data.get('username',uid),slot))
                self.save_selection()
                self.messages.put('该账号已在列表，已更新槽位为%s；没有重复添加。'%slot)
                return
            item = self.table.insert("", "end", values=(data.get("username", uid), slot))
            self.jobs[item] = {"path": str(path.resolve()), "slot": slot, "uid": uid}
            self.save_selection()
            self.apply_dog_filter()
        except Exception:
            messagebox.showerror("账号不可用", "请选择工具箱保存的账号JSON文件；登录失效时需重新登录并保存。")

    def restore_known_slots(self):
        if self.proc is not None:return
        count=0;new=0
        for key,row in self.jobs.items():
            history=self.account_history.get(row['uid'])
            if history is None:new+=1;continue
            slot=history.get('slot')
            if type(slot) is not int or not 0<=slot<=7:continue
            if row['slot']!=slot:
                row['slot']=slot;row.pop('garden_password',None);self.dog_overview.pop(key,None)
                values=list(self.table.item(key,'values'));values[1]=slot
                self.table.item(key,values=values[:2]);count+=1
        self.apply_dog_filter();self.save_selection()
        self.messages.put('当前名单已恢复%s个旧槽位；%s个旧名单外账号保留当前槽位。未新增账号、未登录游戏。'%(count,new))

    def remove(self):
        if self.proc is not None:
            return
        for item in self.table.selection():
            self.jobs.pop(item, None)
            self.table.delete(item)
        self.save_selection()

    def set_garden_password(self):
        if self.proc is not None: return
        selected = self.table.selection()
        if len(selected) != 1:
            messagebox.showerror("选择账号", "请在列表中选择一个账号。")
            return
        password = simpledialog.askstring("二级密码", "输入此账号的二级密码（仅当前窗口使用）：", show="*", parent=self.root)
        if password is not None:
            self.jobs[selected[0]]['garden_password'] = password

    def start(self, garden_operation=None, action_override=None, job_keys=None):
        if self.proc is not None:
            return
        exec_jobs=self.jobs if job_keys is None else {key:self.jobs[key] for key in job_keys if key in self.jobs}
        if not exec_jobs:
            messagebox.showerror("缺少账号", "请先添加执行账号和存档。")
            return
        args = ([sys.executable, "--worker", "union_boss_batch.py"]
                if getattr(sys, "frozen", False) else
                [sys.executable, "-u", str(HERE / "union_boss_batch.py")])
        action = action_override or ("garden" if garden_operation else self.action.get())
        args.extend(["--action", action])
        if action=='dog_activate':
            selected=[int(k.rsplit('_',1)[1]) for k,v in self.dog_activation.items() if v.get()]
            if not selected:
                messagebox.showerror('未选择狗卡','请至少选择一种狗卡');return
            if not messagebox.askyesno('确认激活','对列表中全部账号激活所选狗卡；每种消耗1张，已激活或缺卡跳过。继续？',parent=self.root):return
            for n in selected:args+=['--dog-activate',str(n)]
        single_secret=''
        if action in ('dog_redeem','dog_gift','dog_gift_draw','dog_single_activate'):
            if len(exec_jobs)!=1:messagebox.showerror('选择账号','请只选中一个账号');return
            from union_boss_batch import DOG_NAMES
            card=DOG_NAMES.index(self.single_card.get())+1
            single_secret=self.single_code.get().strip() if action=='dog_redeem' else ''
            if action=='dog_redeem' and not single_secret:messagebox.showerror('缺少兑换码','请填写兑换码');return
            key=next(iter(exec_jobs));label=str(self.table.item(key,'values')[0])
            title={'dog_redeem':'使用兑换码','dog_gift':'仅生成赠送码（消耗1张余卡，不抽卡）','dog_gift_draw':'生成码并额外抽卡','dog_single_activate':'激活所选卡种（消耗1张，已激活或缺卡跳过）'}[action]
            if not messagebox.askyesno('确认单账号操作',label+' / 槽'+str(exec_jobs[key]['slot'])+'\n'+title+'\n卡种：'+DOG_NAMES[card-1],parent=self.root):return
            args+=['--chain-card',str(card)]
        chain_secret=''
        if action=='dog_chain':
            from union_boss_batch import DOG_NAMES
            card=DOG_NAMES.index(self.chain_card.get())+1;mode='code' if self.chain_seed.get()=='输入兑换码' else 'inventory'
            chain_secret=self.chain_code.get().strip() if mode=='code' else ''
            if mode=='code' and not chain_secret:messagebox.showerror('缺少起始码','请输入兑换码或选择库存余卡启动');return
            preview='\n'.join(str(self.table.item(key,'values')[0])+' / 槽'+str(row['slot']) for key,row in exec_jobs.items())
            if not messagebox.askyesno('确认当前筛选名单接力','卡种：%s\n%s\n逐号核查后串行领取、转赠、额外抽一次；未激活或今日已参与的跳过；不新增激活或购买。继续？'%(self.chain_card.get(),preview),parent=self.root):return
            args+=['--chain-card',str(card),'--chain-seed',mode]
        buying = False
        if action == "garden":
            pick = garden_operation == "pick" if garden_operation else self.garden_pick.get()
            uproot = garden_operation == "uproot" if garden_operation else self.garden_uproot.get()
            plant = self.garden_seeds[self.garden_seed.get()] if garden_operation in (None, "plant") else 0
            if garden_operation == "plant" and not plant:
                messagebox.showerror("选择种子", "请先选择要种植的种子。")
                return
            try:
                count = int(self.garden_count.get())
                if count < 0: raise ValueError()
            except ValueError:
                messagebox.showerror("数量无效", "种植数量须为非负整数，0表示全部空地。")
                return
            buying = bool(plant and self.garden_mode.get() == "buy")
            if buying and any(not row.get('garden_password') for row in exec_jobs.values()):
                messagebox.showerror("缺少二级密码", "请为每个执行账号设置二级密码。")
                return
            if pick: args.append("--garden-pick")
            if uproot: args.append("--garden-uproot")
            args.extend(["--garden-plant", str(plant), "--garden-mode", self.garden_mode.get(), "--garden-count", str(count)])
        if action == "boss":
            raw = self.dps.get().strip()
            if raw:
                try:
                    number = float(raw)
                    if not math.isfinite(number) or number <= 0:
                        raise ValueError()
                except ValueError:
                    messagebox.showerror("伤害无效", "每秒期望伤害须为大于0的数字，或留空自动计算。")
                    return
                args.extend(["--expected-dps", str(number)])
            if self.idle.get():
                args.append("--idle-after-02")
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as stream:
                self.batch_path = Path(stream.name)
                json.dump([{"path": row["path"], "slot": row["slot"], "uid": row["uid"]} for row in exec_jobs.values()], stream)
            args.extend(["--batch-file", str(self.batch_path)])
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            env["ZM5_DOG_REDEEM_CODE"]=single_secret
            if action=="dog_redeem":self.single_code.set('')
            env["ZM5_DOG_CHAIN_CODE"]=chain_secret
            if action=="dog_chain":self.chain_code.set('')
            env["ZM5_UNION_BATCH_ACCOUNTS"] = json.dumps({row["uid"]:row["session_account"] for row in exec_jobs.values() if row.get("session_account")})
            env["ZM5_UNION_BATCH_PASSWORDS"] = json.dumps({row["uid"]:row.get("garden_password", "") for row in exec_jobs.values()} if buying else {})
            self.proc = subprocess.Popen(args, cwd=HERE, env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            self.cleanup()
            messagebox.showerror("启动失败", "无法启动执行程序，请检查程序文件是否齐全。")
            return
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.messages.put("开始并行执行，共%s个账号。" % len(exec_jobs))
        threading.Thread(target=self.read_output, args=(self.proc,), daemon=True).start()

    def read_output(self, proc):
        for line in proc.stdout:
            self.messages.put(line.rstrip())
        code = proc.wait()
        self.messages.put(("done", code))

    def cleanup(self):
        if self.batch_path:
            self.batch_path.unlink(missing_ok=True)
            self.batch_path = None

    def poll(self):
        try:
            while True:
                message = self.messages.get_nowait()
                if isinstance(message,str) and message.startswith('__UNION_DOG_CODES__'):
                    try:self.show_server_codes(json.loads(message[len('__UNION_DOG_CODES__'):]))
                    except (ValueError,TypeError,KeyError):self.messages.put('服务器兑换码结果格式异常')
                    continue
                if isinstance(message,str) and message.startswith('__UNION_DOG_OVERVIEW__'):
                    try:self.render_dog_overview(json.loads(message[len('__UNION_DOG_OVERVIEW__'):]))
                    except Exception:self.messages.put('狗卡总览显示失败，请重新查询。')
                    continue
                if isinstance(message, tuple) and message[0] == 'callback':
                    message[1]()
                    continue
                if isinstance(message, tuple):
                    self.proc = None
                    self.cleanup()
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    message = "执行结束，返回码：%s" % message[1]
                self.log.configure(state="normal")
                self.log.insert("end", str(message) + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.messages.put("已停止全部账号连接。")

    def close(self):
        self.stop()
        if self.proc is not None:
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.cleanup()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    UnionBatchWindow(root)
    root.mainloop()
