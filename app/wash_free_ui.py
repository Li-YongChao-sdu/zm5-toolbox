"""VIP免费洗练：各系统独立目标、设置和执行入口。"""
import tkinter as tk
from tkinter import ttk, messagebox
from wash_data import can_lock, auto_replace, five_elements_text
SYSTEMS = {'法宝':'magic','灵符':'rune','羽毛':'feather','精魄':'jingpo','阵眼':'zhenyan'}

ATTR_NAMES = {'hpMax':'生命','mpMax':'魔法','atk':'攻击','phyDef':'防御','hit':'命中',
              'dodge':'闪避','critical':'暴击','toughness':'韧性','lucky':'幸运',
              'guardian':'守护','reHP':'回血','reMP':'回魔'}

def build(parent, frame, field, button, app=None):
    ttk.Label(parent, text='仅使用VIP剩余免费次数，不自动购买材料。').pack(anchor='w', pady=6)
    tabs = ttk.Notebook(parent)
    tabs.pack(fill='both', expand=True)
    sections = {}
    for title, key in SYSTEMS.items():
        sections[key] = build_section(tabs, title, key, frame, field, button, app)
    if app is not None:
        def tick():
            for section in sections.values():
                if section["signature"] is not None and section["signature"] != signature(app):clear(section)
            if parent.winfo_exists():parent.after(250,tick)
        parent.after(250,tick)
    return sections

def build_section(tabs, title, key, frame, field, button, app=None):
    page = ttk.Frame(tabs, padding=6)
    tabs.add(page, text=title)
    hint = '免费洗练直接替换当前词条。' if auto_replace(key) else '查询目标及免费配额后，按本页设置执行一次并处理结果。'
    if key=='rune':hint='洗练后先对比原属性与新属性，再选择保存新属性或保留原属性。'
    box = frame(page, 'VIP免费洗练／'+title, hint)
    choice = tk.StringVar(master=box)
    target = tk.StringVar(master=box)
    quota = tk.StringVar(master=box, value='请先刷新当前存档的目标列表')
    ttk.Label(box, textvariable=quota).pack(anchor='w', pady=4)
    combo = ttk.Combobox(box, textvariable=choice, state='readonly', width=65)
    combo.pack(anchor='w', pady=4)
    section = {'choice':choice,'combo':combo,'quota':quota,'objects':{},'signature':None,'target':target}
    detail = tk.StringVar(master=box)
    if key == 'rune':ttk.Label(box, textvariable=detail, wraplength=750, justify='left').pack(anchor='w', pady=5)
    section['detail']=detail;section['rows']={}
    lock_frame = None
    lock_vars = {}
    if can_lock(key):
        ttk.Label(box, text='锁定词条：选中目标后勾选要保留的属性（最多锁定 n-1 个）').pack(anchor='w', pady=2)
        lock_frame = ttk.Frame(box)
        lock_frame.pack(anchor='w', pady=2)
    section['lock_vars']=lock_vars
    section['lock_frame']=lock_frame
    def _attr_list(row):
        if not row:return []
        a = row.get('lockable')
        if a:return a
        a = row.get('attributes')
        return a if isinstance(a, list) else [x for x in str(a or '').split(';') if x]
    def select(*_):
        target.set(section['objects'].get(choice.get(), ''))
        row=section['rows'].get(target.get())
        detail.set(rune_detail(row) if key=='rune' and row else '')
        if lock_frame is not None:
            for w in lock_frame.winfo_children():
                w.destroy()
            lock_vars.clear()
            attrs = _attr_list(row)
            values = (row or {}).get('attributeValues') or {}
            ranges = (row or {}).get('attrRanges') or {}
            max_lock = max(len(attrs) - 1, 0)
            def make_toggle(attr):
                def toggle():
                    if sum(1 for v in lock_vars.values() if v.get()) > max_lock:
                        lock_vars[attr].set(False)
                        messagebox.showinfo('锁定限制',
                            '该目标共 %d 个词条，最多锁定 %d 个（需留 1 个给洗练随机）。' % (len(attrs), max_lock),
                            parent=box.winfo_toplevel())
                return toggle
            for i, attr in enumerate(attrs):
                var = tk.BooleanVar(master=box, value=False)
                lock_vars[attr] = var
                label = ATTR_NAMES.get(attr, attr)
                v = values.get(attr)
                if v is not None:
                    rng = ranges.get(attr)
                    if rng:
                        lo, hi = rng
                        try:
                            cur_f = float(v)
                            span = hi - lo
                            pct = int((cur_f - lo) / span * 100) if span > 0 else 0
                            label += '  %s/%s (%d%%)' % (v, int(hi), pct)
                        except (TypeError, ValueError):
                            label += '  %s' % v
                    else:
                        label += '  %s' % v
                ttk.Checkbutton(lock_frame, text=label, variable=var, command=make_toggle(attr)).grid(row=i//2, column=i%2, sticky='w', padx=8, pady=1)
    choice.trace_add('write',select)
    password = field(box, '二级密码（未设置可留空）', secret=True)
    keep = None if auto_replace(key) or key in ('rune','jingpo','zhenyan') else field(box, '结果处理', '保存新词条', ['保存新词条','保留旧词条'])
    def args(apply=False):
        argv = ['--system',key]
        if app is not None:
            slot = int(app.cmb_slot.get())
            if not 0 <= slot <= 7:raise ValueError('请先选择有效的存档槽位')
            argv += ['--slot',str(slot)]
        if apply and app is not None and section['signature'] != signature(app):
            clear(section)
            raise ValueError('账号或存档已变化，请重新刷新目标列表')
        value = target.get().strip()
        if value:argv += ['--target',value]
        elif apply:raise ValueError('请先刷新'+title+'列表并从下拉框选择目标')
        if lock_frame is not None:
            locked = [attr for attr, var in lock_vars.items() if var.get()]
            if locked:argv += ['--lock', ','.join(locked)]
        if keep is not None and keep.get()=='保留旧词条':argv += ['--keep']
        if apply:
            argv += ['--apply','--exact-target','--password',password.get()]
            argv += ['--review-result']
        else:argv += ['--list']
        return argv
    button(box, '刷新配额与目标列表', 'wash_run.py', lambda:args(False))
    button(box, '免费洗练并查看结果', 'wash_run.py', lambda:args(True))
    section.update(page=page,password=password,locks=None,keep=keep,args=args)
    return section

def signature(app):
    try:return (getattr(app,'_account_view_epoch',0),int(app.cmb_slot.get()))
    except (ValueError,tk.TclError):return None

def clear(section):
    section['objects']={};section['rows']={};section['detail'].set('');section['combo'].configure(values=())
    section['choice'].set('');section['target'].set('');section['signature']=None
    section['quota'].set('请刷新当前存档的目标列表')
    if section.get('password') is not None:section['password'].set('')
    lf = section.get('lock_frame')
    if lf is not None:
        for w in lf.winfo_children():w.destroy()
    lv = section.get('lock_vars')
    if lv is not None:lv.clear()

def render(app, payload):
    current=signature(app)
    if current is None or payload.get('slot')!=current[1]:return
    status=payload['status']
    for key, section in app.free_wash_sections.items():
        previous=section['target'].get() if section['signature']==current else ''
        objects={}
        for row in status['candidates'].get(key,[]):
            eid=str(row['entityId']);name=str(row.get('name') or row.get('id') or '未命名')
            label=name+(' | 战力 '+str(row['fightPower']) if key=='rune' and row.get('fightPower') is not None else '')+' | '+eid
            loc = row.get('location') or row.get('pos')
            if loc and key in ('rune','feather'):label += ' | '+loc
            objects[label]=eid
        section['rows']={str(row['entityId']):row for row in status['candidates'].get(key,[])}
        section['objects']=objects;section['combo'].configure(values=list(objects))
        section['signature']=current
        section['choice'].set(next((label for label,eid in objects.items() if eid==previous),''))
        q=status['quota'].get(key,{})
        section['quota'].set('VIP%s · 免费可用 %s/%s · 目标 %s 个'%(status['vip'],q.get('freeLeft',0),q.get('freeTotal',0),len(objects)))


def rune_detail(row):
    attrs=row.get('attributeValues') or {}
    values=['%s %s'%(ATTR_NAMES[key],attrs[key]) for key in ATTR_NAMES if key in attrs]
    power=row.get('fightPower')
    title='单件综合战力：'+str(power)+'（按客户端配置计算）' if power is not None else '单件综合战力：未取得'
    location='位置：'+str(row['location'])+'\n' if row.get('location') else ''
    return location+title+'\n'+'；'.join(values)


def magic_detail(row):
    """法宝洗练结果：突出五行，仅保留成长率。"""
    if not isinstance(row, dict):
        return ''
    fe=row.get('fiveElements')
    line_fe='五行：【%s】' % (five_elements_text(fe) if fe else '无')
    extras=[]
    if row.get('growthRate') is not None: extras.append('成长率=%s'%row['growthRate'])
    parts=[line_fe]
    if extras: parts.append('；'.join(extras))
    return '\n'.join(parts)


def feather_detail(row):
    """羽毛属性展示：当前值/最大值（百分比占比）。

    百分比占比 = (当前值 - 最低值) / (最大值 - 最低值)
    """
    if not isinstance(row, dict):
        return ''
    attrs = row.get('attributeValues') or {}
    ranges = row.get('attrRanges') or {}
    parts = []
    for k in ATTR_NAMES:
        if k not in attrs or not attrs[k]:
            continue
        name = ATTR_NAMES[k]
        cur = attrs[k]
        rng = ranges.get(k)
        if rng:
            lo, hi = rng
            try:
                cur_f = float(cur)
            except (TypeError, ValueError):
                parts.append('%s %s' % (name, cur))
                continue
            span = hi - lo
            pct = (cur_f - lo) / span * 100 if span > 0 else 0
            parts.append('%s %s/%s (%d%%)' % (name, cur, int(hi), int(pct)))
        else:
            parts.append('%s %s' % (name, cur))
    return '；'.join(parts)


def formation_detail(row):
    """精魄/阵眼属性展示：当前值/最大值（百分比占比）。

    old row（来自 list_formation_items）只有 lockable（属性名）+ attrRanges，没有当前值；
    new node（洗练回包 newFlag/formationFlag）带属性字段值。
    百分比占比 = (当前值 - 最低值) / (最大值 - 最低值)
    """
    if not isinstance(row, dict):
        return ''
    attrs = row.get('attributeValues') or {}
    lockable = row.get('lockable') or []
    ranges = row.get('attrRanges') or {}
    # 属性名列表：优先 lockable，其次 attributeValues 的 key
    keys = lockable if lockable else list(attrs.keys())
    parts = []
    for k in keys:
        name = ATTR_NAMES.get(k, k)
        cur = attrs.get(k) if attrs else row.get(k)
        rng = ranges.get(k)
        if cur is None or cur == '':
            # 没有当前值（old row），只显示属性名和最大值
            if rng:
                parts.append('%s -/%s' % (name, int(rng[1])))
            else:
                parts.append('%s' % name)
            continue
        if rng:
            lo, hi = rng
            try:
                cur_f = float(cur)
            except (TypeError, ValueError):
                parts.append('%s %s' % (name, cur))
                continue
            span = hi - lo
            pct = int((cur_f - lo) / span * 100) if span > 0 else 0
            parts.append('%s %s/%s (%d%%)' % (name, cur, int(hi), pct))
        else:
            parts.append('%s %s' % (name, cur))
    return '；'.join(parts)


def review(app,payload):
    import json
    action='defer'
    mode=payload.get('mode','confirm')
    system=payload.get('system','rune')
    current=signature(app)
    if current is not None and payload.get('slot')==current[1]:
        name=payload.get('name','洗练')
        if mode=='info':
            if system=='feather':
                text='%s\n\n洗练结果（已自动替换，无法回退）\n%s'%(name, feather_detail(payload.get('new')))
                messagebox.showinfo('羽毛洗练结果', text, parent=app.root)
            else:
                text='%s\n\n洗练结果（已自动替换，无法回退）\n%s'%(name, magic_detail(payload.get('new')))
                messagebox.showinfo('法宝洗练结果', text, parent=app.root)
            if signature(app)==current:
                action='ack'
        else:
            if system=='feather':
                text='%s\n\n原属性\n%s\n\n洗练结果\n%s\n\n是：保存新属性（替换原属性）\n否：保留原属性\n取消：暂不处理'%(name,feather_detail(payload['old']),feather_detail(payload['new']))
                decision=messagebox.askyesnocancel('羽毛洗练结果',text,parent=app.root)
            elif system in ('jingpo','zhenyan'):
                title='精魄洗练结果' if system=='jingpo' else '阵眼洗练结果'
                text='%s\n\n原属性\n%s\n\n洗练结果\n%s\n\n是：保存新属性（替换原属性）\n否：保留原属性\n取消：暂不处理'%(name,formation_detail(payload['old']),formation_detail(payload['new']))
                decision=messagebox.askyesnocancel(title,text,parent=app.root)
            else:
                text='%s\n\n原属性\n%s\n\n洗练结果\n%s\n\n是：保存新属性（替换原属性）\n否：保留原属性\n取消：暂不处理'%(name,rune_detail(payload['old']),rune_detail(payload['new']))
                decision=messagebox.askyesnocancel('灵符洗练结果',text,parent=app.root)
            if signature(app)==current:
                action='replace' if decision is True else 'keep' if decision is False else 'defer'
    reply={'token':payload['token'],'slot':payload['slot'],'entityId':payload['entityId'],'action':action}
    proc=getattr(app,'proc',None)
    if proc is None or proc.poll() is not None or proc.stdin is None:raise RuntimeError('洗练进程已结束，未发送确认；请回游戏检查结果')
    proc.stdin.write(json.dumps(reply,ensure_ascii=False)+'\n');proc.stdin.flush()
