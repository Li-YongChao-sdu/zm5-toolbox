"""我的日常完整非点券模块库：调用原页面命令，共用校验和设置。"""

import hashlib

import tkinter as tk

from tkinter import ttk



# 查询、筛选、导入和设置按钮不是执行项目；同一流程已有 RUN 开关时不重复列出。

ACTIONS={

 '活动副本':{'领取所选免费奖励','挑战至第13层','领取已达成奖励（至13层）'},

 '斗神/乱斗':{'开始匹配挂机','开始斗神挂机'},

 'BOSS挑战':{'开始世界 Boss','开始联盟 Boss'},

 '通天河':{'发船','执行领奖','执行抢船'},







 '联盟仓库':{'购买选中材料'},











 '邮件':{'领取选中邮件附件并删除'},

}



def descendants(widget):

    for child in widget.winfo_children():

        yield child

        yield from descendants(child)



def discover(app):

    """按原页面归组；只绑定明确列出的业务命令，不猜测按钮的付费属性。"""

    result={};pages={};roots=[]

    def visit(notebook):

        for tab in notebook.tabs():

            title=notebook.tab(tab,'text');title={'世界／联盟Boss':'BOSS挑战'}.get(title,title)

            page=notebook.nametowidget(tab)

            if title in ACTIONS:roots.append((title,page))

            else:

                for child in descendants(page):

                    if isinstance(child,ttk.Notebook):visit(child)

    visit(app.main_notebook)

    for title,root in roots:

        counts={}

        for button in descendants(root):

            if not isinstance(button,(tk.Button,ttk.Button)):continue

            text=str(button.cget('text'))

            if text not in ACTIONS.get(title,set()):continue
            if title=='活动副本' and text=='领取所选免费奖励':
                from national_day_wish import choices_for,today_key
                if not choices_for(today_key()):continue

            context=[];parent=button.master

            while parent is not root:

                if isinstance(parent,(ttk.LabelFrame,tk.LabelFrame)):

                    value=str(parent.cget('text')).lstrip('▾▸ ').strip()

                    if value:context.insert(0,value)

                parent=parent.master

                if parent is None:break

            name=' / '.join(context+[text]);counts[name]=counts.get(name,0)+1

            identity=f'{title}/{name}/{counts[name]}'

            key='RUN_MODULE_'+hashlib.sha256(identity.encode()).hexdigest()[:16].upper()

            label=name if name!=text else text

            if text=='购买所选商品（1次）':label=label.replace(text,'购买所选非点券商品（1次）')
            if title=='斗神/乱斗':label+='（12–14；19–21）' if text=='开始斗神挂机' else '（12–14；20–22）'

            result[key]={'label':label,'page':title,'command':button.invoke,'button':button,'context':context}

            pages.setdefault(title,[]).append(key)

    def room():

        panel=app.world_boss_room_page

        if panel.window is None or not panel.window.winfo_exists():

            panel.open();raise ValueError('请先配置并查询世界boss包房，再执行')

        panel.launch('run')

    result['RUN_MODULE_WORLD_ROOM']={'label':'世界boss包房','page':'BOSS挑战','command':room,'visible':app.world_boss_room_page.unlocked}

    pages.setdefault('BOSS挑战',[]).append('RUN_MODULE_WORLD_ROOM')

    return result,pages



def check_non_ticket(app,row):

    if row['page']=='刷去益灵花' and row['label'].endswith('购买所选非点券商品（1次）'):

        from old_shop import requires_ticket

        panel=app.old_activity_page;selected=panel.goods.selection()

        if not selected:raise ValueError('请先在旧活动商店选择非点券商品')

        if requires_ticket(panel.shops[selected[0]]):raise ValueError('我的日常不执行点券商品')



