"""收藏任务策略摘要：只读界面变量，不查询服务器、不展示密码。"""
import tkinter as tk

def value(obj,name,default='未设置'):
    var=getattr(obj,name,None)
    if var is None:return default
    result=var.get()
    return result if result!='' else default

def summary(app,key,modules=None):
    try:return describe(app,key,modules or {})
    except (AttributeError,KeyError,ValueError,TypeError,tk.TclError):return '设置尚未完善，请打开原页面检查'

def describe(app,key,modules):
    row=modules.get(key,{});page=row.get('page','')
    if key in ('RUN_ARENA','RUN_PET_ARENA'):
        from arena_target_ui import MODE_CHOICES
        prefix='var_arena' if key=='RUN_ARENA' else 'var_pet_arena'
        mode=value(app,prefix+'_mode');parts=[dict(MODE_CHOICES).get(mode,str(mode))]
        if mode=='rank_random':parts.append('前%s名随机'%value(app,prefix+'_top_n'))
        if mode=='specified':
            direct=value(app,prefix+'_target_input')=='rid'
            parts.append('RID '+str(value(app,prefix+'_target_rid')) if direct else 'UID %s，r值%s'%(value(app,prefix+'_target_uid'),value(app,prefix+'_target_r_number')))
        if mode=='borrowed':parts.append('借用槽%s'%value(app,prefix+'_borrow_slot'))
        parts.append('%s局'%value(app,prefix+'_target_rounds') if mode in ('rank_highest','rank_random','specified','borrowed') else '当天剩余免费次数')
        parts.append('局内%s秒／局间%s秒'%(value(app,prefix+'_battle_wait'),value(app,prefix+'_round_wait')))
        return '｜'.join(parts)
    if key=='RUN_FREE_MAZE':
        p=app.maze_target_controls
        mode='指定码 '+str(value(p,'code')) if value(p,'mode')=='指定迷宫' else ('高通关率，连续同一迷宫' if value(p,'rate_mode')=='high' else '低通关率，每次不同迷宫')
        return '%s｜补足每日3次｜结算等待%s秒'%(mode,value(p,'wait'))
    if key in ('RUN_FUN_CARD_CAVE','RUN_CARD_CAVE'):
        p=app.card_cave_target_page
        return '%s｜%s局｜等待%s秒'%(value(p,'mode'),value(p,'count'),value(p,'wait'))
    if key=='RUN_FUN_BLACK_MARKET':return '仅购买灵魂商品，使用VIP剩余免费刷新次数'
    if key=='RUN_FUN_MONSTER_CARD':return '免费抽取%s次'%value(app.pet_utility_page,'card_count')
    if key in ('RUN_FUN_COLLECT_REWARD','RUN_FUN_COLLECT_START'):
        p=app.pet_utility_page
        return '位置%s｜普通领取'%value(p,'pos') if key.endswith('REWARD') else '位置%s｜%s｜%s'%(value(p,'pos'),value(p,'material'),value(p,'gear'))
    if key=='RUN_FUN_FAIRY_FEED':
        p=app.fairy_feed_panel
        return '%s｜%s｜%s喂养｜%s'%(value(p,'display'),value(p,'role'),value(p,'kind'),'至最大次数' if not p.times.get().strip() else str(p.times.get())+'次')
    if key=='RUN_FAIRY_REWARD':
        p=app.fairy_preferences;parts=['先领奖再派遣',str(value(app,'var_fairy_daily_scope'))]
        if p.enabled.get():
            parts.append(p.strategy.get())
            parts.extend('%s：%s'%(i+1,' → '.join(group)) for i,group in enumerate(p.groups) if group)
            parts.append('允许其他任务补位' if p.fill.get() or p.value()['strategy']==2 else '不额外补位')
        else:parts.append('未启用奖励偏好')
        return '｜'.join(parts)
    if key=='RUN_WISH_POOL_RANDOM':return '随机3池，各10次' if value(app.wish_pool_panel,'mode')=='随机许愿' else '手动许愿模式：此项目跳过'
    if key=='RUN_HALO':return str(value(app,'var_halo_score'))
    if key=='RUN_DEMON_TOWER2':return str(value(app,'var_tower_range'))
    if key=='RUN_MANHUANG':return '%s｜%s'%(value(app,'var_mh_stage'),value(app,'var_mh_mode'))
    if key=='RUN_FOREST':
        mode=value(app,'var_forest_mode')
        return {'sweep':'速通扫荡','manual':'固定关卡手打','preview':'仅预览材料'}.get(mode,str(mode))
    if key=='RUN_MODULE_FAIRY_SHOP_SELECTED':
        p=app.pet_utility_page;goods=[p.goods[sid]['name']+'×'+str(row['count'].get()) for sid,row in p.shop_rows.items() if row['selected'].get()]
        return '；'.join(goods) if goods else '尚未勾选购买商品'
    if page=='斗神/乱斗':
        pvp='开始斗神挂机' in row['label']
        return '北京时间%s｜匹配%s场'%('12:00–14:00、19:00–21:00' if pvp else '12:00–14:00、20:00–22:00',value(app,'var_pvp_matches' if pvp else 'var_pet_brawl_matches'))
    if page=='BOSS挑战':
        if key=='RUN_MODULE_WORLD_ROOM':return '沿用包房窗口的账号分工、伤害和挂机设置'
        prefix='var_union' if '联盟' in row['label'] else 'var_world'
        return '目标占比%s%%｜%s｜%s'%(value(app,prefix+'_target'),'达标后挂机' if value(app,prefix+'_idle',False) else '达标后按原流程','每秒期望伤害'+str(value(app,prefix+'_dps','自动')))
    if page=='通天河':
        if row['label'].endswith('发船'):return '%s｜自动选最低等级≥40存档'%value(app,'var_ttr_escort_strategy')
        if row['label'].endswith('执行领奖'):return '领奖存档：槽%s'%(app.var_ttr_slots['reward'].get() or '未设置，选择抢船存档后自动跟随')
        if row['label'].endswith('执行抢船'):return ('仅满额等级奖励｜' if value(app,'var_ttr_full_reward',True) else '允许等级折扣｜')+'%s｜%s｜结算等待%s秒'%('仅海舰' if value(app,'var_ttr_target_mode')=='sea_only' else '优先海舰','仅选中灵气' if value(app,'var_ttr_qi_only',False) else '不筛选货物',value(app,'var_ttr_battle_wait'))
        return '沿用通天河原页面对应操作的存档设置'
    if page=='一键刷图':return '%s｜%s次｜场景等待%s秒／Boss等待%s秒'%(value(app,'var_farm_stage'),value(app,'var_farm_times'),value(app,'var_farm_base_delay'),value(app,'var_farm_boss_delay'))
    if page=='时光之舟':return '%s｜兑换%s次'%(value(app,'var_timeboat_choice'),value(app,'var_timeboat_times')) if '兑换' in row['label'] else '使用原页面设置的时光水晶数量'
    return ''
