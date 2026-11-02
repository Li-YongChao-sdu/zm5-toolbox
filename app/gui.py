from activity_availability import disabled_reason



# -*- coding: utf-8 -*-



"""一键日常 GUI — 勾选关卡、设次数、跑日常。



运行: python gui.py



"""



import os, sys, json, re, threading, subprocess, queue, base64, math



from datetime import datetime, timedelta, timezone



import tkinter as tk



from tkinter import ttk, scrolledtext, messagebox



from game_version import GAME_VERSION, XIE_ROLE_SWITCHES, active_xie_names, active_xie_switches







# 账密本地加密存储 (AES-GCM)



try:



    from Crypto.Cipher import AES



    from Crypto.Hash import SHA256



    from Crypto.Random import get_random_bytes



    HAS_CRYPTO = True



except Exception:



    HAS_CRYPTO = False







PWD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.pwd")



_PWD_KEY = SHA256.new(b"zm-daily-v3-local").digest() if HAS_CRYPTO else None







def _enc_pwd(s):



    if not HAS_CRYPTO:



        return s



    nonce = get_random_bytes(12)



    c = AES.new(_PWD_KEY, AES.MODE_GCM, nonce=nonce)



    ct, tag = c.encrypt_and_digest(s.encode("utf-8"))



    return base64.b64encode(nonce + tag + ct).decode("ascii")







def _dec_pwd(s):



    if not HAS_CRYPTO:



        return s



    try:



        raw = base64.b64decode(s)



        nonce, tag, ct = raw[:12], raw[12:28], raw[28:]



        c = AES.new(_PWD_KEY, AES.MODE_GCM, nonce=nonce)



        return c.decrypt_and_verify(ct, tag).decode("utf-8")



    except Exception:



        return ""







def load_credentials():



    if not HAS_CRYPTO or not os.path.exists(PWD_FILE):



        return {}



    try:



        with open(PWD_FILE, encoding="utf-8") as f:



            data = json.load(f)



        return {u: _dec_pwd(p) for u, p in data.items()}



    except Exception:



        return {}







def save_credential(username, password):



    try:



        creds = load_credentials()



        creds[username] = password



        with open(PWD_FILE, "w", encoding="utf-8") as f:



            json.dump({u: _enc_pwd(p) for u, p in creds.items()}, f, ensure_ascii=False)



        return True



    except Exception:



        return False







HERE = os.path.dirname(os.path.abspath(__file__))



ACCOUNT_FILE = os.path.join(HERE, "account.local.json")


HALO_TEAM_CONFIG = os.path.join(HERE, "halo_team.json")


MANHUANG_TEAM_CONFIG = os.path.join(HERE, "manhuang_team.json")







with open(os.path.join(HERE, "stage_names.json"), encoding="utf-8") as _f:



    _SN = json.load(_f)



for _k in _SN:



    _SN[_k] = list(reversed(_SN[_k]))



with open(os.path.join(HERE, "elite_stages.json"), encoding="utf-8") as _f:



    _ELITE_STAGES = list(reversed(json.load(_f)))



with open(os.path.join(HERE, "elite_daily_tasks.json"), encoding="utf-8-sig") as _f:



    _ELITE_DAILY_TASKS = {int(row["id"]): row for row in json.load(_f)}



with open(os.path.join(HERE, "main_custom_stages.json"), encoding="utf-8") as _f:



    _MAIN_CUSTOM_STAGES = list(reversed(json.load(_f)))



with open(os.path.join(HERE, "main_boss_routes.json"), encoding="utf-8") as _f:



    _MAIN_BOSS_ROUTES = json.load(_f)

# 成长挑战任务/积分档位配置（缺失时不影响启动，只显示 qId）
_GC_DIR = os.path.join(HERE, "cg_config_out_cg1_20261019_1")
try:
    with open(os.path.join(_GC_DIR, "GrowthChallengeTask.json"), encoding="utf-8") as _f:
        _GROWTH_TASK_CFG = json.load(_f)
except Exception:
    _GROWTH_TASK_CFG = {}
try:
    with open(os.path.join(_GC_DIR, "GrowthChallengeReward.json"), encoding="utf-8") as _f:
        _GROWTH_REWARD_CFG = json.load(_f)
except Exception:
    _GROWTH_REWARD_CFG = {}
try:
    with open(os.path.join(_GC_DIR, "Prop.json"), encoding="utf-8-sig") as _f:
        _PROP_CFG = json.load(_f)
except Exception:
    _PROP_CFG = {}
try:
    with open(os.path.join(_GC_DIR, "Reward.json"), encoding="utf-8-sig") as _f:
        _REWARD_CFG = json.load(_f)
except Exception:
    _REWARD_CFG = {}
try:
    with open(os.path.join(_GC_DIR, "GrowthHelper.json"), encoding="utf-8-sig") as _f:
        _GROWTH_HELPER_CFG = json.load(_f)
except Exception:
    _GROWTH_HELPER_CFG = {}


def _prop_name(prop_id):
    """道具 id → 名称（Prop.json）。"""
    row = _PROP_CFG.get(str(prop_id)) or {}
    return row.get("name") or ""


_COIN_LABELS = {
    'growthExp': '成长积分', 'haloMoney': '阵法币', 'worldBossMoney': '世界币',
    'bossMoney': '世界币', 'ticket': '点券', 'gold': '金币', 'silver': '银两',
    'blueDiamond': '蓝钻', 'honor': '荣誉', 'money': '银两',
}


def _split_reward_list(text):
    return [p.strip() for p in re.split(r'[;,]', str(text or '')) if p.strip()]


def growth_task_reward_text(qid):
    """任务奖励（GrowthChallengeTask.rewardId → Reward.json），如“成长积分×5、赤血石×10”。"""
    row = _GROWTH_TASK_CFG.get(str(qid)) or {}
    rw = _REWARD_CFG.get(str(row.get('rewardId'))) or {}
    subs = _split_reward_list(rw.get('subType'))
    cnts = _split_reward_list(rw.get('count'))
    parts = []
    for i, sub in enumerate(subs):
        cnt = cnts[i] if i < len(cnts) else '?'
        if sub.isdigit():
            name = _prop_name(sub) or sub
        else:
            name = _COIN_LABELS.get(sub, sub)
        parts.append('%s×%s' % (name, cnt))
    return '、'.join(parts)


def growth_vip_gift_text():
    """购买至尊特权时立即到账的道具（GrowthHelper 的 open_subType / open_count）。"""
    row = _GROWTH_HELPER_CFG.get("1") or {}
    ids = [p.strip() for p in str(row.get("open_subType") or "").split(",") if p.strip()]
    nums = [p.strip() for p in str(row.get("open_count") or "").split(",") if p.strip()]
    parts = []
    for i, pid in enumerate(ids):
        cnt = nums[i] if i < len(nums) else "1"
        parts.append("%s×%s" % (_prop_name(pid) or pid, cnt))
    return "、".join(parts)


_FASHION_SHOP_ITEMS = None


def fashion_shop_items():
    """玉珠商店商品：Shop.json 中消耗 dailyTaskMoney（玉珠）的条目。

    返回 [(shopId, 名称, 单价玉珠, 限购上限)]，限购 -1 表示不限购。
    """
    global _FASHION_SHOP_ITEMS
    if _FASHION_SHOP_ITEMS is None:
        try:
            with open(os.path.join(_GC_DIR, "Shop.json"), encoding="utf-8-sig") as _f:
                _shop = json.load(_f)
        except Exception:
            _shop = {}
        items = []
        for row in _shop.values():
            if "dailyTaskMoney" not in str(row.get("consume_subType") or ""):
                continue
            try:
                sid = int(row.get("id"))
                cost = int(str(row.get("consume_count") or "0").split(",")[0])
                cap = int(row.get("purchaseMaxNum") or -1)
            except (TypeError, ValueError):
                continue
            items.append((sid, str(row.get("name") or sid), cost, cap))
        _FASHION_SHOP_ITEMS = sorted(items)
    return _FASHION_SHOP_ITEMS


def fashion_shop_label(sid, name, cost, cap):
    """玉珠商店一行文字：名称、单价、限购。"""
    limit = '不限购' if cap < 0 else '限购%d' % cap
    return '%s %s · %d玉珠 · %s' % (sid, name, cost, limit)



with open(os.path.join(HERE, "boss_catalog.json"), encoding="utf-8") as _f:



    _BOSS_CATALOG = json.load(_f)



with open(os.path.join(HERE, "time_energy_catalog.json"), encoding="utf-8") as _f:



    _TIME_ENERGY_CATALOG = json.load(_f)



with open(os.path.join(HERE, "nightmare_stages.json"), encoding="utf-8") as _f:



    _NM_STAGES = list(reversed([(int(k), v) for k, v in json.load(_f).items()]))



with open(os.path.join(HERE, "national_day_2026.json"), encoding="utf-8") as _f:



    _NATIONAL_DAY_CHOICES = json.load(_f)











def _national_day_today():



    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")







# 蛮荒副本列表(与 daily_auto.MANHUANG_MIDS 保持一致, 倒序排列最新在前)



MANHUANG_MIDS = list(reversed([



    (1400101, "九江穴"), (1400102, "瑶碧山"), (1400103, "太山"),



    (1400104, "鹿吴之山"), (1400105, "谯明之河"), (1400106, "小次之山"),



    (1400107, "极渊"), (1400108, "北极柜山"), (1400109, "荒域"),



    (1400110, "圭阝山"), (1400111, "钩吾山谷"), (1400112, "洪蒙金山"),



    (1400113, "北冥"),



]))



DEMON_TOWER_RANGES = [



    f"{(layer - 1) * 10 + 1}-{(layer - 1) * 10 + 5}层"



    for layer in range(16, 0, -1)



]







TASKS = [



    ("噩梦天树王", "RUN_NIGHTMARE_SKY", False, False, "每周2次，自动领取宝箱奖励；服务器下发关卡，不购买次数"),



    ("十殿阎罗/五毒炼狱", "RUN_TEN", True, False, "每日共享3次免费机会，在关卡设置中选关"),



    ("VIP礼包",          "RUN_VIP_GIFT",      True,  False, "免费领"),



    ("接取精英日常任务",  "RUN_ACCEPT_DAILY_TASKS", True, False, "按选中的精英关卡接取每日任务"),



    ("联盟贡献",          "RUN_DEVOTE",        True,  False, "需加联盟"),



    ("学艺",              "RUN_APPRENTICE_LEARN", True, False, "有师父时每日免费1次"),



    ("授课",              "RUN_APPRENTICE_TEACH", True, False, "有徒弟时每日1次"),



    ("竞技场(创建战斗)",   "RUN_ARENA",        True,  False, "按当天免费次数挑战"),

    ("斗宠大会(创建战斗)", "RUN_PET_ARENA",   True,  False, "按当天免费次数挑战"),

    ("神兽森林",          "RUN_FOREST",        True,  False, "默认速通扫荡，可选固定关卡手打或材料预览"),



    ("神秘商店",          "RUN_MYSTERY_SHOP",  True,  False, "花灵魂"),






    ("十绝阵",           "RUN_HALO",          True,  False, "每天+1次，最多存5次"),



    ("蛮荒",             "RUN_MANHUANG",      True,  False, "共享宝箱每日+2，最多存10次"),



    ("福禄寿",           "RUN_FLUSHOU",       True,  False, "每项每日免费：VIP0–2为1次，VIP3及以上2次；执行剩余免费次数"),



    ("周末在线·双倍buff（第1档）", "RUN_WEEKEND_BUFF", True, False, "活动230周五/周六/周日：只领在线0分钟的第1档，激活掉宝/灵魂/经验+100% 90分钟"),
    ("周末在线·后几档领奖", "RUN_WEEKEND_ONLINE", True, False, "活动230周五/周六/周日：领在线2/5/10/20分钟档与累计5档礼包（第1档buff由上一项负责）"),



    ("挑战刑天", "RUN_ACT_XINGTIAN", True, False, "普通/噩梦每日共享免费2次；优先噩梦，战力不足转普通"),



    ("牛魔王",           "RUN_ACT_MONKIAN",  True,  False, "免费2次"),



    ("魔龙",             "RUN_ACT_DRAGON",   True,  False, "免费2次"),



    ("GM切磋",           "RUN_ACT_GM",       False, False, "每日免费2次，萌哥/汪汪由服务器决定"),



    ("邪悟空",           "RUN_ACT_XWUKONG",  False, False, "当前未开放"),



    ("邪瑶瑶",           "RUN_ACT_XYAOYAO",  False, False, "当前未开放"),



    ("邪唐僧",           "RUN_ACT_XTANG",    False, False, "当前未开放"),



    ("邪龙女",           "RUN_ACT_XLONG",    False, False, "当前未开放"),



    ("邪二郎神",         "RUN_ACT_XYANGJIAN", False, False, "当前未开放"),



    ("邪八戒",           "RUN_ACT_XBAJIE",   True,  False, "免费1次"),



    ("邪沙僧",           "RUN_ACT_XSHASENG", False, False, "当前未开放"),



    ("邪白龙",           "RUN_ACT_XBAILONG", True,  False, "免费1次"),



    ("九宫玄塔",         "RUN_NINE_TOWER",    True,  False, "共享3次/天"),



    ("玄塔有灵",         "RUN_XUANTA_EVENT",  True,  False, "限时任务；免费打一场玄塔并领奖"),



    ("天树王", "RUN_SKY", False, False, "按关卡设置选择，三个关卡每日共享免费2次"),



    ("精英关卡",          "RUN_ELITE",         True,  False, "按“精英关卡”页勾选，每关每天免费2次"),



    ("噩梦关卡",         "RUN_DEMON_TOWER",   True,  False, "共享宝箱最多2次，默认七星殿"),



    ("镇妖塔",           "RUN_DEMON_TOWER2",  True,  False, "每天+1次，最多存5次"),



    ("灵宠试炼",         "RUN_PET_TOWER",     True,  False, "每日重置"),



    ("星斗幻境",         "RUN_STAR_MAZE",     True,  False, "3大层全通；层间强制间隔3分钟"),



    ("金秋送福（金秋蜜意）", "RUN_JIN_QIU",    True,  False, "每日免费开箱1次"),



    ("龙宫寻宝任务领奖", "RUN_DRAGON_TREASURE_TASKS", True, False, "只领已完成奖励"),



    ("中秋博饼",         "RUN_MID_AUTUMN",    True,  False, "免费掷骰"),



    ("云梯寻宝（夺宝云梯）", "RUN_CLOUD_LADDER", True, False, "每天1次免费投掷，自动领取已达档位"),



    ("双十一免费抽狗卡", "RUN_DOG_CARD", False, False, "每账号每日免费1抽，跨存档共享；仅抽取并核对，不赠送或兑换"),



    ("魔玉兔", "RUN_MAGIC_RABBIT", False, False, "每日活动上限2次；自动选已通关主线，只领取活动怪奖励；需背包空间"),
    ("万能强化石（每日4个）", "RUN_ELITE_STONE", False, False, "从精英碧玉径顺序免费翻牌；不拾取场景掉落，保留强化石，其余新增可售道具自动出售；今日4个即停"),
    ("魔法水晶球（每日11个）", "RUN_MAGIC_CRYSTAL", False, False, "实时检测今日数量；手动打最新主线上一关，按2/1个续领至11；今日已达10个则停止"),



    ("遗迹寻宝",         "RUN_RELIC_TREASURE",False, False, "目前暂未开放"),



    ("聚灵池",           "RUN_STOVE",         True,  False, "VIP6及以上每日免费聚灵1次；不消耗聚灵石"),



    ("万象古树",         "RUN_WANXIANG",      True,  False, "免费2次/天"),



    ("迷宫挑战",         "RUN_FREE_MAZE",     True,  False, "每日活跃需通关3次；可按通关率筛选或指定迷宫"),



    ("每日活跃",         "RUN_LIVENESS",      True,  False, "领任务+里程碑"),



    ("永久时装（玉珠）", "RUN_PERMANENT_FASHION", True, False, "签到＋在线20分钟任务领奖；阶段奖励默认第1项"),



    ("八部天龙等（仙晶）", "RUN_WHITE_DRAGON", True, False, "补做角色日常并领奖；只用免费次数，条件不足跳过，不自动推关升级"),
    ("成长双倍buff（每日祝福）", "RUN_GROWTH_BUFF", True, False, "接取839001并领取2小时掉宝/灵魂/经验双倍buff"),
    ("登录有礼·领取今日（新版）", "RUN_LANDING_NEW", False, False, "新手8天登录有礼：带 loginAct 走新版路由，每天只能领当天一档"),
    ("登录有礼·老版备用路由", "RUN_LANDING_LEGACY", False, False, "不带 loginAct 的老版路由；仅新版异常时备用"),
    ("新手有礼·一键领取（6天任务+当天礼包）", "RUN_NOVICE_GIFT", False, False, "活动173：领取已完成任务奖励；当天任务全完成可领当天礼包"),
    ("新手有礼·仅查询状态", "RUN_NOVICE_CHECK", False, False, "只读：输出第1~6天任务与礼包状态，不做领取"),
    ("成长挑战·通关主线目标", "RUN_GROWTH_DUNGEON", True, False, "逐条接取并快速通关昆仑宫~东极妙严宫，领取积分+强化石；不买至尊特权"),
    ("成长挑战·全部任务接取", "RUN_GROWTH_ACCEPT", True, False, "47个任务一次性接取，不消耗资源；祖巫只接不打卡"),
    ("成长挑战·蛮荒（4关×5次）", "RUN_GROWTH_MANHUANG", True, False, "九江穴/瑶碧山/太山/鹿吴之山各单人通关5次领奖，不领共享宝箱"),
    ("成长挑战·十绝阵", "RUN_GROWTH_HALO", True, False, "按剩余奖励次数补打831029~034并领奖，次数不够留到明天"),
    ("成长挑战·炼丹", "RUN_GROWTH_DAN", True, False, "缺基础材料自动同大类1:1置换，缺丹引则跳过"),
    ("成长挑战·积分档位领奖", "RUN_GROWTH_POINT", True, False, "领取1001~1018档位奖励，至尊档需已开通"),
    ("成长挑战·购买至尊特权", "RUN_GROWTH_BUY_VIP", False, False, "扣除3600点券且不可撤销；仅限成长挑战页“购买至尊特权”按钮+口令确认后执行"),
    ("成长挑战·一键接取全部", "RUN_GROWTH_ACCEPTALL", True, False, "47个任务一次性接取（接取免费、不耗次数），应先于完成/领取执行"),
    ("成长挑战·一键完成主线+蛮荒", "RUN_GROWTH_FREE", True, False, "只做主线与蛮荒（不耗额外次数/点券），不看勾选、全量补做剩余"),
    ("成长挑战·一键领取（只领奖）", "RUN_GROWTH_CLAIM_ONLY", True, False, "只提交已完成任务并领积分档位，不接取、不打本、不耗次数"),
    ("永久时装·签到领奖", "RUN_FASHION_SIGNIN", True, False, "每日签到，跨天才会发奖"),
    ("永久时装·在线任务领奖", "RUN_FASHION_ONLINE", True, False, "在线20分钟任务970002；未满不挂机等待"),
    ("永久时装·玉珠商店购买", "RUN_FASHION_SHOP", False, False, "只花玉珠、按限购自动扣减；默认关，需在永久时装页勾选商品"),



    ("庆典其他五项任务", "RUN_CELEBRATION", False, False, "先凑4个止血草炼制两次，再用药；完成连击、杀怪、法宝，不等待在线任务"),
    ("庆典在线15分钟", "RUN_CELEBRATION_ONLINE", False, False, "只等待在线达标并领取在线任务奖励，不执行其他五项"),



    ("重阳采菊", "RUN_CLIMB_HIGH", True, False, "默认100分，执行当天剩余免费次数（每日3次），不花点券"),



]







ACTIVE_XIE_SWITCHES = active_xie_switches()



TASKS += [



    ('竞技场报名', 'RUN_ARENA_SIGNUP', False, False, '仅在报名时段内、本周未报名时发送一次 applyFor；已报名不重发'),
    ('斗宠大会报名', 'RUN_PET_ARENA_SIGNUP', False, False, '同竞技场；斗宠阵容为空时跳过报名'),
    ('竞技场上届领奖', 'RUN_ARENA_REWARD', False, False, '仅领上届奖励并核对竞技币；不报名、不挑战'),
    ('斗宠大会上届领奖', 'RUN_PET_ARENA_REWARD', False, False, '仅领上届奖励并核对斗宠币和道具；不报名、不挑战'),



    ('月卡领奖', 'RUN_MONTHCARD_REWARD', False, False, '当前存档；仅领取'),



    ('善法堂免费点赞', 'RUN_SHANFA_LIKE', False, False, '免费点赞一次'),



    ('许愿池上期领奖', 'RUN_WISH_POOL_REWARD', False, False, '仅领上期奖励'),
    ('许愿池（仅随机方案）', 'RUN_WISH_POOL_RANDOM', False, False, '设置为随机许愿时执行3池各10次；手动模式跳过此项目'),



    ('幻兽派遣日常', 'RUN_FAIRY_REWARD', False, False, '先领已完成奖励，再按幻兽页设置重新派遣；不使用点券'),



]




TASKS = [



    (name, key,



     key in ACTIVE_XIE_SWITCHES,



     paid,



     "本轮开放·免费1次" if key in ACTIVE_XIE_SWITCHES else "本游戏版本未开放")



    if key in XIE_ROLE_SWITCHES else (name, key, default, paid, note)



    for name, key, default, paid, note in TASKS



]







TASK_PAGES = {



    "日常任务1": (



        "RUN_FLUSHOU", "RUN_WEEKEND_BUFF", "RUN_WEEKEND_ONLINE", "RUN_DEVOTE", "RUN_SHANFA_LIKE",



        "RUN_ARENA", "RUN_PET_ARENA", 



        "RUN_MYSTERY_SHOP", "RUN_STOVE", "RUN_FREE_MAZE",



        "RUN_APPRENTICE_LEARN", "RUN_APPRENTICE_TEACH",



    ),



    "日常任务2": (



        "RUN_VIP_GIFT", "RUN_MONTHCARD_REWARD", "RUN_FAIRY_REWARD", "RUN_LIVENESS",



    ),



    "新手任务": ("RUN_PERMANENT_FASHION", "RUN_WHITE_DRAGON", "RUN_GROWTH_BUFF",
                 "RUN_LANDING_NEW", "RUN_LANDING_LEGACY",
                 "RUN_NOVICE_GIFT", "RUN_NOVICE_CHECK",
                 "RUN_GROWTH_ACCEPTALL", "RUN_GROWTH_FREE",
                 "RUN_GROWTH_DUNGEON", "RUN_GROWTH_ACCEPT", "RUN_GROWTH_MANHUANG", "RUN_GROWTH_HALO",
                 "RUN_GROWTH_DAN", "RUN_GROWTH_POINT", "RUN_GROWTH_CLAIM_ONLY", "RUN_GROWTH_BUY_VIP",
                 "RUN_FASHION_SIGNIN", "RUN_FASHION_ONLINE", "RUN_FASHION_SHOP"),



    "日常副本": (



        "RUN_FOREST", "RUN_NINE_TOWER", "RUN_TEN",



        "RUN_ELITE", "RUN_ELITE_STONE", "RUN_SKY", "RUN_DEMON_TOWER",



        "RUN_WANXIANG", "RUN_PET_TOWER",



    ),



    "活动副本": (



        "RUN_CLOUD_LADDER", "RUN_DOG_CARD", "RUN_JIN_QIU", "RUN_MID_AUTUMN",



        "RUN_MAGIC_RABBIT", "RUN_MAGIC_CRYSTAL", "RUN_WISH_POOL_REWARD", "RUN_WISH_POOL_RANDOM", "RUN_CELEBRATION", "RUN_CELEBRATION_ONLINE", "RUN_CLIMB_HIGH",



        "RUN_XUANTA_EVENT",



        "RUN_DRAGON_TREASURE_TASKS", "RUN_RELIC_TREASURE",



        "RUN_ACT_XINGTIAN", "RUN_ACT_MONKIAN", "RUN_ACT_DRAGON", "RUN_ACT_GM", "RUN_ACT_XWUKONG",



        "RUN_ACT_XYAOYAO", "RUN_ACT_XTANG", "RUN_ACT_XLONG",



        "RUN_ACT_XYANGJIAN", "RUN_ACT_XBAJIE", "RUN_ACT_XSHASENG",



        "RUN_ACT_XBAILONG",



    ),



    "周常副本／领奖": ("RUN_ARENA_SIGNUP", "RUN_PET_ARENA_SIGNUP", "RUN_ARENA_REWARD", "RUN_PET_ARENA_REWARD", "RUN_MANHUANG", "RUN_HALO", "RUN_DEMON_TOWER2", "RUN_STAR_MAZE", "RUN_NIGHTMARE_SKY"),



}



assert ({key for keys in TASK_PAGES.values() for key in keys}



        | {"RUN_ACCEPT_DAILY_TASKS"}) == {task[1] for task in TASKS}

# 新手任务页「成长挑战」子标签包含的开关
GROWTH_CHALLENGE_KEYS = ("RUN_GROWTH_DUNGEON", "RUN_GROWTH_ACCEPT", "RUN_GROWTH_MANHUANG",
                         "RUN_GROWTH_HALO", "RUN_GROWTH_DAN", "RUN_GROWTH_POINT")

# 成长挑战子标签内的可折叠分类：(分类key, 标题, 归属开关, [qId...])
GROWTH_CATEGORIES = (
    ('dungeon', '主线通关 831001~831016', 'RUN_GROWTH_DUNGEON', list(range(831001, 831017))),
    ('manhuang', '蛮荒·每关通关5次 831035~831038', 'RUN_GROWTH_MANHUANG', list(range(831035, 831039))),
    ('halo', '十绝阵·累计次数 831029~831034', 'RUN_GROWTH_HALO', list(range(831029, 831035))),
    ('accept', '祖巫/世界BOSS 831017~831028（只接取，限时开放）', 'RUN_GROWTH_ACCEPT',
     list(range(831017, 831029))),
    ('dan', '炼丹 831039~831047', 'RUN_GROWTH_DAN', list(range(831039, 831048))),
    ('point', '积分档位·普通 1001~1018', 'RUN_GROWTH_POINT', list(range(1001, 1019))),
    ('point_vip', '积分档位·至尊（需已购特权）2001~2018', 'RUN_GROWTH_POINT',
     list(range(2001, 2019))),
)


def growth_row_label(cat_key, qid):
    """折叠列表里的一行文字：任务名称/条件，或积分档位需求。"""
    if cat_key in ('point', 'point_vip'):
        row = _GROWTH_REWARD_CFG.get(str(qid)) or {}
        need = row.get('growthMoneney')
        kind = '至尊' if row.get('levelType') == 2 else '普通'
        item = row.get('describe') or _prop_name(row.get('subType'))
        cnt = row.get('count')
        gift = ('%s×%s' % (item, cnt)) if item else '奖励未配置'
        return '档位%s · %s分 · %s · %s' % (qid, need if need is not None else '?', kind, gift)
    row = _GROWTH_TASK_CFG.get(str(qid)) or {}
    text = ('%s %s' % (qid, row.get('describe') or row.get('name') or '')).strip()
    gift = growth_task_reward_text(qid)
    return ('%s ｜奖励 %s' % (text, gift)) if gift else text


def growth_task_need(qid):
    """任务需要完成的目标次数（配置 targetNum 取最大值，默认1）。"""
    row = _GROWTH_TASK_CFG.get(str(qid)) or {}
    nums = []
    for part in str(row.get('targetNum') or '').split(';'):
        try:
            nums.append(int(part))
        except ValueError:
            continue
    return max(nums) if nums else 1







TIMES_TASKS = [



    ("神秘商店购买次数", "MYSTERY_BUY_TIMES", 1, 10, 10),

    ("藏宝洞本次挑战次数", "CARD_CAVE_TIMES", 1, 5, 5),



]







STAGE_LABELS = [



    ("神兽森林", "forest", _SN["forest"]),



    ("十殿阎罗/五毒炼狱", "ten", _SN["ten"]),



    ("天树王", "sky", _SN["sky"]),



    ("九宫玄塔", "nine", _SN["nine"]),



    ("万象古树", "wanxiang", [(300113, "丹熏山")]),



    # 精英、噩梦的设置直接放在日常副本页



]



class DailyGUI:



    def __init__(self, root):



        self.root = root



        root.title("造梦西游5 工具箱 正式版1.01（2026-11-01）")



        root.geometry("920x760")



        root.minsize(800, 640)



        self.var_checks = {}



        self.var_times = {}



        self.var_stage = {}



        self.elite_vars = {}



        self.daily_task_vars = {}



        self.daily_task_quota = None



        self.daily_task_statuses = {}



        self.log_queue = queue.Queue()



        self.running = False



        from task_execution_gate import ExecutionGate



        self.execution_gate = ExecutionGate()



        self._stop_requested = False



        self.proc = None



        self.log_file_path = None



        self.log_file_lock = threading.Lock()



        self.accounts_dir = os.path.join(HERE, "accounts")



        os.makedirs(self.accounts_dir, exist_ok=True)



        self.credentials = load_credentials()



        from category_spend_ui import CategoryPermissions



        self.spend_permissions = CategoryPermissions(self)



        self._build_ui()



        from my_daily_ui import MyDailyWindow
        self.my_daily_window = MyDailyWindow(self, TASKS, TASK_PAGES)
        from my_weekly_ui import MyWeeklyWindow
        self.my_weekly_window = MyWeeklyWindow(self)

        self._refresh_account_list()



        self._load_account_info()



        from ui_memory import SettingsMemory



        self.settings_memory = SettingsMemory(self, self.main_notebook,



                                              self.memory_controls, os.path.join(HERE, 'ui_settings.json'))







    def _build_ui(self):



        top = ttk.LabelFrame(self.root, text="账号 / 登录")



        top.pack(fill=tk.X, padx=8, pady=4)







        # 账密登录行



        login_row = ttk.Frame(top)



        login_row.pack(fill=tk.X, padx=4, pady=2)



        ttk.Label(login_row, text="4399账号:").pack(side=tk.LEFT)



        self.var_login_user = tk.StringVar()



        ttk.Entry(login_row, textvariable=self.var_login_user, width=16).pack(side=tk.LEFT, padx=4)



        ttk.Label(login_row, text="密码:").pack(side=tk.LEFT)



        self.var_login_pwd = tk.StringVar()



        ttk.Entry(login_row, textvariable=self.var_login_pwd, width=16, show="*").pack(side=tk.LEFT, padx=4)



        self.var_remember = tk.BooleanVar(value=True)



        ttk.Checkbutton(login_row, text="记住账密", variable=self.var_remember).pack(side=tk.LEFT, padx=4)



        self.btn_login = ttk.Button(login_row, text="账密登录", command=self._do_login)



        self.btn_login.pack(side=tk.LEFT, padx=8)
        tk.Button(login_row, text="▶ 我的日常", command=lambda: self.my_daily_window.open(),
                  bg="#2d7ff9", fg="white", activebackground="#1f6ae0", activeforeground="white",
                  relief=tk.FLAT, font=("Microsoft YaHei UI", 10, "bold"), padx=12, cursor="hand2"
                  ).pack(side=tk.LEFT, padx=6)



        self.lbl_login_status = ttk.Label(login_row, text="", foreground="gray")



        self.lbl_login_status.pack(side=tk.LEFT, padx=4)







        cookie_row = ttk.Frame(top)



        cookie_row.pack(fill=tk.X, padx=4, pady=2)



        ttk.Label(cookie_row, text="Cookie 整串:").pack(side=tk.LEFT)



        self.var_login_cookie = tk.StringVar()



        ttk.Entry(cookie_row, textvariable=self.var_login_cookie, show="*",



                  width=68).pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)



        self.btn_cookie_login = ttk.Button(cookie_row, text="Cookie登录", command=self._do_cookie_login)



        self.btn_cookie_login.pack(side=tk.LEFT, padx=8)



        ttk.Button(cookie_row, text="获取方式说明", command=self._show_cookie_help).pack(side=tk.LEFT, padx=(0, 4))







        # 账号信息行



        info_row = ttk.Frame(top)



        info_row.pack(fill=tk.X, padx=4, pady=2)



        ttk.Label(info_row, text="已存账号:").pack(side=tk.LEFT, padx=(8, 4))



        self.cmb_account = ttk.Combobox(info_row, values=[], width=20, state="readonly")



        self.cmb_account.pack(side=tk.LEFT)



        self.cmb_account.bind("<<ComboboxSelected>>", lambda e: self._load_account())



        ttk.Button(info_row, text="载入", command=self._load_account).pack(side=tk.LEFT, padx=4)



        ttk.Button(info_row, text="删除选中账号", command=self._delete_saved_account).pack(side=tk.LEFT, padx=4)



        self.lbl_account = ttk.Label(info_row, text="未加载")



        self.lbl_account.pack(side=tk.LEFT, padx=8, pady=2)



        ttk.Label(info_row, text="存档槽位:").pack(side=tk.LEFT, padx=(20, 4))



        self.cmb_slot = ttk.Combobox(info_row, values=[str(i) for i in range(8)], width=4, state="readonly")



        self.cmb_slot.set("0")



        self.cmb_slot.pack(side=tk.LEFT)



        self.cmb_slot.bind("<<ComboboxSelected>>", self._on_slot_selected)



        ttk.Button(info_row, text="刷新存档", command=self._refresh_slots).pack(side=tk.LEFT, padx=8)







        mid = ttk.LabelFrame(self.root, text="任务与关卡设置（红色 = 可能消耗点券）")



        self.task_region = mid



        mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)



        notebook = ttk.Notebook(mid)



        self.main_notebook = notebook



        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)



        task_by_key = {task[1]: task for task in TASKS}



        pages = {}



        self.task_canvases = {}



        self.page_run_buttons = {}



        self.single_task_choices = {}



        from activity_page_layout import ordered_keys

        for title, keys in TASK_PAGES.items():
            if title == '活动副本':
                keys = ordered_keys(keys, disabled_reason)



            page = ttk.Frame(notebook, padding=8)



            notebook.add(page, text=title)



            task_parent = page
            if title == '日常任务1':
                self.daily1_notebook = ttk.Notebook(page)
                self.daily1_notebook.pack(fill=tk.BOTH, expand=True)
                task_parent = ttk.Frame(self.daily1_notebook)
                self.daily1_paid_page = ttk.Frame(self.daily1_notebook, padding=8)
                self.daily1_notebook.add(task_parent, text='日常任务')
                self.daily1_notebook.add(self.daily1_paid_page, text='点券斗宠／竞技场')
            elif title == '新手任务':
                self.growth_notebook = ttk.Notebook(page)
                self.growth_notebook.pack(fill=tk.BOTH, expand=True)
                task_parent = ttk.Frame(self.growth_notebook)
                self.growth_buff_page = ttk.Frame(self.growth_notebook)
                self.landing_page = ttk.Frame(self.growth_notebook)
                self.novice_page = ttk.Frame(self.growth_notebook)
                self.fashion_page = ttk.Frame(self.growth_notebook)
                self.white_dragon_page = ttk.Frame(self.growth_notebook)
                self.growth_challenge_page = ttk.Frame(self.growth_notebook)
                self.growth_notebook.add(self.growth_buff_page, text='成长双倍buff')
                self.growth_notebook.add(self.novice_page, text='新手有礼')
                self.growth_notebook.add(self.fashion_page, text='永久时装')
                # 新手任务子标签暂时隐藏：内容已全部拆分到 成长双倍buff/新手有礼/永久时装/成长挑战/八部天龙/登录有礼
                self.growth_notebook.add(self.growth_challenge_page, text='成长挑战')
                self.growth_notebook.add(self.white_dragon_page, text='八部天龙')
                self.growth_notebook.add(self.landing_page, text='登录有礼')
            page_actions = ttk.Frame(task_parent)



            page_actions.pack(fill=tk.X, padx=4, pady=(0, 5))



            button = ttk.Button(page_actions, text="一键执行本页",



                                command=lambda page_title=title: self._start(page_title))



            button.pack(side=tk.LEFT)



            self.page_run_buttons[title] = button
            if title == '新手任务':
                button.configure(text="一键执行本标签")
                button.configure(command=lambda: self._start(
                    '新手任务', group_keys=tuple(k for k in TASK_PAGES['新手任务']
                                                 if k not in GROWTH_CHALLENGE_KEYS)))



            if title in ("日常任务1", "日常任务2", "日常副本", "活动副本", "周常副本／领奖"):



                choices = {task_by_key[key][0]: key for key in keys



                           if title != "活动副本" or not disabled_reason(key)}



                selected = tk.StringVar(value=next(iter(choices), ''))



                self.single_task_choices[title] = (selected, choices)



                ttk.Combobox(page_actions, textvariable=selected, values=list(choices),



                             state="readonly", width=22).pack(side=tk.LEFT, padx=(14, 4))



                ttk.Button(page_actions, text="执行所选项",



                           command=lambda t=title: self._start_single_task(t)).pack(side=tk.LEFT)



            if title in ("日常任务1", "日常任务2", "新手任务", "日常副本", "活动副本", "周常副本／领奖"):



                canvas = tk.Canvas(task_parent, highlightthickness=0)



                scrollbar = ttk.Scrollbar(task_parent, orient=tk.VERTICAL, command=canvas.yview)



                canvas.configure(yscrollcommand=scrollbar.set)



                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)



                canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)



                body = ttk.Frame(canvas)



                window = canvas.create_window((0, 0), window=body, anchor=tk.NW)



                body.bind("<Configure>", lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))



                canvas.bind("<Configure>", lambda e, c=canvas, w=window: c.itemconfigure(w, width=e.width))



                self.task_canvases[title] = canvas



                pages[title] = body



            else:



                pages[title] = page



            if title == "活动副本":



                ttk.Label(pages[title], text="游戏版本 v%s · 当前邪角色轮换：%s"



                          % (GAME_VERSION, "、".join(active_xie_names()))).pack(anchor=tk.W, padx=6, pady=(2, 4))



            checks = ttk.LabelFrame(pages[title], text="执行项目")
            if title == '活动副本':
                self.activity_task_checks = checks



            checks.pack(fill=tk.X, padx=4, pady=4)



            checks.columnconfigure(0, weight=1)



            checks.columnconfigure(1, weight=1)



            render_keys = [k for k in keys if title != '新手任务' or k not in GROWTH_CHALLENGE_KEYS]
            if title == '新手任务':
                # 成长双倍buff / 永久时装 已单独成页，其余开关只建隐藏变量
                for key in render_keys:
                    if key not in self.var_checks:
                        self.var_checks[key] = tk.BooleanVar(value=True)
                # 所有项目都已拆到各自子标签，本页不再显示复选行
                render_keys = []
                ttk.Label(checks, foreground="#666",
                          text="本页项目已拆分为独立子标签：成长双倍buff / 新手有礼 / 永久时装 / 成长挑战 / 八部天龙 / 登录有礼").pack(
                    anchor=tk.W, padx=6, pady=4)
                # 玉珠商店购买/登录有礼默认关闭：只有对应按钮（强制键）才会执行
                for _k in ('RUN_FASHION_SHOP', 'RUN_LANDING_NEW', 'RUN_LANDING_LEGACY',
                           'RUN_NOVICE_GIFT', 'RUN_NOVICE_CHECK'):
                    if _k in self.var_checks:
                        self.var_checks[_k].set(False)
            for i, key in enumerate(render_keys):



                name, _, default, paid, note = task_by_key[key]



                unavailable = disabled_reason(key)



                if unavailable:



                    default, note = False, unavailable



                var = tk.BooleanVar(value=default)



                self.var_checks[key] = var
                if title == '活动副本' and unavailable:
                    continue



                cb = ttk.Checkbutton(checks, text=f"{name}  ({note})", variable=var)



                cb.grid(row=i // 2, column=i % 2, sticky=tk.W, padx=10, pady=4)



                if key in XIE_ROLE_SWITCHES and key not in ACTIVE_XIE_SWITCHES:



                    cb.configure(state=tk.DISABLED)



                if unavailable:



                    cb.configure(state=tk.DISABLED)



                if paid:



                    cb.configure(style="Red.TCheckbutton")







        # 新手任务页「成长挑战」：拆成两个子标签，领奖在前、任务在后
        if hasattr(self, 'growth_challenge_page'):
            gc_page = self.growth_challenge_page
            gc_sub = ttk.Notebook(gc_page)
            gc_sub.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            self.growth_sub_notebook = gc_sub
            self.growth_reward_page = ttk.Frame(gc_sub)
            self.growth_task_page = ttk.Frame(gc_sub)
            gc_sub.add(self.growth_reward_page, text="领奖")
            gc_sub.add(self.growth_task_page, text="任务")

            # ---- 领奖子页：一键领取已完成 + 刷新状态 + 积分档位 + 购买特权 ----
            gc_actions = ttk.Frame(self.growth_reward_page)
            gc_actions.pack(fill=tk.X, padx=4, pady=(4, 2))
            ttk.Button(gc_actions, text="一键领取已完成（不耗次数）",
                       command=lambda: self._start('成长挑战一键领取',
                                                   group_keys=('RUN_GROWTH_CLAIM_ONLY',))).pack(side=tk.LEFT)
            self.btn_sync_growth = ttk.Button(gc_actions, text="刷新状态",
                                              command=self._sync_growth_status)
            self.btn_sync_growth.pack(side=tk.LEFT, padx=(6, 0))
            self.var_growth_summary = tk.StringVar(value="状态：未读取（点“刷新状态”拉取积分、剩余次数和任务进度）")
            ttk.Label(self.growth_reward_page, textvariable=self.var_growth_summary,
                      foreground="#444").pack(anchor=tk.W, padx=6, pady=(0, 4))
            gc_actions3 = ttk.Frame(self.growth_reward_page)
            gc_actions3.pack(fill=tk.X, padx=4, pady=(0, 4))
            ttk.Button(gc_actions3, text="购买至尊特权（3600点券·需输入口令）",
                       command=self._buy_growth_vip).pack(side=tk.LEFT)
            ttk.Label(gc_actions3, foreground="#b00",
                      text="一次性：扣 3600 点券、不可撤销；立即到账 %s；并解锁 2001~2018 至尊档位"
                           % (growth_vip_gift_text() or "（配置缺失）")).pack(
                side=tk.LEFT, padx=(8, 0))
            reward_canvas = tk.Canvas(self.growth_reward_page, highlightthickness=0)
            reward_scroll = ttk.Scrollbar(self.growth_reward_page, orient=tk.VERTICAL,
                                          command=reward_canvas.yview)
            reward_canvas.configure(yscrollcommand=reward_scroll.set)
            reward_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            reward_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            reward_body = ttk.Frame(reward_canvas)
            reward_win = reward_canvas.create_window((0, 0), window=reward_body, anchor=tk.NW)
            reward_body.bind("<Configure>",
                             lambda e, c=reward_canvas: c.configure(scrollregion=c.bbox("all")))
            reward_canvas.bind("<Configure>",
                               lambda e, c=reward_canvas, w=reward_win: c.itemconfigure(w, width=e.width))

            # ---- 任务子页：一键接取 + 免费一键完成 + 按勾选执行 ----
            gc_actions2 = ttk.Frame(self.growth_task_page)
            gc_actions2.pack(fill=tk.X, padx=4, pady=(4, 2))
            ttk.Button(gc_actions2, text="① 一键接取全部（免费）",
                       command=lambda: self._start('成长挑战一键接取',
                                                   group_keys=('RUN_GROWTH_ACCEPTALL',))).pack(side=tk.LEFT)
            ttk.Button(gc_actions2, text="② 一键完成主线+蛮荒（不耗次数）",
                       command=lambda: self._start('成长挑战一键完成',
                                                   group_keys=('RUN_GROWTH_FREE',))).pack(side=tk.LEFT, padx=(6, 0))
            gc_actions4 = ttk.Frame(self.growth_task_page)
            gc_actions4.pack(fill=tk.X, padx=4, pady=(0, 2))
            gc_button = ttk.Button(gc_actions4, text="执行勾选任务（按下方勾选的具体条目）",
                                   command=lambda: self._start('新手任务·成长挑战',
                                                               group_keys=GROWTH_CHALLENGE_KEYS))
            gc_button.pack(side=tk.LEFT)
            self.page_run_buttons['新手任务·成长挑战'] = gc_button
            ttk.Button(gc_actions4, text="领取任务奖励（已完成任务·不耗次数）",
                       command=lambda: self._start('成长挑战一键领取',
                                                   group_keys=('RUN_GROWTH_CLAIM_ONLY',))).pack(
                side=tk.LEFT, padx=(6, 0))
            ttk.Label(gc_actions4, foreground="#a15c00",
                      text="炼丹/十绝阵/世界BOSS 不进“一键完成”：只有在这里勾选后才会跑").pack(
                side=tk.LEFT, padx=(8, 0))
            task_canvas = tk.Canvas(self.growth_task_page, highlightthickness=0)
            task_scroll = ttk.Scrollbar(self.growth_task_page, orient=tk.VERTICAL,
                                        command=task_canvas.yview)
            task_canvas.configure(yscrollcommand=task_scroll.set)
            task_scroll.pack(side=tk.RIGHT, fill=tk.Y)
            task_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            task_body = ttk.Frame(task_canvas)
            task_win = task_canvas.create_window((0, 0), window=task_body, anchor=tk.NW)
            task_body.bind("<Configure>",
                           lambda e, c=task_canvas: c.configure(scrollregion=c.bbox("all")))
            task_canvas.bind("<Configure>",
                             lambda e, c=task_canvas, w=task_win: c.itemconfigure(w, width=e.width))
            self.task_canvases['新手任务·成长挑战'] = task_canvas

            # 分类总开关不再显示（执行范围由分类勾选 + *_IDS 决定），仍保留变量以兼容配置生成
            for key in GROWTH_CHALLENGE_KEYS:
                self.var_checks[key] = tk.BooleanVar(value=True)

            self.var_growth_ids = {}
            self.growth_row_texts = {}
            self.growth_cat_status = {}
            self.var_growth_vip_unlock = tk.BooleanVar(value=False)
            for cat_key, cat_title, switch_key, qids in GROWTH_CATEGORIES:
                # 积分档位放“领奖”子页，其余任务分类放“任务”子页
                body = reward_body if switch_key == 'RUN_GROWTH_POINT' else task_body
                cat_frame = ttk.LabelFrame(body, text="%s（%d项）" % (cat_title, len(qids)))
                cat_frame._default_expanded = True
                cat_frame.pack(fill=tk.X, padx=4, pady=3)
                cat_frame.columnconfigure(0, weight=1)
                cat_frame.columnconfigure(1, weight=1)
                status_var = tk.StringVar(value="状态：未读取")
                self.growth_cat_status[cat_key] = status_var
                ttk.Label(cat_frame, textvariable=status_var, foreground="#666").grid(
                    row=0, column=0, columnspan=2, sticky=tk.W, padx=8, pady=(2, 0))
                id_vars = {}
                text_vars = {}
                for i, qid in enumerate(qids):
                    var = tk.BooleanVar(value=True)
                    id_vars[qid] = var
                    text_var = tk.StringVar(value=growth_row_label(cat_key, qid))
                    text_vars[qid] = text_var
                    ttk.Checkbutton(cat_frame, textvariable=text_var, variable=var).grid(
                        row=1 + i // 2, column=i % 2, sticky=tk.W, padx=8, pady=2)
                # 同一开关下的多个分类（普通/至尊档位）合并写回同一个 *_IDS
                self.var_growth_ids.setdefault(switch_key, {}).update(id_vars)
                self.growth_row_texts[cat_key] = text_vars

        # 「八部天龙」独立子页：仙晶（白龙）新手日常，整包执行
        if hasattr(self, 'white_dragon_page'):
            wp = self.white_dragon_page
            wa = ttk.Frame(wp)
            wa.pack(fill=tk.X, padx=8, pady=(8, 4))
            ttk.Button(wa, text="一键执行：八部天龙日常（含领奖）",
                       command=lambda: self._start('八部天龙',
                                                   group_keys=('RUN_WHITE_DRAGON',))).pack(side=tk.LEFT)
            ttk.Label(wa, text='二级密码（补购回元露用，仅本次）').pack(side=tk.LEFT, padx=(10, 2))
            self.var_white_dragon_password = tk.StringVar(value='')
            ttk.Entry(wa, textvariable=self.var_white_dragon_password,
                      show='*', width=14).pack(side=tk.LEFT)
            ttk.Label(wp, foreground="#666",
                      text="存档未开放时自动跳过；只涉及灵魂/仙晶，不花点券").pack(anchor=tk.W, padx=8)
            wd_sub = ttk.LabelFrame(wp, text="包含的动作")
            wd_sub.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))
            for line in ("① 在线10分钟 8440001（进度随登录/挂机累计，满10分钟自动领取）",
                         "② 炼丹炉炼制3次 8440004（先打止血草，再 composeId=1 炼回元露）",
                         "③ 关卡内使用道具2次 8440003（缺药先打止血草→炼制→仍缺才用灵魂买，需二级密码）",
                         "④ 福星挑战 8440002（200101，免费1次；VIP≥3 时 2 次）",
                         "⑤ 九宫玄塔 8440005（100011 起，按九宫免费次数，最多1次）",
                         "⑥ 精英挑战2次 8440007（优先已有通关记录的精英关）",
                         "⑦ 速通2次 8440006（仅已通关精英关且战力达标，10扫荡体力/次）",
                         "⑧ 竞技场3次 8440008（30级+，只用免费次数）",
                         "⑨ 领奖：所有已完成任务 commitQuest，含到点的在线任务",
                         "⑩ 全程核对点券前后一致，出现消耗或条件不足立即跳过"):
                ttk.Label(wd_sub, text=line).pack(anchor=tk.W, padx=8, pady=1)

        # 「永久时装」独立子页：签到+每日任务+阶段奖励领奖，以及玉珠商店购买
        if hasattr(self, 'fashion_page'):
            fp = self.fashion_page
            fa = ttk.Frame(fp)
            fa.pack(fill=tk.X, padx=8, pady=(8, 4))
            ttk.Button(fa, text="签到领奖",
                       command=lambda: self._start('永久时装·签到',
                                                   group_keys=('RUN_FASHION_SIGNIN',))).pack(side=tk.LEFT)
            ttk.Button(fa, text="在线任务领奖（970002）",
                       command=lambda: self._start('永久时装·在线任务',
                                                   group_keys=('RUN_FASHION_ONLINE',))).pack(
                side=tk.LEFT, padx=(6, 0))
            ttk.Button(fa, text="全部领奖（签到+任务+阶段）",
                       command=lambda: self._start('永久时装领奖',
                                                   group_keys=('RUN_PERMANENT_FASHION',))).pack(
                side=tk.LEFT, padx=(6, 0))
            sub = ttk.LabelFrame(fp, text="包含的子任务")
            sub.pack(fill=tk.X, padx=8, pady=(4, 6))
            for line in ("① 签到 970001（每日签到）",
                         "② 在线任务 970002（在线20分钟，进度可存）",
                         "③ 每日任务 970003 竞技场1次 / 970004 主线副本1次 / 970005 炼丹1次",
                         "④ 阶段奖励：玉珠进度 10/70/150/300/450/600",
                         "⑤ 玉珠商店：以下 22 件商品，部分有 purchaseMaxNum 限购"):
                ttk.Label(sub, text=line).pack(anchor=tk.W, padx=8, pady=1)
            pwd_row = ttk.Frame(fp)
            pwd_row.pack(fill=tk.X, padx=8, pady=(0, 6))
            ttk.Label(pwd_row, text='二级密码（玉珠商店购买必需，仅本次使用、不保存）').pack(side=tk.LEFT)
            self.var_fashion_shop_password = tk.StringVar(value='')
            ttk.Entry(pwd_row, textvariable=self.var_fashion_shop_password,
                      show='*', width=16).pack(side=tk.LEFT, padx=4)
            ttk.Button(pwd_row, text="购买勾选商品（只花玉珠）",
                       command=lambda: self._start('永久时装·玉珠商店',
                                                   group_keys=('RUN_FASHION_SHOP',))).pack(
                side=tk.LEFT, padx=(6, 0))
            shop_frame = ttk.LabelFrame(
                fp, text="玉珠商店（限购按已购数量自动扣减；默认只勾选要买的商品）")
            shop_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
            shop_canvas = tk.Canvas(shop_frame, highlightthickness=0)
            shop_bar = ttk.Scrollbar(shop_frame, orient=tk.VERTICAL, command=shop_canvas.yview)
            shop_canvas.configure(yscrollcommand=shop_bar.set)
            shop_bar.pack(side=tk.RIGHT, fill=tk.Y)
            shop_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            shop_body = ttk.Frame(shop_canvas)
            shop_win = shop_canvas.create_window((0, 0), window=shop_body, anchor=tk.NW)
            shop_body.bind("<Configure>",
                           lambda e, c=shop_canvas: c.configure(scrollregion=c.bbox("all")))
            shop_canvas.bind("<Configure>",
                             lambda e, c=shop_canvas, w=shop_win: c.itemconfigure(w, width=e.width))
            self.var_fashion_shop_ids = {}
            self.var_fashion_shop_qty = {}
            for sid, name, cost, cap in fashion_shop_items():
                row = ttk.Frame(shop_body)
                row.pack(anchor=tk.W, fill=tk.X, padx=8, pady=1)
                var = tk.BooleanVar(value=False)
                qty = tk.StringVar(value='1')
                self.var_fashion_shop_ids[sid] = var
                self.var_fashion_shop_qty[sid] = qty
                ttk.Checkbutton(row, text=fashion_shop_label(sid, name, cost, cap),
                                variable=var).pack(side=tk.LEFT)
                ttk.Label(row, text='数量').pack(side=tk.LEFT, padx=(10, 2))
                ttk.Spinbox(row, from_=1, to=999, width=5,
                            textvariable=qty).pack(side=tk.LEFT)

        # 「成长双倍buff」独立子页：单独执行任务 839001
        if hasattr(self, 'growth_buff_page'):
            buff_page = self.growth_buff_page
            buff_actions = ttk.Frame(buff_page)
            buff_actions.pack(fill=tk.X, padx=8, pady=8)
            ttk.Button(buff_actions, text="执行：接取并领取 2 小时双倍 buff",
                       command=lambda: self._start('成长双倍buff执行',
                                                   group_keys=('RUN_GROWTH_BUFF',))).pack(side=tk.LEFT)
            ttk.Label(buff_page, foreground="#666",
                      text="任务 839001：接取→commitQuest，领取后 2 小时内 掉宝/灵魂/经验 +100%；每天一次，重复领取会失败").pack(
                anchor=tk.W, padx=8)

        # 「登录有礼」独立子页：新手8天登录有礼，默认新版路由 + 老版备用按钮
        if hasattr(self, 'landing_page'):
            lp = self.landing_page
            la = ttk.Frame(lp)
            la.pack(fill=tk.X, padx=8, pady=(8, 4))
            ttk.Button(la, text="领取今日奖励（新版路由·loginAct）",
                       command=lambda: self._start_landing('RUN_LANDING_NEW')).pack(side=tk.LEFT)
            ttk.Button(la, text="老版路由领取（备用）",
                       command=lambda: self._start_landing('RUN_LANDING_LEGACY')).pack(
                side=tk.LEFT, padx=(6, 0))
            sub = ttk.LabelFrame(lp, text="说明")
            sub.pack(fill=tk.X, padx=8, pady=(4, 6))
            for line in (
                    "① 服务端 entry 下发 loginAct（当前账号为 1840 新成长登录有礼），默认带此参数领奖",
                    "② 每天只能领当天一档，day 0→8；无法跳天，第 8 天需先领到 day=7",
                    "③ 第 8 天：莲子幻珠 101036007×1、妖元 101035001×3、攻击果 101710003×1、大灵魂药水 101012002×5",
                    "④ 老版路由不带 loginAct（对应活动 156）；实测服务端不校验，仍按当天档位发放，仅供新版异常时备用",
                    "⑤ 两个按钮都只领当天额度，同一天重复领取会被 lastGetTime 拦截"):
                ttk.Label(sub, text=line, wraplength=760).pack(anchor=tk.W, padx=8, pady=1)

        # 「新手有礼」独立子页：第1~6天每日任务 + 当天礼包
        if hasattr(self, 'novice_page'):
            np_ = self.novice_page
            na = ttk.Frame(np_)
            na.pack(fill=tk.X, padx=8, pady=(8, 4))
            ttk.Button(na, text="一键领取（已完成任务+当天礼包）",
                       command=lambda: self._start_novice('RUN_NOVICE_GIFT')).pack(side=tk.LEFT)
            ttk.Button(na, text="仅查询状态（不领取）",
                       command=lambda: self._start_novice('RUN_NOVICE_CHECK')).pack(
                side=tk.LEFT, padx=(6, 0))
            nsub = ttk.LabelFrame(np_, text="说明")
            nsub.pack(fill=tk.X, padx=8, pady=(4, 6))
            for line in (
                    "① 活动173「新手有礼」：第1~6天共 30 个任务（配置内 7 条已作废不计），每个任务单独一份奖励",
                    "② 当天全部任务完成后，当天礼包才会解锁（981001~981006，Reward 10681~10686）",
                    "③ 领取路由：scene.questHandler.commitQuest {\"qId\": 980xxx} / 981001~6，仅 status=2 可领",
                    "④ 任务本身（等级5转职、战力70000、强化武器、服丹、竞技场等）需在游戏内完成，工具箱只负责领奖",
                    "⑤ «仅查询» 为只读，不发送任何 commitQuest；日志会列出每天的可领/已领/进行中/未下发数量"):
                ttk.Label(nsub, text=line, wraplength=760).pack(anchor=tk.W, padx=8, pady=1)

        settings = ttk.Frame(notebook, padding=8)



        notebook.insert(1, settings, text="关卡设置")



        settings_canvas = tk.Canvas(settings, highlightthickness=0)



        settings_scroll = ttk.Scrollbar(settings, orient=tk.VERTICAL,



                                        command=settings_canvas.yview)



        settings_canvas.configure(yscrollcommand=settings_scroll.set)



        settings_scroll.pack(side=tk.RIGHT, fill=tk.Y)



        settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)



        settings_body = ttk.Frame(settings_canvas)



        settings_window = settings_canvas.create_window((0, 0), window=settings_body, anchor=tk.NW)



        settings_body.bind("<Configure>", lambda e: settings_canvas.configure(



            scrollregion=settings_canvas.bbox("all")))



        settings_canvas.bind("<Configure>", lambda e: settings_canvas.itemconfigure(



            settings_window, width=e.width))







        supply_frame = ttk.LabelFrame(settings_body, text="全局拾取设置")



        supply_frame.pack(fill=tk.X, padx=4, pady=6)



        self.var_pickup_supplies = tk.BooleanVar(value=False)



        ttk.Checkbutton(supply_frame, text="允许萝卜、蟠桃、蓝瓶、蓝壶进入背包",



                        variable=self.var_pickup_supplies).pack(anchor=tk.W, padx=8, pady=5)



        ttk.Label(supply_frame, text="默认关闭：工具箱各功能逐件拾取时跳过这四类道具。扫荡、翻牌等服务器直接发放的奖励不支持选择拒收。",



                  foreground="gray", wraplength=720).pack(anchor=tk.W, padx=8, pady=(0, 6))







        self.celebration_buttons = []

        climb_frame = ttk.LabelFrame(pages["活动副本"], text="重阳采菊设置")



        climb_frame.pack(fill=tk.X, padx=4, pady=6)



        climb_row = ttk.Frame(climb_frame)



        climb_row.pack(anchor=tk.W, padx=8, pady=6)



        ttk.Label(climb_row, text="提交分数：").pack(side=tk.LEFT)



        self.var_climb_score = tk.StringVar(value="100")



        ttk.Entry(climb_row, textvariable=self.var_climb_score, width=16).pack(side=tk.LEFT, padx=4)



        ttk.Label(climb_frame, text="默认100，可输入任意非负整数；实际分数接受范围和奖励由服务器决定。每天只用剩余3次免费机会，两次之间等待3秒。",



                  foreground="gray", wraplength=750).pack(anchor=tk.W, padx=8, pady=(0, 6))







        wish_frame = ttk.LabelFrame(pages["活动副本"], text="十一许愿 · 每日免费签到三选一")



        wish_frame.pack(fill=tk.X, padx=4, pady=6)



        self.var_wish_day = tk.StringVar()



        ttk.Label(wish_frame, textvariable=self.var_wish_day,



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(5, 3))



        self.var_wish_choice = tk.IntVar(value=0)



        self.wish_choice_buttons = []



        for index in range(1, 4):



            button = ttk.Radiobutton(wish_frame, variable=self.var_wish_choice, value=index)



            button.pack(anchor=tk.W, padx=12, pady=2)



            self.wish_choice_buttons.append(button)



        wish_actions = ttk.Frame(wish_frame)



        wish_actions.pack(anchor=tk.W, padx=8, pady=(5, 8))



        self.btn_wish_status = ttk.Button(wish_actions, text="查看今日签到状态",



                                          command=lambda: self._start_national_day_wish(True))



        self.btn_wish_status.pack(side=tk.LEFT, padx=(0, 8))



        self.btn_wish_sign = ttk.Button(wish_actions, text="领取所选免费奖励",



                                        command=lambda: self._start_national_day_wish(False))



        self.btn_wish_sign.pack(side=tk.LEFT)



        self._refresh_wish_choices()
        from national_day_wish import choices_for, today_key
        if not choices_for(today_key()):
            wish_frame.pack_forget()
        if disabled_reason('RUN_CLIMB_HIGH'):
            climb_frame.pack_forget()








        self._build_teacher_tab(pages["周常副本／领奖"])







        flushou_frame = ttk.LabelFrame(settings_body, text="福禄寿执行模式")



        flushou_frame.pack(fill=tk.X, padx=4, pady=6)



        self.var_flushou_mode = tk.StringVar(value="all")



        ttk.Radiobutton(flushou_frame, text="用完剩余免费次数（当前逻辑）",



                        variable=self.var_flushou_mode, value="all").pack(anchor=tk.W, padx=8, pady=3)



        ttk.Radiobutton(flushou_frame, text="每项仅执行一次",



                        variable=self.var_flushou_mode, value="once").pack(anchor=tk.W, padx=8, pady=3)



        ttk.Label(flushou_frame, text="福、禄、寿分别计次；本周解锁战斗也计入一次。免费次数用尽后跳过。",



                  foreground="gray", wraplength=790).pack(anchor=tk.W, padx=8, pady=(2, 6))







        arena_frame = ttk.LabelFrame(settings_body, text="竞技场与斗宠大会打法")



        arena_frame.pack(fill=tk.X, padx=4, pady=6)



        self.var_arena_mode = tk.StringVar(value="fixed")



        self.var_pet_arena_mode = tk.StringVar(value="fixed")



        self.var_arena_target_uid = tk.StringVar(value="")



        self.var_arena_target_r_number = tk.StringVar(value="")



        self.var_arena_target_rounds = tk.IntVar(value=5)



        self.var_pet_arena_target_uid = tk.StringVar(value="")



        self.var_pet_arena_target_r_number = tk.StringVar(value="")



        self.var_pet_arena_target_rounds = tk.IntVar(value=5)



        self.var_arena_top_n = tk.StringVar(value='20')



        self.var_pet_arena_top_n = tk.StringVar(value='20')



        self.var_arena_battle_wait = tk.StringVar(value='22')



        self.var_arena_round_wait = tk.StringVar(value='22')



        self.var_pet_arena_battle_wait = tk.StringVar(value='2')



        self.var_pet_arena_round_wait = tk.StringVar(value='8')



        self.var_arena_borrow_account = tk.StringVar(value='当前账号')



        self.var_arena_borrow_slot = tk.StringVar(value='0')



        self.var_pet_arena_borrow_account = tk.StringVar(value='当前账号')



        self.var_pet_arena_borrow_slot = tk.StringVar(value='0')



        self.var_arena_target_input = tk.StringVar(value='r_number')



        self.var_arena_target_rid = tk.StringVar(value='')



        self.var_pet_arena_target_input = tk.StringVar(value='r_number')



        self.var_pet_arena_target_rid = tk.StringVar(value='')



        from arena_target_ui import ArenaModePanel



        registration_box = ttk.LabelFrame(arena_frame,text='竞技场／斗宠报名（周五16点~周日22点）')
        registration_box.pack(fill=tk.X,padx=8,pady=6)
        self.arena_registration_buttons=[]
        for title,handler in (('竞技场报名','arena'),('斗宠大会报名','petArena')):
            button=ttk.Button(registration_box,text=title,command=lambda h=handler:self.launch_arena_registration(h))
            button.pack(side=tk.LEFT,padx=6,pady=5)
            self.arena_registration_buttons.append(button)
        # 一键日常开启竞技场任务时会自动检查并报名；这里保留手动入口。

        self.arena_target_controls = {}



        self.arena_mode_panels = {}



        for title, var, uid, slot, rounds in (



                ("竞技场", self.var_arena_mode, self.var_arena_target_uid,



                 self.var_arena_target_r_number, self.var_arena_target_rounds),



                ("斗宠大会", self.var_pet_arena_mode, self.var_pet_arena_target_uid,



                 self.var_pet_arena_target_r_number, self.var_pet_arena_target_rounds)):



            section = ttk.LabelFrame(arena_frame, text=title)



            section.pack(fill=tk.X, padx=8, pady=6)



            handler = 'arena' if title == '竞技场' else 'petArena'



            top_n = self.var_arena_top_n if handler == 'arena' else self.var_pet_arena_top_n



            prefix = 'var_arena' if handler == 'arena' else 'var_pet_arena'



            panel = ArenaModePanel(self, section, handler, var, uid, slot, rounds, top_n, ACCOUNT_FILE,



                                   getattr(self, prefix + '_battle_wait'), getattr(self, prefix + '_round_wait'),



                                   getattr(self, prefix + '_borrow_account'), getattr(self, prefix + '_borrow_slot'),



                                   getattr(self, prefix + '_target_input'), getattr(self, prefix + '_target_rid'))



            self.arena_mode_panels[handler] = panel



            self.arena_target_controls[handler] = panel.control



        arena_advanced_note = ttk.Label(arena_frame, text="随机模式从本榜前120名按战力取前N名，身份无法核对者跳过且不补位。排行榜、指定对手及借用列表只打免费次数；5局/10局为上限，以当天剩余免费次数为准。每局等待和局间等待均可自定义；竞技场默认22秒/22秒，斗宠默认2秒/8秒。借用列表须先查询并确认。目标查询或身份核对失败时停止。",



                  foreground="gray", wraplength=760)
        def refresh_arena_note(*_):
            bits = ''.join('1' if v.get() else '0' for v in self.spend_permissions.variables['dungeons'])
            if bits == '001':
                arena_advanced_note.pack(anchor=tk.W, padx=8, pady=(2, 6))
            else:
                arena_advanced_note.pack_forget()
        for permission_var in self.spend_permissions.variables['dungeons']:
            permission_var.trace_add('write', refresh_arena_note)
        refresh_arena_note()







        from pet_arena_paid_ui import PaidPetArenaPanel
        self.pet_arena_paid_panel = PaidPetArenaPanel(self, self.daily1_paid_page)
        self.paid_arena_permissions = self.spend_permissions.mount(self.daily1_paid_page, 'daily')
        self.paid_arena_permissions._default_expanded = True





        self.var_paid_confirm = self.spend_permissions.variables['daily']







        self.var_times["CARD_CAVE_TIMES"] = tk.IntVar(value=5)







        maze_frame = ttk.LabelFrame(settings_body, text="迷宫挑战筛选")



        maze_frame.pack(fill=tk.X, padx=4, pady=6)



        from maze_target_ui import MazeTargetControls



        self.maze_target_controls = MazeTargetControls(self, maze_frame)



        self.var_free_maze_mode = self.maze_target_controls.rate_mode







        battle_page = ttk.Frame(notebook, padding=8)



        notebook.add(battle_page, text="斗神/乱斗")



        pet_brawl_frame = ttk.LabelFrame(battle_page, text="灵宠乱斗")



        pet_brawl_frame.pack(fill=tk.X, padx=4, pady=6)



        ttk.Label(pet_brawl_frame, text="开放时间：每天 12:00–14:00、20:00–22:00；逐场匹配并挂机。默认4场，场数不限，单场最多10分钟。",



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(5, 3))



        pet_brawl_row = ttk.Frame(pet_brawl_frame)



        pet_brawl_row.pack(anchor=tk.W, padx=8, pady=(0, 7))



        ttk.Label(pet_brawl_row, text="本次匹配：").pack(side=tk.LEFT)



        self.var_pet_brawl_matches = tk.IntVar(value=4)



        ttk.Entry(pet_brawl_row, textvariable=self.var_pet_brawl_matches,



                  width=8).pack(side=tk.LEFT, padx=4)



        ttk.Label(pet_brawl_row, text="次").pack(side=tk.LEFT)



        self.btn_pet_brawl = ttk.Button(pet_brawl_row, text="开始匹配挂机", command=self._start_pet_brawl)



        self.btn_pet_brawl.pack(side=tk.LEFT, padx=12)
        ttk.Label(pet_brawl_row,text='开放时间：12:00–14:00；20:00–22:00（北京时间）').pack(side=tk.LEFT,padx=4)



        ttk.Button(pet_brawl_row, text="打开手动乱斗窗口",



                   command=self._start_pet_brawl_manual).pack(side=tk.LEFT)



        ttk.Label(pet_brawl_frame, text="手动模式单独选宠、上符；一场结束后查看胜负，点击继续匹配才会开下一场。",



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(0, 7))







        pvp_frame = ttk.LabelFrame(battle_page, text="斗神大会")



        pvp_frame.pack(fill=tk.X, padx=4, pady=6, before=pet_brawl_frame)



        ttk.Label(pvp_frame, text="开放时间：每天 12:00–14:00、19:00–21:00；默认3场，可填任意正整数。",



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(5, 3))



        ttk.Label(pvp_frame, text="真人入房挂机（单场最多10分钟），机器人立即胜利结算。",



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(5, 3))



        pvp_row = ttk.Frame(pvp_frame)



        pvp_row.pack(anchor=tk.W, padx=8, pady=(0, 7))



        ttk.Label(pvp_row, text="本次场数：").pack(side=tk.LEFT)



        self.var_pvp_matches = tk.IntVar(value=3)



        ttk.Entry(pvp_row, textvariable=self.var_pvp_matches, width=8).pack(side=tk.LEFT, padx=4)



        ttk.Label(pvp_row, text="场").pack(side=tk.LEFT)



        self.btn_pvp = ttk.Button(pvp_row, text="开始斗神挂机", command=self._start_pvp)



        self.btn_pvp.pack(side=tk.LEFT, padx=12)
        ttk.Label(pvp_row,text='开放时间：12:00–14:00；19:00–21:00（北京时间）').pack(side=tk.LEFT,padx=4)







        forest_frame = ttk.LabelFrame(pages["日常副本"], text="神兽森林方式")



        forest_frame.pack(fill=tk.X, padx=4, pady=5)



        self.var_forest_mode = tk.StringVar(value="sweep")



        forest_modes = (("固定关卡手打，最多4次", "manual"),



                        ("速通扫荡，消耗速通能量", "sweep"),



                        ("只查看本轮怪物和材料，不打副本", "preview"))



        for title, value in forest_modes:



            ttk.Radiobutton(forest_frame, text=title, value=value,



                            variable=self.var_forest_mode).pack(anchor=tk.W, padx=8, pady=2)



        from forest_crystal_ui import ForestCrystalControls
        self.forest_crystal_controls=ForestCrystalControls(self,forest_frame)
        ttk.Label(forest_frame, text="手打和扫荡使用“关卡设置”页的神兽森林关卡；扫荡每次需10点速通能量，能量或免费次数不足即停止，禁止20点券补扫。",



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(1, 5))







        self.var_checks["RUN_ACCEPT_DAILY_TASKS"] = tk.BooleanVar(value=True)



        ttk.Checkbutton(pages["日常副本"], text="刷精英关前接取对应的日常任务",



                        variable=self.var_checks["RUN_ACCEPT_DAILY_TASKS"]).pack(anchor=tk.W, padx=12, pady=(5, 1))



        self.var_daily_task_quota = tk.StringVar(value="VIP 与每日任务次数：尚未读取")



        ttk.Label(pages["日常副本"], textvariable=self.var_daily_task_quota,



                  foreground="gray").pack(anchor=tk.W, padx=12, pady=(0, 4))



        task_page = ttk.LabelFrame(pages["日常副本"], text="自选精英每日任务 · 接取后自动勾选关卡")



        task_page.pack(fill=tk.X, padx=4, pady=5)



        ttk.Label(task_page, text="选择本次要接的任务；已接取的任务不会重复占用今日次数。",



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(3, 1))



        self.var_daily_task_selection = tk.StringVar(value="本次待接：0 项")



        ttk.Label(task_page, textvariable=self.var_daily_task_selection,



                  foreground="gray").pack(anchor=tk.W, padx=8)



        task_canvas = tk.Canvas(task_page, highlightthickness=0, height=140)



        task_bar = ttk.Scrollbar(task_page, orient=tk.VERTICAL, command=task_canvas.yview)



        task_canvas.configure(yscrollcommand=task_bar.set)



        task_bar.pack(side=tk.RIGHT, fill=tk.Y)



        task_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=4)



        task_grid = ttk.Frame(task_canvas)



        task_window = task_canvas.create_window((0, 0), window=task_grid, anchor=tk.NW)



        task_grid.bind("<Configure>", lambda _e: task_canvas.configure(scrollregion=task_canvas.bbox("all")))



        task_canvas.bind("<Configure>", lambda e: task_canvas.itemconfigure(task_window, width=e.width))



        for index, task in enumerate(sorted(_ELITE_DAILY_TASKS.values(), key=lambda row: int(row["mid"]))):



            qid = int(task["id"])



            var = tk.BooleanVar(value=False)



            self.daily_task_vars[qid] = var



            var.trace_add("write", lambda *_args, task_id=qid: self._on_daily_task_toggle(task_id))



            ttk.Checkbutton(task_grid, text=task["name"], variable=var).grid(



                row=index // 4, column=index % 4, sticky=tk.W, padx=8, pady=2)



        elite_page = ttk.LabelFrame(pages["日常副本"], text="精英关卡 · 逐关选择")



        elite_page.pack(fill=tk.X, padx=4, pady=5)



        self.var_elite_card = tk.BooleanVar(value=True)



        ttk.Checkbutton(elite_page, text="每次通关领取一次免费翻牌奖励",



                        variable=self.var_elite_card).pack(anchor=tk.W, padx=8, pady=(3, 5))



        self.var_elite_sell_boss = tk.BooleanVar(value=False)



        self.var_elite_sell_small = tk.BooleanVar(value=False)



        self.var_elite_sell_medicine = tk.BooleanVar(value=False)



        self.var_elite_sell_password = tk.StringVar()



        ttk.Checkbutton(elite_page, text='通关后出售本场新增BOSS材料（含纯BOSS材料礼包）', variable=self.var_elite_sell_boss).pack(anchor=tk.W, padx=8)



        ttk.Checkbutton(elite_page, text='通关后出售本场新增小材料（木／矿／布）', variable=self.var_elite_sell_small).pack(anchor=tk.W, padx=8)



        ttk.Checkbutton(elite_page, text='通关后出售本场新增翻牌药品', variable=self.var_elite_sell_medicine).pack(anchor=tk.W, padx=8)



        sell_row = ttk.Frame(elite_page); sell_row.pack(fill=tk.X, padx=8, pady=4)



        ttk.Label(sell_row, text='出售二级密码（可留空，仅本次使用）').pack(side=tk.LEFT)



        ttk.Entry(sell_row, textvariable=self.var_elite_sell_password, show='*', width=18).pack(side=tk.LEFT, padx=6)



        ttk.Label(elite_page, text='三项独立选择；强化石、原库存和未选类别保留。每场翻牌后出售并核对，失败不重发。', foreground='gray').pack(anchor=tk.W, padx=8)



        ttk.Label(elite_page, text="勾选要刷的关卡；每关只使用当天剩余的免费次数，最多2次。不勾选则跳过精英关。",



                  foreground="gray").pack(anchor=tk.W, padx=8)



        elite_buttons = ttk.Frame(elite_page)



        elite_buttons.pack(fill=tk.X, padx=8, pady=5)



        ttk.Button(elite_buttons, text="全选", command=lambda: [var.set(True) for var in self.elite_vars.values()]).pack(side=tk.LEFT)



        ttk.Button(elite_buttons, text="清空", command=lambda: [var.set(False) for var in self.elite_vars.values()]).pack(side=tk.LEFT, padx=6)



        self.btn_sync_elite = ttk.Button(elite_buttons, text="读取已接任务并勾选关卡",



                                         command=self._sync_elite_tasks)



        self.btn_sync_elite.pack(side=tk.LEFT, padx=12)



        elite_scroll = ttk.Frame(elite_page)



        elite_scroll.pack(fill=tk.X, padx=8)



        elite_canvas = tk.Canvas(elite_scroll, highlightthickness=0, height=185)



        elite_bar = ttk.Scrollbar(elite_scroll, orient=tk.VERTICAL, command=elite_canvas.yview)



        elite_canvas.configure(yscrollcommand=elite_bar.set)



        elite_bar.pack(side=tk.RIGHT, fill=tk.Y)



        elite_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)



        elite_grid = ttk.Frame(elite_canvas)



        elite_window = elite_canvas.create_window((0, 0), window=elite_grid, anchor=tk.NW)



        elite_grid.bind("<Configure>", lambda e: elite_canvas.configure(scrollregion=elite_canvas.bbox("all")))



        elite_canvas.bind("<Configure>", lambda e: elite_canvas.itemconfigure(elite_window, width=e.width))



        for index, stage in enumerate(_ELITE_STAGES):



            mid = int(stage["mid"])



            var = tk.BooleanVar(value=False)



            self.elite_vars[mid] = var



            ttk.Checkbutton(elite_grid, text=f"{(mid - 30000) // 10:02d}  {stage['name']}", variable=var).grid(



                row=index // 4, column=index % 4, sticky=tk.W, padx=9, pady=3)







        nightmare_frame = ttk.LabelFrame(pages["日常副本"], text="噩梦关卡选关 · 共享宝箱")



        nightmare_frame.pack(fill=tk.X, padx=4, pady=5, before=elite_page)



        nightmare_row = ttk.Frame(nightmare_frame)



        nightmare_row.pack(fill=tk.X, padx=8, pady=5)



        ttk.Label(nightmare_row, text="选择要刷的关卡:").pack(side=tk.LEFT)



        self.var_nightmare_stage = tk.StringVar(value="40270 七星殿")



        ttk.Combobox(nightmare_row, textvariable=self.var_nightmare_stage,



                     values=[f"{mid} {name}" for mid, name in _NM_STAGES],



                     width=25, state="readonly").pack(side=tk.LEFT, padx=5)



        self.var_nightmare_card = tk.BooleanVar(value=True)



        ttk.Checkbutton(nightmare_frame, text="每次通关领取翻牌奖励（按下方策略）",



                        variable=self.var_nightmare_card).pack(anchor=tk.W, padx=8, pady=(0, 3))



        self.nightmare_card_strategies = {



            '不使用翡翠钥匙（只翻免费第一张）': 'free',



            '使用静态策略（按牌面宝石盒数量）': 'static',



            '使用动态策略（跨周收益优先，默认）': 'dynamic',



        }



        self.var_nightmare_card_strategy = tk.StringVar(value=list(self.nightmare_card_strategies)[2])



        ttk.Combobox(nightmare_frame, textvariable=self.var_nightmare_card_strategy,



                     values=list(self.nightmare_card_strategies), state='readonly', width=48).pack(anchor=tk.W, padx=8, pady=(0, 3))



        ttk.Label(nightmare_frame, text="静态：0/1盒只翻1张；2盒翻中即停、最多3张；3盒前两张均中即停，否则最多4张；4盒翻满。额外第2/3/4张分别消耗1/2/3把钥匙，最多6把/场。",



                  foreground='gray', wraplength=790).pack(anchor=tk.W, padx=8, pady=(0, 3))



        ttk.Label(nightmare_frame, text="钥匙可积攒，无每周硬上限；库存不足6把时优先高收益。库存充足时部分场次放宽门槛，20场平均约12.33把（模型估算），不在周末强行用完。",



                  foreground="gray", wraplength=790).pack(anchor=tk.W, padx=8, pady=(0, 3))



        ttk.Label(nightmare_frame, text="只用当前剩余的共享宝箱机会，最多打2次；逐件领取宝箱奖励，不自动兑换时光能量或花点券。",



                  foreground="gray", wraplength=790).pack(anchor=tk.W, padx=8, pady=(0, 6))







        boss_page = ttk.Frame(notebook, padding=8)



        notebook.add(boss_page, text="BOSS挑战")



        boss_canvas = tk.Canvas(boss_page, highlightthickness=0)



        boss_scroll = ttk.Scrollbar(boss_page, orient=tk.VERTICAL, command=boss_canvas.yview)



        boss_canvas.configure(yscrollcommand=boss_scroll.set)



        boss_scroll.pack(side=tk.RIGHT, fill=tk.Y)



        boss_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)



        boss_body = ttk.Frame(boss_canvas)



        boss_window = boss_canvas.create_window((0, 0), window=boss_body, anchor=tk.NW)



        boss_body.bind("<Configure>", lambda e: boss_canvas.configure(scrollregion=boss_canvas.bbox("all")))



        boss_canvas.bind("<Configure>", lambda e: boss_canvas.itemconfigure(boss_window, width=e.width))



        world_frame = ttk.LabelFrame(boss_body, text="世界 Boss · 三界共伐")



        world_frame.pack(fill=tk.X, padx=4, pady=6)



        ttk.Label(world_frame,



                  text="开放时间：周一至周五 12:00–15:00、18:00–21:00；周六、周日 09:00–21:00。",



                  foreground="gray", wraplength=790).pack(anchor=tk.W, padx=8, pady=(6, 2))



        world_row = ttk.Frame(world_frame)



        world_row.pack(fill=tk.X, padx=8, pady=8)



        ttk.Label(world_row, text="目标 Boss:").pack(side=tk.LEFT)



        world_choices = ["%s %s" % (row["id"], row["name"])



                         for row in _BOSS_CATALOG["world"]]



        self.var_world_boss = tk.StringVar(value=world_choices[-2])



        ttk.Combobox(world_row, textvariable=self.var_world_boss,



                     values=world_choices, width=26, state="readonly").pack(side=tk.LEFT, padx=5)



        world_damage = ttk.Frame(world_frame)



        world_damage.pack(fill=tk.X, padx=8, pady=(0, 5))



        ttk.Label(world_damage, text="兜底每秒期望伤害 x:").pack(side=tk.LEFT)



        self.var_world_dps = tk.StringVar(value="300000")



        ttk.Entry(world_damage, textvariable=self.var_world_dps, width=13).pack(side=tk.LEFT, padx=5)



        ttk.Label(world_damage, text="目标占最大血量:").pack(side=tk.LEFT, padx=(14, 2))



        self.var_world_target = tk.StringVar(value="5.05")



        ttk.Entry(world_damage, textvariable=self.var_world_target, width=7).pack(side=tk.LEFT)



        ttk.Label(world_damage, text="%").pack(side=tk.LEFT)



        self.var_world_attack_target = tk.BooleanVar(value=True)



        ttk.Checkbutton(world_frame, text="使用目标伤害作为挂机切换点",



                        variable=self.var_world_attack_target).pack(anchor=tk.W, padx=8, pady=(0, 4))



        self.var_world_idle = tk.BooleanVar(value=False)



        ttk.Checkbutton(world_frame, text="开启挂机模式：达标后每秒随机上报0～10000；未设目标则进房后直接挂机",



                        variable=self.var_world_idle).pack(anchor=tk.W, padx=8, pady=(0, 4))



        ttk.Label(world_frame,



                  text="默认按真实角色面板、真实技能栏和伤害公式逐段累计，每2秒上报；技能CD、蓝耗、暴击、死亡复活按实际节奏。模型不可用时才改用每秒 x/4～7x/4 随机；挂机时每秒上报 0～10000。自动进入当前血量最高的存活房间并等待结算。",



                  foreground="gray", wraplength=790).pack(anchor=tk.W, padx=8, pady=(0, 7))



        self.btn_world_boss = ttk.Button(world_frame, text="开始世界 Boss",



                                         command=self._start_world_boss)



        self.btn_world_boss.pack(anchor=tk.W, padx=8, pady=(0, 10))
        from world_boss_room_ui import WorldBossRoomPage
        self.world_boss_room_page = WorldBossRoomPage(self, world_frame)







        union_frame = ttk.LabelFrame(boss_body, text="联盟 Boss · 九灵元圣")



        union_frame.pack(fill=tk.X, padx=4, pady=6)



        ttk.Label(union_frame,



                  text="阶数由盟主设定；进入时自动识别服务器当前关卡，并按该阶最大血量计算。",



                  foreground="gray", wraplength=790).pack(anchor=tk.W, padx=8, pady=6)



        union_damage = ttk.Frame(union_frame)



        union_damage.pack(fill=tk.X, padx=8, pady=(0, 5))



        ttk.Label(union_damage, text="每秒期望伤害 x:").pack(side=tk.LEFT)



        self.var_union_dps = tk.StringVar(value="")



        ttk.Entry(union_damage, textvariable=self.var_union_dps, width=13).pack(side=tk.LEFT, padx=5)



        ttk.Label(union_damage, text="留空按阶数自动计算").pack(side=tk.LEFT, padx=(0, 12))



        ttk.Label(union_damage, text="目标占最大血量:").pack(side=tk.LEFT)



        self.var_union_target = tk.StringVar(value="0.2")



        ttk.Entry(union_damage, textvariable=self.var_union_target, width=7).pack(side=tk.LEFT, padx=4)



        ttk.Label(union_damage, text="%").pack(side=tk.LEFT)



        self.var_union_attack_target = tk.BooleanVar(value=True)



        ttk.Checkbutton(union_frame, text="使用目标伤害作为挂机切换点",



                        variable=self.var_union_attack_target).pack(anchor=tk.W, padx=8, pady=(0, 4))



        self.var_union_idle = tk.BooleanVar(value=False)



        ttk.Checkbutton(union_frame, text="开启挂机模式：达标后每秒随机上报0～10000；未设目标则进房后直接挂机",



                        variable=self.var_union_idle).pack(anchor=tk.W, padx=8, pady=(0, 4))



        columns = ("level", "hp", "per_second", "per_five")



        rate_area = ttk.Frame(union_frame)



        rate_area.pack(fill=tk.X, padx=8, pady=(2, 5))



        rate_table = ttk.Treeview(rate_area, columns=columns, show="headings", height=7)



        rate_scroll = ttk.Scrollbar(rate_area, orient=tk.VERTICAL, command=rate_table.yview)



        rate_table.configure(yscrollcommand=rate_scroll.set)



        for col, title, width in (("level", "阶数", 65), ("hp", "最大血量", 180),



                                  ("per_second", "每秒约", 125),



                                  ("per_five", "每5秒约", 125)):



            rate_table.heading(col, text=title)



            rate_table.column(col, width=width, anchor=tk.CENTER)



        for row in _BOSS_CATALOG["union"]:



            hp = row["hpMax"]



            rate_table.insert("", tk.END, values=("%s阶" % row["level"],



                            "%s" % format(hp, ","),



                            "%s" % format(round(hp / 30000), ","),



                            "%s" % format(round(hp / 6000), ",")))



        rate_table.pack(side=tk.LEFT, fill=tk.X, expand=True)



        rate_scroll.pack(side=tk.RIGHT, fill=tk.Y)



        ttk.Label(union_frame,



                  text="每秒伤害在 x/4～7x/4 之间均匀随机；挂机时每秒上报 0～10000。留空时 x 按当前阶数每分钟最大血量的 0.2% 计算。",



                  foreground="gray", wraplength=790).pack(anchor=tk.W, padx=8, pady=(0, 7))



        self.btn_union_boss = ttk.Button(union_frame, text="开始联盟 Boss",



                                         command=self._start_union_boss)



        self.btn_union_boss.pack(anchor=tk.W, padx=8, pady=(0, 10))







        rob_page = ttk.Frame(notebook, padding=8)



        notebook.add(rob_page, text="通天河")



        rob_canvas = tk.Canvas(rob_page, highlightthickness=0)



        rob_vertical = ttk.Scrollbar(rob_page, orient=tk.VERTICAL, command=rob_canvas.yview)



        rob_horizontal = ttk.Scrollbar(rob_page, orient=tk.HORIZONTAL, command=rob_canvas.xview)



        rob_canvas.configure(yscrollcommand=rob_vertical.set, xscrollcommand=rob_horizontal.set)



        rob_canvas.grid(row=0, column=0, sticky='nsew')



        rob_vertical.grid(row=0, column=1, sticky='ns')



        rob_horizontal.grid(row=1, column=0, sticky='ew')



        rob_page.rowconfigure(0, weight=1)



        rob_page.columnconfigure(0, weight=1)



        rob_body = ttk.Frame(rob_canvas)



        rob_window = rob_canvas.create_window((0,0), window=rob_body, anchor=tk.NW)



        def resize_rob_body(event=None):



            rob_canvas.itemconfigure(rob_window, width=max(rob_canvas.winfo_width(),rob_body.winfo_reqwidth()))



            rob_canvas.configure(scrollregion=rob_canvas.bbox('all'))



        rob_body.bind('<Configure>', resize_rob_body)



        rob_canvas.bind('<Configure>', resize_rob_body)



        def scroll_rob(event):



            if notebook.select()!=str(rob_page) or not str(event.widget).startswith(str(rob_page)):



                return



            rob_canvas.yview_scroll(-int(event.delta/120),'units')



            return 'break'



        self.root.bind_all('<MouseWheel>', scroll_rob, add='+')



        self.ttr_canvas = rob_canvas



        rob_frame = ttk.LabelFrame(rob_body, text="发船 / 免费刷新升级 / 领奖 / 抢船")



        rob_frame.pack(fill=tk.X, padx=4, pady=8)



        ttk.Label(rob_frame, text="发船／刷新自动选择主角色等级最低且≥40级的存档，同级优先槽号较小者；领奖存档默认跟随抢船存档，也可手动选为不同槽位；奖励进入领奖存档。",



                  wraplength=790).pack(anchor=tk.W, padx=8, pady=(8, 4))



        self.var_ttr_slots = {action: tk.StringVar(value="")



                              for action in ("escort", "reward", "rob")}



        previous_ttr_rob=[self.var_ttr_slots['rob'].get()]
        def follow_ttr_reward(*_):
            old=previous_ttr_rob[0];new=self.var_ttr_slots['rob'].get()
            if self.var_ttr_slots['reward'].get() in ('',old):
                self.var_ttr_slots['reward'].set(new)
            previous_ttr_rob[0]=new
        self.var_ttr_slots['rob'].trace_add('write',follow_ttr_reward)
        from tongtian_escort_strategy import STRATEGIES as TTR_ESCORT_STRATEGIES
        self.ttr_escort_strategies=TTR_ESCORT_STRATEGIES
        self.var_ttr_escort_strategy=tk.StringVar(value=TTR_ESCORT_STRATEGIES['free'])
        strategy_row=ttk.Frame(rob_frame);strategy_row.pack(anchor=tk.W,padx=8,pady=4)
        ttk.Label(strategy_row,text='发船策略：').pack(side=tk.LEFT)
        ttk.Combobox(strategy_row,textvariable=self.var_ttr_escort_strategy,values=list(TTR_ESCORT_STRATEGIES.values()),state='readonly',width=48).pack(side=tk.LEFT,padx=6)
        ttk.Label(rob_frame,text='图示两套方案均只分配每日共享的5次免费刷新；按服务器今日已发船数选择第1／2／3船。每次只发当前一船，到达后独立领奖，再执行下一船；不购买次数。',wraplength=790).pack(anchor=tk.W,padx=8,pady=4)
        self.btn_ttr_actions = {}



        for action, label in (("escort", "发船/刷新"), ("reward", "领奖"), ("rob", "抢船")):



            row = ttk.Frame(rob_frame)



            row.pack(anchor=tk.W, padx=8, pady=4)



            ttk.Label(row, text=label + "存档:", width=9).pack(side=tk.LEFT)



            if action=='escort':
                ttk.Label(row,text='自动选择最低等级≥40存档').pack(side=tk.LEFT,padx=6)
            else:
                ttk.Combobox(row,textvariable=self.var_ttr_slots[action],values=[str(i) for i in range(8)],width=5,state='readonly').pack(side=tk.LEFT,padx=6)

            buttons = (("status", "查看船档"), ("refresh", "免费刷新一次"),



                       ("upgrade", "免费刷到海舰"), ("escort", "发船")) if action == "escort" else ((action, "执行" + label),)



            for operation, button_text in buttons:



                button = ttk.Button(row, text=button_text,



                                    command=lambda name=operation: self._start_tongtian_action(name))



                button.pack(side=tk.LEFT, padx=5)



                self.btn_ttr_actions[operation] = button



        ttk.Label(rob_frame, text="船档：木舟→宝船→银帆→海舰。每日免费刷新最多5次；刷新只走免费路由，用完即停，不使用点券。",



                  wraplength=790, foreground="gray").pack(anchor=tk.W, padx=8, pady=(2, 8))



        ttk.Label(rob_frame, text="优先海舰等大船；等级差不超过10级、战力比不低于0.6；每天最多4次。",



                  wraplength=790).pack(anchor=tk.W, padx=8, pady=(8, 4))



        ttk.Label(rob_frame, text="每10秒补充候选，按船主ID＋发船时间去重并保留旧船；优先刚解保的船，临近解保时暂缓其他普通请求。0/2战斗中保留，1/2战斗中放弃，海舰成功后优先连抢。",



                  wraplength=790).pack(anchor=tk.W, padx=8, pady=4)



        self.var_ttr_target_mode = tk.StringVar(value="fallback")



        mode_row = ttk.Frame(rob_frame)



        mode_row.pack(anchor=tk.W, padx=8, pady=4)



        ttk.Radiobutton(mode_row, text="仅抢海舰", variable=self.var_ttr_target_mode,



                        value="sea_only").pack(side=tk.LEFT, padx=(0, 18))



        ttk.Radiobutton(mode_row, text="优先海舰；没有可抢海舰时按船档从高到低抢其他船", variable=self.var_ttr_target_mode,



                        value="fallback").pack(side=tk.LEFT)



        self.var_ttr_full_reward=tk.BooleanVar(value=True)
        ttk.Checkbutton(rob_frame,text='仅抢满额奖励目标（按自身和船主等级自动筛选）',variable=self.var_ttr_full_reward).pack(anchor=tk.W,padx=8,pady=4)
        from tongtian_reward_filter import explanation as ttr_level_explanation
        ttk.Label(rob_frame,text=ttr_level_explanation(),wraplength=790).pack(anchor=tk.W,padx=28,pady=(0,4))
        self.var_ttr_qi_only = tk.BooleanVar(value=True)



        ttk.Checkbutton(rob_frame, text="仅筛选天清气／地浊气海舰（开启后不抢其他货物或低档船）",



                        variable=self.var_ttr_qi_only).pack(anchor=tk.W, padx=8, pady=4)



        cargo_row = ttk.Frame(rob_frame)



        cargo_row.pack(anchor=tk.W, padx=28, pady=(0,4))



        self.var_ttr_qi_kind = tk.StringVar(value="both")



        cargo_buttons = [



            ttk.Radiobutton(cargo_row, text=label, variable=self.var_ttr_qi_kind, value=value)



            for label,value in (("天清气＋地浊气","both"),("天清气","heaven"),("地浊气","earth"))]



        for cargo_button in cargo_buttons:



            cargo_button.pack(side=tk.LEFT, padx=(0,16))



        def update_cargo_options(*args):



            for cargo_button in cargo_buttons:



                cargo_button.configure(state='normal' if self.var_ttr_qi_only.get() else 'disabled')



        self.var_ttr_qi_only.trace_add('write', update_cargo_options)



        update_cargo_options()



        self.var_ttr_chain_twice = tk.BooleanVar(value=True)



        ttk.Checkbutton(rob_frame, text="原船连抢两次（成功后优先再抢同一艘海舰）",



                        variable=self.var_ttr_chain_twice).pack(anchor=tk.W, padx=8, pady=4)



        rob_row = ttk.Frame(rob_frame)



        rob_row.pack(anchor=tk.W, padx=8, pady=8)



        ttk.Label(rob_row, text="最长等待（分钟）:").pack(side=tk.LEFT)



        self.var_rob_wait = tk.IntVar(value=10)



        ttk.Spinbox(rob_row, from_=1, to=60, textvariable=self.var_rob_wait,



                    width=5).pack(side=tk.LEFT, padx=6)



        ttk.Label(rob_row, text="入场后结算等待（秒）:").pack(side=tk.LEFT, padx=(15,0))



        self.var_ttr_battle_wait = tk.StringVar(value="25")



        ttk.Spinbox(rob_row, from_=1, to=30, increment=1, textvariable=self.var_ttr_battle_wait,



                    width=6).pack(side=tk.LEFT, padx=6)







        timeboat_page = ttk.Frame(notebook, padding=8)



        notebook.add(timeboat_page, text="时光之舟")



        timeboat_frame = ttk.LabelFrame(timeboat_page, text="时光能量兑换副本次数")



        timeboat_frame.pack(fill=tk.X, padx=4, pady=8)



        ttk.Label(timeboat_frame, text="选择领取次数的存档；每次兑换前检查当前能量、每周兑换上限和副本剩余次数。",



                  wraplength=790).pack(anchor=tk.W, padx=8, pady=(8, 6))



        timeboat_slot_row = ttk.Frame(timeboat_frame)



        timeboat_slot_row.pack(anchor=tk.W, padx=8, pady=4)



        ttk.Label(timeboat_slot_row, text="兑换存档:").pack(side=tk.LEFT)



        self.var_timeboat_slot = tk.StringVar(value="")



        ttk.Combobox(timeboat_slot_row, textvariable=self.var_timeboat_slot,



                     values=[str(i) for i in range(8)], width=5,



                     state="readonly").pack(side=tk.LEFT, padx=7)



        self.btn_timeboat_status = ttk.Button(timeboat_slot_row, text="查看能量与兑换状态",



                                               command=lambda: self._start_timeboat("status"))



        self.btn_timeboat_status.pack(side=tk.LEFT, padx=10)



        timeboat_row = ttk.Frame(timeboat_frame)



        timeboat_row.pack(anchor=tk.W, padx=8, pady=6)



        ttk.Label(timeboat_row, text="兑换项目:").pack(side=tk.LEFT)



        self.var_timeboat_choice = tk.StringVar(value="")



        timeboat_choices = ["%s %s（%s能量/次，周上限%s）" %



                            (item["id"], item["name"], item["consume_count"], item["weekChangeNum"])



                            for item in sorted(_TIME_ENERGY_CATALOG.values(),



                                               key=lambda item: (item["order"], item["id"]))]



        ttk.Combobox(timeboat_row, textvariable=self.var_timeboat_choice,



                     values=timeboat_choices, width=43,



                     state="readonly").pack(side=tk.LEFT, padx=7)



        ttk.Label(timeboat_row, text="次数:").pack(side=tk.LEFT, padx=(10, 2))



        self.var_timeboat_times = tk.IntVar(value=1)



        ttk.Spinbox(timeboat_row, from_=1, to=15, textvariable=self.var_timeboat_times,



                    width=5).pack(side=tk.LEFT)



        self.btn_timeboat_exchange = ttk.Button(timeboat_frame, text="兑换所选次数",



                                                 command=lambda: self._start_timeboat("exchange"))



        self.btn_timeboat_exchange.pack(anchor=tk.W, padx=8, pady=(2, 8))
        ttk.Button(timeboat_frame, text="兑换并按原配置执行", command=lambda: self._start_timeboat("exchange_run")).pack(anchor=tk.W, padx=8, pady=(2, 8))



        ttk.Label(timeboat_frame, text="兑换并执行：循环“兑换1次＋按原配置执行1次”；只兑换按钮仍保留。次数已满、能量不足、周额度用尽或执行失败时停止。",



                  foreground="gray", wraplength=790).pack(anchor=tk.W, padx=8, pady=(0, 8))







        weekly = pages["周常副本／领奖"]



        halo_frame = ttk.LabelFrame(weekly, text="十绝阵设置")



        halo_frame.pack(fill=tk.X, padx=4, pady=8)



        halo_row = ttk.Frame(halo_frame)



        halo_row.pack(fill=tk.X, padx=8, pady=8)

        halo_team_row = ttk.Frame(halo_frame)

        halo_team_row.pack(fill=tk.X, padx=8, pady=(0, 8))

        ttk.Label(halo_team_row, text="三账号模式:").pack(side=tk.LEFT)

        self.halo_team_combos = []
        self.halo_slot_combos = []
        self.halo_claim_vars = []
        self.halo_claim_buttons = []

        _halo_saved = []
        _halo_saved_slots = []
        _halo_saved_claims = []
        try:

            with open(HALO_TEAM_CONFIG, encoding="utf-8") as _stream:

                _halo_data = json.load(_stream) or {}
            _halo_saved = _halo_data.get("accounts") or []
            _halo_saved_slots = _halo_data.get("slots") or []
            _halo_saved_claims = _halo_data.get("claim") or []

        except (OSError, ValueError):

            pass

        for _halo_idx in range(3):

            _halo_combo = ttk.Combobox(halo_team_row, width=15, state="readonly")

            _halo_combo.pack(side=tk.LEFT, padx=(4, 0))

            if _halo_idx < len(_halo_saved):

                _halo_combo.set(_halo_saved[_halo_idx])

            self.halo_team_combos.append(_halo_combo)

            ttk.Label(halo_team_row, text="槽").pack(side=tk.LEFT, padx=(6, 0))
            _halo_slot = ttk.Combobox(halo_team_row, width=3, state="readonly",
                                      values=[str(i) for i in range(8)])
            _halo_slot.set(str(_halo_saved_slots[_halo_idx]) if _halo_idx < len(_halo_saved_slots) else "0")
            _halo_slot.pack(side=tk.LEFT, padx=(2, 0))
            self.halo_slot_combos.append(_halo_slot)

            _halo_claim = tk.BooleanVar(
                value=bool(_halo_saved_claims[_halo_idx]) if _halo_idx < len(_halo_saved_claims) else True)
            _halo_claim_btn = ttk.Checkbutton(halo_team_row, text="领", variable=_halo_claim)
            _halo_claim_btn.pack(side=tk.LEFT, padx=(2, 0))
            self.halo_claim_vars.append(_halo_claim)
            self.halo_claim_buttons.append(_halo_claim_btn)

        self.btn_halo_team = ttk.Button(halo_team_row, text="三人组队开打",
                                        command=self.launch_halo_team)

        self.btn_halo_team.pack(side=tk.LEFT, padx=(8, 0))



        ttk.Label(halo_row, text="模式:").pack(side=tk.LEFT)

        self.var_halo_score = tk.StringVar(value="单人3000分")

        self.cmb_halo_mode = ttk.Combobox(halo_row, textvariable=self.var_halo_score,
                     values=["单人1000分", "三人3000分", "三人模式2（仅主号领奖）", "单人3000分"],
                     width=21, state="readonly")

        self.cmb_halo_mode.pack(side=tk.LEFT, padx=4)

        self.cmb_halo_mode.bind("<<ComboboxSelected>>", lambda _e: self._sync_halo_mode())



        ttk.Label(halo_frame,



                  text="每天恢复1次，最多存5次。单人档只操作当前账号；三人档会登录三个账号同房正常开局；模式2只由主账号（第一个）领奖，副账号不领、保留次数。",



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(0, 8))

        self._sync_halo_mode()



        tower_frame = ttk.LabelFrame(weekly, text="镇妖塔设置")



        tower_frame.pack(fill=tk.X, padx=4, pady=8)



        tower_row = ttk.Frame(tower_frame)



        tower_row.pack(fill=tk.X, padx=8, pady=8)



        ttk.Label(tower_row, text="目标层段:").pack(side=tk.LEFT)



        self.var_tower_range = tk.StringVar(value="自动最高已解锁")



        ttk.Combobox(tower_row, textvariable=self.var_tower_range,



                     values=["自动最高已解锁"] + DEMON_TOWER_RANGES,



                     width=21, state="readonly").pack(side=tk.LEFT, padx=4)



        ttk.Label(tower_frame,



                  text="只列1–5、11–15等五层段；逐组切换。每天增加1次挑战，最多存5次。",



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(0, 8))



        mh_frame = ttk.LabelFrame(weekly, text="蛮荒设置")



        mh_frame.pack(fill=tk.X, padx=4, pady=8)



        mh_row = ttk.Frame(mh_frame)



        mh_row.pack(fill=tk.X, padx=8, pady=8)



        ttk.Label(mh_row, text="关卡:").pack(side=tk.LEFT)



        self.var_mh_stage = tk.StringVar(value="")



        mh_opts = [""] + [str(m) + " " + n for m, n in MANHUANG_MIDS]



        ttk.Combobox(mh_row, textvariable=self.var_mh_stage, values=mh_opts,



                     width=22, state="readonly").pack(side=tk.LEFT, padx=4)



        ttk.Label(mh_row, text="模式:").pack(side=tk.LEFT, padx=(12, 2))



        self.var_mh_mode = tk.StringVar(value="多人版(2–4件)")



        self.cmb_mh_mode = ttk.Combobox(mh_row, textvariable=self.var_mh_mode,
                     values=["多人版(2–4件)", "单人版(1–3件)", "多人组队·2号", "多人组队·3号"],
                     width=17, state="readonly")

        self.cmb_mh_mode.pack(side=tk.LEFT, padx=4)

        self.cmb_mh_mode.bind("<<ComboboxSelected>>", lambda _e: self._sync_mh_team())



        ttk.Label(mh_frame,



                  text="留空自动选择最高已解锁关；共享宝箱每天增加2次，最多累积10次。多人组队只支持2~3个账号（服务器只有3个座位）。",



                  foreground="gray").pack(anchor=tk.W, padx=8, pady=(0, 8))

        mh_team_row = ttk.Frame(mh_frame)

        mh_team_row.pack(fill=tk.X, padx=8, pady=(0, 8))

        ttk.Label(mh_team_row, text="组队账号:").pack(side=tk.LEFT)

        self.manhuang_team_combos = []
        self.manhuang_slot_combos = []
        self.manhuang_claim_vars = []
        self.manhuang_claim_buttons = []

        _mh_saved = ["zzqzzs123", "xyh13416626694", "13979244278xx"]
        _mh_saved_slots = []
        _mh_saved_claims = []
        try:
            with open(MANHUANG_TEAM_CONFIG, encoding="utf-8") as _stream:
                _mh_data = json.load(_stream) or {}
            _mh_saved = _mh_data.get("accounts") or _mh_saved
            _mh_saved_slots = _mh_data.get("slots") or []
            _mh_saved_claims = _mh_data.get("claim") or []
        except (OSError, ValueError):
            pass

        for _mh_idx in range(3):
            _mh_combo = ttk.Combobox(mh_team_row, width=16, state="readonly")
            _mh_combo.pack(side=tk.LEFT, padx=(4, 0))
            if _mh_idx < len(_mh_saved):
                _mh_combo.set(_mh_saved[_mh_idx])
            self.manhuang_team_combos.append(_mh_combo)

            ttk.Label(mh_team_row, text="槽").pack(side=tk.LEFT, padx=(6, 0))
            _mh_slot = ttk.Combobox(mh_team_row, width=3, state="readonly",
                                    values=[str(i) for i in range(8)])
            _mh_slot.set(str(_mh_saved_slots[_mh_idx]) if _mh_idx < len(_mh_saved_slots) else "0")
            _mh_slot.pack(side=tk.LEFT, padx=(2, 0))
            self.manhuang_slot_combos.append(_mh_slot)

            _mh_claim = tk.BooleanVar(
                value=bool(_mh_saved_claims[_mh_idx]) if _mh_idx < len(_mh_saved_claims) else True)
            _mh_claim_btn = ttk.Checkbutton(mh_team_row, text="领", variable=_mh_claim)
            _mh_claim_btn.pack(side=tk.LEFT, padx=(2, 0))
            self.manhuang_claim_vars.append(_mh_claim)
            self.manhuang_claim_buttons.append(_mh_claim_btn)

        self.btn_manhuang_team = ttk.Button(mh_team_row, text="组队开打",
                                            command=self.launch_manhuang_team)

        self.btn_manhuang_team.pack(side=tk.LEFT, padx=(8, 0))

        self._sync_mh_team()



        maze_frame = ttk.LabelFrame(weekly, text="星斗幻境设置")



        maze_frame.pack(fill=tk.X, padx=4, pady=8)



        ttk.Label(maze_frame,



                  text="一次通关三大层；重置后第1层到第2层有3分钟强制间隔，程序按服务器计时等待。",



                  foreground="gray", wraplength=820).pack(anchor=tk.W, padx=8, pady=8)







        times_frame = ttk.LabelFrame(settings_body, text="次数与运行选项")



        times_frame.pack(fill=tk.X, padx=4, pady=2)



        for label, key, lo, hi, default in TIMES_TASKS:



            if key == "CARD_CAVE_TIMES":



                continue



            ttk.Label(times_frame, text=label + ":").pack(side=tk.LEFT, padx=(8, 2))



            var = tk.IntVar(value=default)



            self.var_times[key] = var



            ttk.Spinbox(times_frame, from_=lo, to=hi, textvariable=var, width=5).pack(side=tk.LEFT)



        # 模拟战斗延迟开关(单独一行)



        delay_frame = ttk.Frame(settings_body)



        delay_frame.pack(fill=tk.X, padx=4, pady=2)



        self.var_fight_delay = tk.BooleanVar(value=True)



        ttk.Checkbutton(delay_frame, text="模拟战斗延迟(2-3秒,降低联机检测风险)", variable=self.var_fight_delay).pack(side=tk.LEFT, padx=8)







        stage_frame = ttk.LabelFrame(settings_body, text="自选关卡（留空=自动打最高已解锁关）")



        stage_frame.pack(fill=tk.X, padx=4, pady=4)



        for i, (label, key, items) in enumerate(STAGE_LABELS):



            row, col = divmod(i, 2)



            f = ttk.Frame(stage_frame)



            f.grid(row=row, column=col, padx=6, pady=2, sticky=tk.W)



            ttk.Label(f, text=label + ":").pack(side=tk.LEFT)



            var = tk.StringVar(value="300113 丹熏山" if key == "wanxiang" else "")



            self.var_stage[key] = var



            opts = ([""] if key != "wanxiang" else []) + [str(m) + " " + n for m, n in items]



            ttk.Combobox(f, textvariable=var, values=opts, width=22, state="readonly").pack(side=tk.LEFT, padx=2)







        ttk.Label(stage_frame,



                  text="九宫玄塔（普通1–9层）：默认优先走可掉落本层法宝材料的宝箱房，拾取后进入Boss房；第二层宝箱还可能掉落仙柳枝。奖励随机，不保证出材料。第一层走房间2分支。每日全塔共享3次免费机会，用尽后停止，不自动花点券或兑换次数。",



                  foreground="gray", wraplength=720).grid(



                      row=(len(STAGE_LABELS) + 1) // 2, column=0, columnspan=2,



                      sticky=tk.W, padx=8, pady=(5, 8))







        from pet_worldcup import WorldCupPage



        self.worldcup_page = WorldCupPage(self, notebook, ACCOUNT_FILE,



                                         os.path.join(HERE, '擂台预测检测'))







        farm_page = ttk.Frame(notebook)



        notebook.add(farm_page, text="一键刷图")



        farm_canvas = tk.Canvas(farm_page, highlightthickness=0)



        farm_scrollbar = ttk.Scrollbar(farm_page, orient=tk.VERTICAL, command=farm_canvas.yview)



        farm_canvas.configure(yscrollcommand=farm_scrollbar.set)



        farm_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)



        farm_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)



        farm = ttk.Frame(farm_canvas, padding=12)



        farm_window = farm_canvas.create_window((0, 0), window=farm, anchor=tk.NW)



        farm.bind('<Configure>', lambda e: farm_canvas.configure(scrollregion=farm_canvas.bbox('all')))



        farm_canvas.bind('<Configure>', lambda e: farm_canvas.itemconfigure(farm_window, width=e.width))



        farm_canvas.bind('<MouseWheel>', lambda e: farm_canvas.yview_scroll(-int(e.delta / 120), 'units'))



        self.farm_canvas = farm_canvas



        farm_stage = ttk.LabelFrame(farm, text="选择主线关卡")



        farm_stage.pack(fill=tk.X, padx=4, pady=6)



        farm_row = ttk.Frame(farm_stage)



        farm_row.pack(fill=tk.X, padx=8, pady=8)



        ttk.Label(farm_row, text="关卡:").pack(side=tk.LEFT)



        self.var_farm_stage = tk.StringVar(value="")



        farm_names = [str(s["mid"]) + " " + s["name"] for s in _MAIN_CUSTOM_STAGES]



        ttk.Combobox(farm_row, textvariable=self.var_farm_stage,



                     values=farm_names, width=29, state="readonly").pack(side=tk.LEFT, padx=4)



        ttk.Label(farm_row, text="次数:").pack(side=tk.LEFT, padx=(16, 2))



        self.var_farm_times = tk.IntVar(value=1)



        ttk.Spinbox(farm_row, from_=1, to=20, textvariable=self.var_farm_times,



                    width=5).pack(side=tk.LEFT)



        ttk.Label(farm_row, text="每批最多20次", foreground="gray").pack(side=tk.LEFT, padx=8)







        farm_result = ttk.LabelFrame(farm, text="结算方式")



        farm_result.pack(fill=tk.X, padx=4, pady=6)



        self.var_farm_result = tk.StringVar(value="keep")



        ttk.Radiobutton(farm_result, text="失败结算：passNum 不增加，已拾取材料保留",



                        variable=self.var_farm_result, value="keep").pack(anchor=tk.W, padx=8, pady=4)



        ttk.Radiobutton(farm_result, text="通关结算：passNum 增加",



                        variable=self.var_farm_result, value="increase").pack(anchor=tk.W, padx=8, pady=4)







        farm_loot = ttk.LabelFrame(farm, text="拾取范围")



        farm_loot.pack(fill=tk.X, padx=4, pady=6)



        self.var_farm_loot = tk.StringVar(value="spiritPet")



        for value, label in (



            ("small", "仅小材料：不进入 Boss 房"),



            ("boss", "小材料＋普通 Boss 材料：进入普通 Boss 房"),



            ("hidden", "小材料＋隐藏 Boss 掉落：只适用于有隐藏 Boss 房的关卡"),



            ("currency", "仅要角色/宠物经验和灵魂：不拾取材料，不进入 Boss 房"),
            ("spiritPet", "仅要灵魂＋宠物经验：不拾取角色经验和材料，不进入 Boss 房"),



        ):



            ttk.Radiobutton(farm_loot, text=label, variable=self.var_farm_loot,



                            value=value).pack(anchor=tk.W, padx=8, pady=4)







        farm_timing = ttk.LabelFrame(farm, text="等待时间（秒）")



        farm_timing.pack(fill=tk.X, padx=4, pady=6)



        timing_row = ttk.Frame(farm_timing)



        timing_row.pack(anchor=tk.W, padx=8, pady=8)



        self.var_farm_base_delay = tk.IntVar(value=40)



        self.var_farm_boss_delay = tk.IntVar(value=10)



        self.var_farm_round_delay = tk.IntVar(value=5)



        for title, var in (("主图", self.var_farm_base_delay),



                           ("Boss房", self.var_farm_boss_delay),



                           ("每次之间", self.var_farm_round_delay)):



            ttk.Label(timing_row, text=title + ":").pack(side=tk.LEFT, padx=(8, 2))



            ttk.Spinbox(timing_row, from_=0, to=300, textvariable=var,



                        width=5).pack(side=tk.LEFT)



        ttk.Label(farm, text="隐藏 Boss 房若配置同时掉落普通 Boss 材料，会一并拾取；实际掉落以服务器返回为准。",



                  foreground="gray", wraplength=790).pack(anchor=tk.W, padx=8, pady=5)



        ttk.Label(farm, text="穹顶宫首次通关曾在测试槽触发封禁，程序会阻止该关自动首次通关。",



                  foreground="red", wraplength=790).pack(anchor=tk.W, padx=8, pady=3)



        self.btn_farm = ttk.Button(farm, text="开始一键刷图", command=self._start_farm)



        self.btn_farm.pack(anchor=tk.W, padx=8, pady=12)







        self.fun_activity_page = ttk.Frame(notebook)
        notebook.add(self.fun_activity_page, text='趣味活动')
        self.fun_activity_notebook = ttk.Notebook(self.fun_activity_page)
        self.fun_activity_notebook.pack(fill=tk.BOTH, expand=True)

        self.backup_function_page = ttk.Frame(notebook)
        notebook.add(self.backup_function_page, text='备用功能')
        self.backup_function_notebook = ttk.Notebook(self.backup_function_page)
        self.backup_function_notebook.pack(fill=tk.BOTH, expand=True)

        from feature_ui import attach



        attach(self, notebook, pages)
        from time_crystal_ui import TimeCrystalPanel
        self.time_crystal_panel=TimeCrystalPanel(self,timeboat_page)
        self.feature_buttons.extend(self.time_crystal_panel.buttons)



        from old_activity_ui import OldActivityPage



        self.old_activity_page = OldActivityPage(self, self.backup_function_notebook)



        self.feature_buttons.extend(self.old_activity_page.buttons)
        self.feature_buttons.extend(self.pet_arena_paid_panel.buttons)

        from config_sync_ui import ConfigSyncPage

        self.config_sync_page = ConfigSyncPage(self, self.backup_function_notebook)



        from bag_warehouse_ui import BagWarehousePage



        self.bag_warehouse_page = BagWarehousePage(self, self.backup_function_notebook)



        self.feature_buttons.extend(self.bag_warehouse_page.buttons)



        from material_exchange_ui import MaterialExchangePage



        self.material_exchange_page = MaterialExchangePage(self, self.backup_function_notebook)



        self.feature_buttons.extend(self.material_exchange_page.buttons)



        from mail_ui import MailPage



        self.mail_page = MailPage(self, notebook)



        self.feature_buttons.extend(self.mail_page.buttons)



        self.feature_buttons.extend(self.maze_target_controls.buttons)



        from card_cave_target_ui import CardCaveTargetPage



        self.card_cave_target_page = CardCaveTargetPage(self, self.fun_activity_notebook)



        self.feature_buttons.extend(self.card_cave_target_page.buttons)



        from elite_stone_ui import EliteStonePage
        self.elite_stone_page = EliteStonePage(self, parent=pages['日常副本'])
        self.feature_buttons.extend(self.elite_stone_page.buttons)

        from pet_trial_ui import PetTrialPage
        self.pet_trial_page = PetTrialPage(self, self.backup_function_notebook)
        self.feature_buttons.extend(self.pet_trial_page.buttons)

        from stove_tool_ui import StovePage



        from rebirth_trial_ui import RebirthTrialPage

        self.rebirth_trial_page = RebirthTrialPage(self, parent=pages['活动副本'])
        self.rebirth_trial_page.page.pack_configure(before=self.activity_task_checks)

        self.feature_buttons.extend(self.rebirth_trial_page.buttons)

        self.stove_page = StovePage(self, self.backup_function_notebook)



        self.feature_buttons.extend(self.stove_page.buttons)



        from pet_mating_ui import PetMatingPage



        self.pet_mating_page = PetMatingPage(self, self.backup_function_notebook)



        self.feature_buttons.extend(self.pet_mating_page.buttons)



        from pet_utilities_ui import PetUtilityPage



        self.pet_utility_page = PetUtilityPage(self, self.fun_activity_notebook)



        self.feature_buttons.extend(self.pet_utility_page.buttons)



        from black_market_ui import BlackMarketPage



        self.black_market_page = BlackMarketPage(self, self.fun_activity_notebook)



        self.feature_buttons.extend(self.black_market_page.buttons)



        from fun_batch_ui import FunBatchPage
        self.fun_batch_page = FunBatchPage(self, self.fun_activity_notebook)
        self.feature_buttons.extend(self.fun_batch_page.buttons)

        fun_tabs = {self.fun_activity_notebook.tab(tab, 'text'): tab for tab in self.fun_activity_notebook.tabs()}
        for title in ('黑市', '宠物采集', '妖王帖', '藏宝仙魄商店', '藏宝洞', '幻兽派遣', '幻兽喂养'):
            self.fun_activity_notebook.insert('end', fun_tabs[title])

        backup_tabs = {self.backup_function_notebook.tab(tab, 'text'): tab for tab in self.backup_function_notebook.tabs()}
        for title in ('联盟仓库', '刷去益灵花', '灵宠试炼', '材料置换', '背包/仓库', '抓宠', '宠物上推荐', '炼丹炉'):
            self.backup_function_notebook.insert('end', backup_tabs[title])

        tabs = list(notebook.tabs())



        by_title = {notebook.tab(tab, 'text'): tab for tab in tabs}



        pet_index = tabs.index(by_title['趣味活动'])



        after_pet = tabs[pet_index + 1] if pet_index + 1 < len(tabs) else 'end'



        notebook.insert(after_pet, by_title['新手任务'])



        bottom = ttk.LabelFrame(self.root, text="运行日志")



        bottom.pack(side=tk.BOTTOM, before=self.task_region, fill=tk.BOTH, padx=8, pady=4)



        log_options = ttk.Frame(bottom)



        log_options.pack(fill=tk.X, padx=4, pady=2)



        self.var_save_log = tk.BooleanVar(value=True)



        ttk.Checkbutton(log_options, text="保存运行日志到文件", variable=self.var_save_log).pack(side=tk.LEFT)



        ttk.Label(log_options, text="位置：工具箱目录 / logs", foreground="gray").pack(side=tk.LEFT, padx=8)



        self.lbl_log_file = ttk.Label(log_options, text="", foreground="gray")



        self.lbl_log_file.pack(side=tk.LEFT, padx=4)



        self.txt_log = scrolledtext.ScrolledText(bottom, height=8, wrap=tk.WORD, state=tk.DISABLED)



        self.txt_log.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)



        btns = ttk.Frame(self.root)



        self.memory_controls = btns



        from category_spend_ui import page_category



        for tab in self.main_notebook.tabs():



            title = self.main_notebook.tab(tab, 'text')



            if title not in ('日常任务1', '趣味活动', '备用功能'):



                self.spend_permissions.mount(self.main_notebook.nametowidget(tab), page_category(title))



        for utility_page in self.pet_utility_page.permission_parents.values():
            self.spend_permissions.mount(utility_page, page_category('采集/妖王帖/藏宝'))
        self.spend_permissions.mount(self.pet_capture_page, page_category('抓宠'))
        self.spend_permissions.mount(self.union_warehouse_page, page_category('联盟仓库'))
        self.spend_permissions.mount(self.fairy_dispatch_page, page_category('幻兽'))
        for nested_title, nested_page in (('宠物上推荐', self.pet_mating_page.page), ('藏宝洞', self.card_cave_target_page.page), ('炼丹炉', self.stove_page.page), ('黑市', self.black_market_page.page)):
            self.spend_permissions.mount(nested_page, page_category(nested_title))

        for nested_title, nested_page in (('灵宠试炼', self.pet_trial_page.page), ('材料置换', self.material_exchange_page.page), ('背包/仓库', self.bag_warehouse_page.launcher), ('刷去益灵花', self.old_activity_page.page)):
            self.spend_permissions.mount(nested_page, page_category(nested_title))

        from collapsible_panels import install



        self.collapsible_panels = install(self.main_notebook)



        btns.pack(side=tk.BOTTOM, before=bottom, fill=tk.X, padx=8, pady=4)



        self.btn_run = ttk.Button(btns, text="一键执行全部勾选", command=self._start)



        self.btn_run.pack(side=tk.LEFT, padx=4)
        self.btn_my_daily = ttk.Button(btns, text='我的日常', command=lambda: self.my_daily_window.open())
        self.btn_my_daily.pack(side=tk.LEFT, padx=4)
        self.btn_my_weekly = ttk.Button(btns, text='我的周常', command=lambda: self.my_weekly_window.open())
        self.btn_my_weekly.pack(side=tk.LEFT, padx=4)



        self.btn_stop = ttk.Button(btns, text="停止", command=self._stop, state=tk.DISABLED)



        self.btn_stop.pack(side=tk.LEFT, padx=4)



        ttk.Button(btns, text="清空日志", command=self._clear_log).pack(side=tk.LEFT, padx=4)



        style = ttk.Style()



        style.configure("Red.TCheckbutton", foreground="red")







    def _refresh_account_list(self):



        """刷新已存账号列表"""



        accounts = []



        if os.path.exists(self.accounts_dir):



            for fn in sorted(os.listdir(self.accounts_dir)):



                if fn.endswith(".json"):



                    accounts.append(fn[:-5])



        self.cmb_account.configure(values=accounts)



        if hasattr(self, "teacher_accounts"):



            for combo in self.teacher_accounts.values():



                combo.configure(values=accounts)



        if hasattr(self, "halo_team_combos"):

            for combo in self.halo_team_combos:

                combo.configure(values=accounts)

                if combo.get() not in accounts:

                    combo.set("")

        if hasattr(self, "manhuang_team_combos"):

            for combo in self.manhuang_team_combos:

                combo.configure(values=accounts)

                if combo.get() not in accounts:

                    combo.set("")



        if accounts:



            self.cmb_account.set(accounts[0])



        else:



            self.cmb_account.set("")







    def _delete_saved_account(self):



        if self.running:



            messagebox.showinfo('删除账号','请先等待当前任务结束，再删除已存账号。',parent=self.root);return



        name=self.cmb_account.get().strip()



        if not name:



            messagebox.showinfo('删除账号','请先选择要删除的已存账号。',parent=self.root);return



        if not messagebox.askyesno('删除选中账号','仅删除本地保存的账号“%s”、记住的密码，以及该账号的当前登录缓存。\n其他账号不受影响，游戏账号及存档不会删除。是否继续？'%name,parent=self.root):return



        try:



            from saved_accounts import delete_saved_account



            delete_saved_account(self.accounts_dir,name,PWD_FILE,ACCOUNT_FILE)



        except Exception as exc:



            messagebox.showerror('删除账号失败',str(exc),parent=self.root);return



        self.credentials.pop(name,None)



        self._refresh_account_list()



        for combo in getattr(self,'teacher_accounts',{}).values():



            if combo.get()==name:combo.set('')



        if self.var_login_user.get().strip()==name:



            self.var_login_user.set('');self.var_login_pwd.set('');self.var_login_cookie.set('')



        if not os.path.exists(ACCOUNT_FILE):



            self.lbl_account.configure(text='未加载');self.cmb_slot.configure(values=[str(i) for i in range(8)]);self.cmb_slot.set('0')



        self._append_log('[*] 已删除本地已存账号：'+name)







    def _load_account(self):



        if self.running or self.execution_gate.busy:



            return



        """载入选中的账号"""



        name = self.cmb_account.get().strip()



        if not name:



            return



        path = os.path.join(self.accounts_dir, name + ".json")



        if not os.path.exists(path):



            self._append_log("[!] 账号文件不存在: " + name)



            return



        try:



            with open(path, encoding="utf-8") as f:



                acc = json.load(f)



            with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:



                json.dump(acc, f, ensure_ascii=False, indent=2)



            self._load_account_info()



            # 自动填充账密



            self.var_login_user.set(name)



            if name in self.credentials:



                self.var_login_pwd.set(self.credentials[name])



            self._append_log("[*] 已载入账号: " + name)



        except Exception as e:



            self._append_log("[!] 载入账号失败: " + str(e))







    def _save_account(self, acc):



        """保存账号到accounts目录"""



        name = acc.get("username", "unknown")



        path = os.path.join(self.accounts_dir, name + ".json")



        with open(path, "w", encoding="utf-8") as f:



            json.dump(acc, f, ensure_ascii=False, indent=2)



        self._refresh_account_list()



        self.cmb_account.set(name)







    def _build_teacher_tab(self, parent):



        page = ttk.LabelFrame(parent, text="师徒副本", padding=8)



        page.pack(fill=tk.X, padx=4, pady=6)



        ttk.Label(page, text="哪吒师徒试炼：师尊每周最多 18 次，徒弟每周最多 2 次。两人需使用不同账号，且对应存档已有师徒关系。",



                  wraplength=830).pack(anchor=tk.W, padx=6, pady=6)



        self.teacher_accounts = {}



        self.teacher_slots = {}



        self.teacher_login_fields = {}



        for role, title in (("master", "师尊账号"), ("student", "徒弟账号")):



            frame = ttk.LabelFrame(page, text=title)



            frame.pack(fill=tk.X, padx=5, pady=5)



            row = ttk.Frame(frame)



            row.pack(fill=tk.X, padx=6, pady=3)



            ttk.Label(row, text="已存账号").pack(side=tk.LEFT)



            combo = ttk.Combobox(row, state="readonly", width=19)



            combo.pack(side=tk.LEFT, padx=5)



            self.teacher_accounts[role] = combo



            ttk.Label(row, text="存档槽位").pack(side=tk.LEFT, padx=(10, 4))



            slot = ttk.Combobox(row, values=[str(i) for i in range(8)], state="readonly", width=4)



            slot.set("0")



            slot.pack(side=tk.LEFT)



            self.teacher_slots[role] = slot



            login_row = ttk.Frame(frame)



            login_row.pack(fill=tk.X, padx=6, pady=3)



            user = tk.StringVar()



            pwd = tk.StringVar()



            ttk.Label(login_row, text="4399账号").pack(side=tk.LEFT)



            ttk.Entry(login_row, textvariable=user, width=18).pack(side=tk.LEFT, padx=4)



            ttk.Label(login_row, text="密码").pack(side=tk.LEFT)



            ttk.Entry(login_row, textvariable=pwd, width=18, show="*").pack(side=tk.LEFT, padx=4)



            ttk.Button(login_row, text="账密导入", command=lambda r=role: self._teacher_password_login(r)).pack(side=tk.LEFT, padx=6)



            self.teacher_login_fields[role] = (user, pwd)



            cookie_row = ttk.Frame(frame)



            cookie_row.pack(fill=tk.X, padx=6, pady=(3, 6))



            raw_cookie = tk.StringVar()



            ttk.Label(cookie_row, text="Cookie 整串").pack(side=tk.LEFT)



            ttk.Entry(cookie_row, textvariable=raw_cookie, show="*", width=68).pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)



            ttk.Button(cookie_row, text="Cookie 导入", command=lambda r=role: self._teacher_cookie_login(r)).pack(side=tk.LEFT, padx=6)



            self.teacher_login_fields[role] += (raw_cookie,)



        action = ttk.LabelFrame(page, text="刷券设置")



        action.pack(fill=tk.X, padx=5, pady=8)



        row = ttk.Frame(action)



        row.pack(anchor=tk.W, padx=8, pady=6)



        ttk.Label(row, text="本次次数").pack(side=tk.LEFT, padx=(0, 5))



        self.var_teacher_times = tk.IntVar(value=1)



        ttk.Spinbox(row, from_=1, to=18, textvariable=self.var_teacher_times, width=5).pack(side=tk.LEFT)



        ttk.Label(row, text="建房间隔（秒）").pack(side=tk.LEFT, padx=(16, 5))



        self.var_teacher_interval = tk.StringVar(value="10")



        ttk.Entry(row, textvariable=self.var_teacher_interval, width=7).pack(side=tk.LEFT)



        ttk.Label(action, text="每场核对完成后等待此间隔再建房；按剩余次数封顶，异常停止并输出成功/失败汇总。",



                  foreground="gray", wraplength=800).pack(anchor=tk.W, padx=8, pady=(0, 6))



        buttons = ttk.Frame(action)



        buttons.pack(anchor=tk.W, padx=8, pady=(0, 8))



        self.btn_teacher = ttk.Button(buttons, text="刷师尊券", command=lambda: self._start_teacher_trial("teacher"))



        self.btn_teacher.pack(side=tk.LEFT, padx=(0, 12))



        self.btn_student = ttk.Button(buttons, text="刷徒弟券", command=lambda: self._start_teacher_trial("student"))



        self.btn_student.pack(side=tk.LEFT)







    def _teacher_password_login(self, role):



        user_var, pwd_var, _ = self.teacher_login_fields[role]



        user, pwd = user_var.get().strip(), pwd_var.get().strip()



        if not user or not pwd:



            messagebox.showerror("师徒账号", "请填写账号和密码")



            return



        def work():



            try:



                from ptlogin_login import login_by_password



                result = login_by_password(user, pwd)



                if not result.get("ok"):



                    raise RuntimeError(result.get("error") or "登录失败或需要验证码，请改用 Cookie")



                cookies = result["cookies"]



                acc = {"uid": result["uid"], "username": user, "record_index": 0, "cookies": cookies}



                self.root.after(0, lambda: self._teacher_save_account(role, acc))



            except Exception as exc:



                self.root.after(0, lambda error=str(exc): messagebox.showerror("师徒账号", error))



        threading.Thread(target=work, daemon=True).start()







    def _teacher_cookie_login(self, role):



        raw = self.teacher_login_fields[role][2].get().strip()



        try:



            acc = self._account_from_cookie(raw)



            self._teacher_save_account(role, acc)



        except (ValueError, IndexError) as exc:



            messagebox.showerror("师徒账号", str(exc))







    def _teacher_save_account(self, role, acc):



        self._save_account(acc)



        self.teacher_accounts[role].set(acc["username"])



        self.teacher_slots[role].set(str(acc.get("record_index", 0)))



        self._append_log("[*] 已导入%s账号：%s" % ("师尊" if role == "master" else "徒弟", acc["username"]))







    def _start_teacher_trial(self, role):



        if self.running:



            return



        try:



            master_name = self.teacher_accounts["master"].get().strip()



            student_name = self.teacher_accounts["student"].get().strip()



            if not master_name or not student_name or master_name == student_name:



                raise ValueError("请分别选择两个不同的师尊、徒弟账号")



            times = self.var_teacher_times.get()



            interval = float(self.var_teacher_interval.get().strip())



            if not math.isfinite(interval) or interval < 0:



                raise ValueError("建房间隔须为大于或等于0的有限秒数")



            if not 1 <= times <= (18 if role == "teacher" else 2):



                raise ValueError("师尊本次可选 1～18 次；徒弟本次可选 1～2 次")



            slots = [int(self.teacher_slots[key].get()) for key in ("master", "student")]



            if any(not 0 <= slot <= 7 for slot in slots):



                raise ValueError("请选择两个账号各自的存档槽位")



            paths = [os.path.join(self.accounts_dir, name + ".json") for name in (master_name, student_name)]



            if any(not os.path.isfile(path) for path in paths):



                raise ValueError("账号未导入，请先账密或 Cookie 导入")



        except (ValueError, tk.TclError) as exc:



            messagebox.showerror("师徒副本", str(exc))



            return



        self._append_log("[*] 师徒试炼：刷%s券，师尊 %s 槽%d / 徒弟 %s 槽%d，本次最多 %d 次，建房间隔 %g 秒" %



                         ("师尊" if role == "teacher" else "徒弟", master_name, slots[0], student_name, slots[1], times, interval))



        self._launch([os.path.join(HERE, "teacher_trial.py"),



                      "--master-account", paths[0], "--master-slot", str(slots[0]),



                      "--student-account", paths[1], "--student-slot", str(slots[1]),



                      "--role", role, "--times", str(times), "--interval", str(interval)])







    def _load_account_info(self):



        self.spend_permissions.reset()



        from account_view_cache import invalidate



        invalidate(self)



        for control in getattr(self, 'arena_target_controls', {}).values():



            control.invalidate()



        try:



            with open(ACCOUNT_FILE, encoding="utf-8") as f:



                acc = json.load(f)



            self.lbl_account.configure(



                text="账号: " + str(acc.get("username","?")) + "  uid: " + str(acc.get("uid","?")) + "  存档槽: " + str(acc.get("record_index",0)))



            self.cmb_slot.set(str(acc.get("record_index", 0)))



            self._clear_daily_task_selection()



            self.var_daily_task_quota.set("VIP 与每日任务次数：正在读取当前存档...")



            self.root.after(0, self._sync_elite_tasks)



        except Exception as e:



            self.lbl_account.configure(text="未找到账号文件 (" + str(e) + ")")







    def _show_cookie_help(self):



        messagebox.showinfo('Cookie 获取方式说明',



            '1. 在浏览器打开造梦西游5的4399游戏页面，登录要使用的账号。\n\n'



            '2. 按 F12（或 Ctrl+Shift+I）打开开发者工具，选择“网络 / Network”。\n\n'



            '3. 保持开发者工具打开，刷新游戏页面。优先搜索 user_auth 或 save.api.4399.com；找不到时，检查其他4399登录请求。\n\n'



            '4. 点开请求，在“标头 / Headers → 请求标头 / Request Headers”中找到 Cookie，复制它的完整值。\n'



            '   只复制 name=value; name=value 这一整串，不要带 Cookie: 字样，也不要复制响应中的 Set-Cookie。\n\n'



            '5. Cookie中应包含 Pauth、Uauth、Xauth、USESSIONID 四项。缺少时换一个请求检查，或重新登录后刷新页面。\n\n'



            '6. 粘贴到本工具的“Cookie 整串”框，点击“Cookie登录”。\n\n'



            '请不要用 document.cookie 代替完整请求头，它可能遗漏 HttpOnly 项。Cookie等同登录凭证，请仅粘贴到本地工具箱。',



            parent=self.root)







    @staticmethod



    def _account_from_cookie(raw, slot=0):



        raw = raw.strip()



        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):



            raw = raw[1:-1]



        cookies = {}



        for part in raw.split(';'):



            key, separator, value = part.strip().partition('=')



            if separator and key:



                cookies[key] = value.strip().strip('"')



        for key in ('Pauth', 'Uauth', 'Xauth', 'USESSIONID'):



            if not cookies.get(key): raise ValueError('Cookie 缺少 ' + key)



        fields = cookies['Pauth'].split('|')



        if len(fields) < 2 or not fields[0].isdigit() or not fields[1]:



            raise ValueError('Pauth 中的账号资料无效')



        if any(c in fields[1] for c in '/\\:*?"<>|'):



            raise ValueError('Cookie 中的账号名称无效')



        return {'uid': fields[0], 'username': fields[1], 'record_index': slot, 'cookies': cookies}







    def _do_cookie_login(self):



        if self.running or self.execution_gate.busy:



            return



        if self.btn_cookie_login.instate(['disabled']): return



        if self.running:



            messagebox.showinfo('Cookie登录', '请先停止正在执行的任务，再切换账号。'); return



        try:



            account = self._account_from_cookie(self.var_login_cookie.get(), int(self.cmb_slot.get()))



        except ValueError as exc:



            self.lbl_login_status.configure(text=str(exc), foreground='red'); return



        self.btn_cookie_login.configure(state=tk.DISABLED, text='登录中...')



        self.btn_login.configure(state=tk.DISABLED)



        self.lbl_login_status.configure(text='正在验证Cookie...', foreground='orange')



        threading.Thread(target=self._cookie_login_thread, args=(account,), daemon=True).start()







    def _cookie_login_thread(self, account):



        try:



            from pypomelo.login4399 import fetch_game_token



            fetch_game_token(account['uid'], account['username'], account['cookies'])



            self.root.after(0, lambda: self._finish_cookie_login(account))



        except Exception:



            self.root.after(0, lambda: self._finish_cookie_login(None))







    def _finish_cookie_login(self, account):



        self.btn_cookie_login.configure(state=tk.NORMAL, text='Cookie登录')



        self.btn_login.configure(state=tk.NORMAL)



        if account is None:



            self.lbl_login_status.configure(text='Cookie验证失败', foreground='red')



            self._append_log('[!] Cookie已失效或网络连接失败，请重新复制Cookie后尝试。'); return



        try:



            self._save_account(account)



            with open(ACCOUNT_FILE, 'w', encoding='utf-8') as f:



                json.dump(account, f, ensure_ascii=False, indent=2)



        except OSError:



            self.lbl_login_status.configure(text='账号保存失败', foreground='red'); return



        self.var_login_cookie.set('')



        self.var_login_user.set(account['username']); self.var_login_pwd.set('')



        self.lbl_login_status.configure(text='Cookie登录成功', foreground='green')



        self._append_log('[*] Cookie登录成功，已载入账号：' + account['username'])



        self._load_account_info()







    def _do_login(self):



        if self.running or self.execution_gate.busy:



            return



        user = self.var_login_user.get().strip()



        pwd = self.var_login_pwd.get().strip()



        if not user or not pwd:



            self.lbl_login_status.configure(text="请输入账号密码", foreground="red")



            return



        self.btn_login.configure(state=tk.DISABLED, text="登录中...")



        self.btn_cookie_login.configure(state=tk.DISABLED)



        self.lbl_login_status.configure(text="正在登录...", foreground="orange")



        self._append_log("[*] 开始账密登录: " + user)



        threading.Thread(target=self._login_thread, args=(user, pwd), daemon=True).start()







    def _login_thread(self, user, pwd):



        try:



            sys.path.insert(0, HERE)



            from ptlogin_login import login_by_password

            from login_captcha_ui import ask_captcha



            r = login_by_password(user, pwd, progress=lambda message:

                                  self.root.after(0, self._append_log, '[验证码预检查] ' + message),

                                  captcha_prompt=lambda verification, loader: ask_captcha(self, verification, loader))



            verify = r.get('verification') or {}



            if verify.get('message'):



                self._append_log('[验证码预检查] ' + verify['message'])



            if r.get("ok"):



                uid = r.get("uid", "")



                cookies = r.get("cookies", {})



                acc = {"uid": uid, "username": cookies.get("Puser") or user,



                       "record_index": 0, "cookies": cookies}



                with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:



                    json.dump(acc, f, ensure_ascii=False, indent=2)



                self._save_account(acc)



                if self.var_remember.get():



                    save_credential(user, pwd)



                    self.credentials = load_credentials()



                self._append_log("  uid: " + str(uid))



                self._append_log("  Puser: " + str(cookies.get("Puser")))



                self._append_log("  USESSIONID: " + str(cookies.get("USESSIONID", "")[:8]) + "...")



                self.lbl_login_status.configure(text="登录成功!", foreground="green")



                self._append_log("[*] 登录成功, cookie 已保存到 account.local.json")



                self._load_account_info()



            elif r.get("need_captcha"):



                self.lbl_login_status.configure(text="需要验证码", foreground="orange")



                self._append_log("[!] 需要图片验证码，但未能取得有效图片；请重试账密登录")



            else:



                labels = {'cancelled':'已取消登录', 'verify_error':'验证码查询失败/未知', 'credentials_error':'账号或密码错误',



                          'login_restricted':'其他登录限制', 'network_error':'登录网络错误',



                          'unknown_error':'登录原因未确认'}



                self.lbl_login_status.configure(text=labels.get(r.get('status'), '登录失败'), foreground="red")



                self._append_log("[!] 登录失败: " + str(r.get("error", "未知错误")))



        except Exception as e:



            self.lbl_login_status.configure(text="登录出错", foreground="red")



            self._append_log("[!] 登录出错: " + str(e))



        finally:



            self.btn_login.configure(state=tk.NORMAL, text="账密登录")



            self.btn_cookie_login.configure(state=tk.NORMAL)







    def _refresh_slots(self):



        self._append_log("[*] 正在连接游戏服拉取存档列表...")



        threading.Thread(target=self._refresh_slots_thread, daemon=True).start()







    def _sync_growth_status(self):
        """读取成长挑战状态：积分、至尊等级、十绝阵/BOSS剩余次数、每个任务进度。"""
        if self.running:
            return
        if getattr(self, 'btn_sync_growth', None) is None:
            return
        if self.btn_sync_growth.instate(["disabled"]):
            return
        try:
            with open(ACCOUNT_FILE, encoding="utf-8") as stream:
                account = json.load(stream)
            slot = int(self.cmb_slot.get())
            if not account.get("uid") or not account.get("cookies", {}).get("Uauth"):
                raise ValueError("请先登录并载入账号")
        except (OSError, ValueError) as exc:
            messagebox.showerror("成长挑战", str(exc))
            return
        self.btn_sync_growth.configure(state=tk.DISABLED)
        self.var_growth_summary.set("状态：正在读取积分、次数与任务进度...")
        self._append_log("[*] 正在读取成长挑战状态（存档槽位%d）..." % slot)
        threading.Thread(target=self._sync_growth_status_thread,
                         args=(account, slot, getattr(self, '_account_view_epoch', 0)),
                         daemon=True).start()

    def _sync_growth_status_thread(self, account, slot, view_epoch=None):
        flow = None
        try:
            from pypomelo.login4399 import fetch_game_token
            from pypomelo.flow import GameLoginFlow
            token = fetch_game_token(account["uid"], account["username"], account["cookies"])
            flow = GameLoginFlow(uid=account["uid"], token=token)
            ips = ["82.157.236.253", "101.43.232.80", "101.42.229.203",
                   "101.43.164.20", "82.157.236.99", "43.143.171.37",
                   "82.157.238.37", "43.143.246.102"]
            for ip in ips:
                try:
                    host, port = flow.query_entry(ip, 3010)
                    break
                except Exception:
                    continue
            else:
                raise RuntimeError("连接游戏服失败")
            flow.auth(host, port)
            entered = flow.request("connector.entryHandler.entry",
                                   {"index": slot, "userAgent": flow.user_agent})
            info = entered.get("info")
            if not isinstance(info, dict):
                raise RuntimeError("进入所选存档失败")
            quests = {}
            listed = flow.request("scene.questHandler.getQuestList", {})
            if isinstance(listed, dict) and listed.get("code") == 200:
                for q in (listed.get("quest") or []):
                    try:
                        qid = int(q.get("id"))
                    except (TypeError, ValueError):
                        continue
                    quests[qid] = {"status": int(q.get("status") or 0),
                                   "progress": dict(q.get("progress") or {})}
            gc = info.get("growthChallenge") or {}
            payload = {
                "exp": (None if gc.get("exp") is None else int(gc.get("exp") or 0)),
                "lv": int(gc.get("lv") or 1),
                "rewards": [str(k) for k in (gc.get("rewards") or {})],
                "halo_cnt": int((info.get("halo") or {}).get("haloRewardCnt") or 0),
                "boss_cnt": int((info.get("worldBoss") or {}).get("count") or 0),
                "quests": quests,
            }
            self.root.after(0, lambda data=payload: self._apply_growth_status(data, view_epoch))
        except Exception as exc:
            message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            self.root.after(0, lambda msg=message: self._growth_status_failed(msg))
        finally:
            if flow is not None:
                flow.disconnect()

    def _buy_growth_vip(self):
        """确认锁：必须手动输入口令，才允许花 3600 点券购买成长挑战至尊特权。"""
        from tkinter import simpledialog
        if getattr(self, 'running', False):
            messagebox.showinfo("购买至尊特权", "当前有任务在跑，请等它结束后再买。")
            return
        phrase = "确认购买至尊特权"
        typed = simpledialog.askstring(
            "购买至尊特权（3600点券）",
            "此操作立即扣除 3600 点券且不可撤销。\n若确认，请原样输入：%s" % phrase,
            parent=self.root)
        if not typed:
            return
        if typed.strip() != phrase:
            messagebox.showwarning("购买至尊特权", "口令不一致，已取消（未扣任何点券）。")
            return
        # 实测该路由不在二级密码保护表内（槽6 havePwd=true 也能直接扣费），故不再询问密码；
        # 如需临时带密码，可用环境变量 ZM5_GROWTH_VIP_PASSWORD 启动本程序。
        self.var_growth_vip_unlock.set(True)
        self.var_checks['RUN_GROWTH_BUY_VIP'].set(True)
        try:
            self._start('成长挑战购买特权', group_keys=('RUN_GROWTH_BUY_VIP',))
        finally:
            # 配置已生成、子进程已启动，立刻关锁，防止下一次自动执行重复扣点券
            self.root.after(300, self._reset_growth_vip_lock)

    def _reset_growth_vip_lock(self):
        try:
            self.var_growth_vip_unlock.set(False)
            self.var_checks['RUN_GROWTH_BUY_VIP'].set(False)
        except AttributeError:
            pass

    def _apply_growth_status(self, payload, view_epoch=None):
        from account_view_cache import current
        if not current(view_epoch, self):
            return
        self.btn_sync_growth.configure(state=tk.NORMAL)
        quests = payload.get("quests") or {}
        exp_raw = payload.get("exp")
        exp_known = exp_raw is not None
        exp = int(exp_raw or 0)
        lv = payload.get("lv") or 1
        got = {str(k) for k in (payload.get("rewards") or [])}
        self.var_growth_summary.set(
            "状态：积分 %s · 至尊等级 %s · 十绝阵奖励次数 %s · 世界BOSS次数 %s"
            % (exp if exp_known else "未下发", lv,
               payload.get("halo_cnt") or 0, payload.get("boss_cnt") or 0))
        id_vars_by_switch = getattr(self, 'var_growth_ids', None) or {}
        row_texts = getattr(self, 'growth_row_texts', None) or {}
        cat_status = getattr(self, 'growth_cat_status', None) or {}
        for cat_key, cat_title, switch_key, qids in GROWTH_CATEGORIES:
            id_vars = id_vars_by_switch.get(switch_key) or {}
            texts = row_texts.get(cat_key) or {}
            status_var = cat_status.get(cat_key)
            if cat_key in ('point', 'point_vip'):
                ready = done = missing = 0
                for qid in qids:
                    var = id_vars.get(qid)
                    row = _GROWTH_REWARD_CFG.get(str(qid)) or {}
                    need = int(row.get('growthMoneney') or 0)
                    label = growth_row_label(cat_key, qid)
                    if str(qid) in got:
                        done += 1
                        if var is not None:
                            var.set(False)
                        state = "已领取"
                    elif row.get('levelType') == 2 and lv < 2:
                        missing += 1
                        state = "需至尊特权"
                    elif not exp_known:
                        missing += 1
                        state = "积分未下发（可直接试领）"
                    elif exp < need:
                        missing += 1
                        state = "差%d分" % (need - exp)
                    else:
                        ready += 1
                        state = "可领奖"
                    if qid in texts:
                        texts[qid].set("%s  [%s]" % (label, state))
                if status_var is not None:
                    status_var.set("积分 %s · 已领 %s · 可领 %s · 未达成 %s"
                                   % (exp, done, ready, missing))
                continue
            todo = ready = done = 0
            for qid in qids:
                var = id_vars.get(qid)
                q = quests.get(int(qid)) or {}
                status = int(q.get("status") or 0)
                need = growth_task_need(qid)
                cur = 0
                for value in (q.get("progress") or {}).values():
                    try:
                        cur = max(cur, int(value))
                    except (TypeError, ValueError):
                        continue
                if status == 3:
                    done += 1
                    if var is not None:
                        var.set(False)
                    state = "已领取"
                elif status == 2:
                    ready += 1
                    state = "可领奖"
                elif status == 1:
                    todo += 1
                    state = "进行中 %s/%s" % (cur, need)
                else:
                    todo += 1
                    state = "未接取（0/%s）" % need
                if qid in texts:
                    texts[qid].set("%s  [%s]" % (growth_row_label(cat_key, qid), state))
            if status_var is not None:
                status_var.set("已领 %s · 可领 %s · 待完成 %s" % (done, ready, todo))

    def _growth_status_failed(self, message):
        self.btn_sync_growth.configure(state=tk.NORMAL)
        self.var_growth_summary.set("状态：读取失败（%s）" % message)
        self._append_log("[!] 成长挑战状态读取失败: %s" % message)

    def _sync_elite_tasks(self):



        if self.running:



            return



        if self.btn_sync_elite.instate(["disabled"]):



            return



        try:



            with open(ACCOUNT_FILE, encoding="utf-8") as stream:



                account = json.load(stream)



            slot = int(self.cmb_slot.get())



            if not account.get("uid") or not account.get("cookies", {}).get("Uauth"):



                raise ValueError("请先登录并载入账号")



        except (OSError, ValueError) as exc:



            messagebox.showerror("精英日常任务", str(exc))



            return



        self.btn_sync_elite.configure(state=tk.DISABLED)



        self._append_log("[*] 正在读取存档槽位%d已接取的精英日常任务..." % slot)



        threading.Thread(target=self._sync_elite_tasks_thread,



                         args=(account, slot, getattr(self, '_account_view_epoch', 0)), daemon=True).start()







    def _on_slot_selected(self, _event=None):



        self.spend_permissions.reset()



        from account_view_cache import invalidate



        invalidate(self)



        for control in getattr(self, 'arena_target_controls', {}).values():



            control.invalidate()



        self._clear_daily_task_selection()



        self.var_daily_task_quota.set("VIP 与每日任务次数：正在读取当前存档...")



        self._sync_elite_tasks()







    def _clear_daily_task_selection(self):



        self.daily_task_quota = None



        self.daily_task_statuses = {}



        for var in self.daily_task_vars.values():



            var.set(False)



        self.var_daily_task_selection.set("本次待接：0 项")







    def _on_daily_task_toggle(self, qid):



        if self.daily_task_vars[qid].get():



            pending = [task_id for task_id, var in self.daily_task_vars.items()



                       if var.get() and task_id not in self.daily_task_statuses]



            if self.daily_task_quota is not None and len(pending) > self.daily_task_quota["remaining"]:



                self.daily_task_vars[qid].set(False)



                messagebox.showwarning("精英日常任务", "当前存档今日只剩%d次接取机会。" %



                                       self.daily_task_quota["remaining"])



                return



            mid = int(_ELITE_DAILY_TASKS[qid]["mid"])



            if mid in self.elite_vars:



                self.elite_vars[mid].set(True)



            self.var_checks["RUN_ELITE"].set(True)



        pending_count = sum(var.get() and task_id not in self.daily_task_statuses



                            for task_id, var in self.daily_task_vars.items())



        self.var_daily_task_selection.set("本次待接：%d 项" % pending_count)







    def _sync_elite_tasks_thread(self, account, slot, view_epoch=None):



        flow = None



        try:



            from pypomelo.login4399 import fetch_game_token



            from pypomelo.flow import GameLoginFlow



            token = fetch_game_token(account["uid"], account["username"], account["cookies"])



            flow = GameLoginFlow(uid=account["uid"], token=token)



            ips = ["82.157.236.253", "101.43.232.80", "101.42.229.203",



                   "101.43.164.20", "82.157.236.99", "43.143.171.37",



                   "82.157.238.37", "43.143.246.102"]



            for ip in ips:



                try:



                    host, port = flow.query_entry(ip, 3010)



                    break



                except Exception:



                    continue



            else:



                raise RuntimeError("连接游戏服失败")



            flow.auth(host, port)



            entered = flow.request("connector.entryHandler.entry",



                                   {"index": slot, "userAgent": flow.user_agent})



            if not isinstance(entered.get("info"), dict):



                raise RuntimeError("进入所选存档失败")



            detected_vip=(entered['info'].get('vip') or {}).get('level')
            self.root.after(0,lambda value=detected_vip:self._apply_forest_vip(value,slot,view_epoch))
            listed = flow.request("scene.questHandler.getQuestList", {})



            if listed.get("code") != 200 or not isinstance(listed.get("quest"), list):



                raise RuntimeError("读取任务列表失败")



            from daily_task_quota import quota_from_info



            quota = quota_from_info(entered["info"])



            selected = sorted({int(_ELITE_DAILY_TASKS[q["id"]]["mid"])



                               for q in listed["quest"]



                               if q.get("taskClass") == 2 and q.get("status") == 1



                               and q.get("id") in _ELITE_DAILY_TASKS})



            statuses = {int(q["id"]): int(q["status"]) for q in listed["quest"]



                        if q.get("taskClass") == 2 and q.get("id") in _ELITE_DAILY_TASKS}



            self.root.after(0, lambda: self._apply_elite_task_selection(slot, selected, quota, statuses, view_epoch))



        except Exception as exc:



            message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__



            self.root.after(0, lambda msg=message: self._elite_sync_failed(slot, msg, view_epoch))



        finally:



            if flow is not None:



                flow.disconnect()







    def _apply_forest_vip(self,vip,slot,view_epoch=None):
        from account_view_cache import current
        if not current(view_epoch,self):return
        if int(self.cmb_slot.get())!=slot:return
        self.forest_crystal_controls.set_vip(vip)

    def _apply_elite_task_selection(self, slot, selected, quota, statuses, view_epoch=None):



        from account_view_cache import current



        if not current(view_epoch, self):



            self.btn_sync_elite.configure(state=tk.NORMAL)



            self._sync_elite_tasks()



            return



        self.btn_sync_elite.configure(state=tk.NORMAL)



        if int(self.cmb_slot.get()) != slot:



            self._append_log("[!] 存档槽位已切换，本次精英任务勾选未应用")



            self._sync_elite_tasks()



            return



        self.var_daily_task_quota.set("VIP %d · 每日任务接取机会 %d 次，已用 %d 次，剩余 %d 次" %



                                      (quota["vip"], quota["limit"], quota["used"], quota["remaining"]))



        self.daily_task_quota = quota



        self.daily_task_statuses = statuses



        for qid, status in statuses.items():



            if status == 1 and qid in self.daily_task_vars:



                self.daily_task_vars[qid].set(True)



        self.var_daily_task_selection.set("本次待接：%d 项" % sum(



            var.get() and qid not in statuses for qid, var in self.daily_task_vars.items()))



        for mid in selected:



            if mid in self.elite_vars:



                self.elite_vars[mid].set(True)



        self._append_log("[精英日常任务] 已自动勾选%d关：%s" %



                         (len(selected), ", ".join(str(mid) for mid in selected) or "当前没有已接任务"))







    def _elite_sync_failed(self, slot, message, view_epoch=None):



        from account_view_cache import current



        if not current(view_epoch, self):



            self.btn_sync_elite.configure(state=tk.NORMAL)



            self._sync_elite_tasks()



            return



        self.btn_sync_elite.configure(state=tk.NORMAL)



        if int(self.cmb_slot.get()) != slot:



            self._sync_elite_tasks()



            return



        self.var_daily_task_quota.set("VIP 与每日任务次数：读取失败")



        self._append_log("[!] 读取精英日常任务失败: " + message)







    def _refresh_slots_thread(self):



        try:



            import json as _json



            with open(ACCOUNT_FILE, encoding="utf-8") as f:



                acc = _json.load(f)



            uid = acc.get("uid")



            username = acc.get("username")



            cookies = acc.get("cookies", {})



            if not uid or not cookies.get("Uauth"):



                self._append_log("[!] 请先账密登录")



                return







            from pypomelo.login4399 import fetch_game_token



            from pypomelo.flow import GameLoginFlow



            token = fetch_game_token(uid, username, cookies)



            flow = GameLoginFlow(uid=uid, token=token)







            ips = ["82.157.236.253", "101.43.232.80", "101.42.229.203",



                   "101.43.164.20", "82.157.236.99", "43.143.171.37",



                   "82.157.238.37", "43.143.246.102"]



            host, port = None, None



            for ip in ips:



                try:



                    host, port = flow.query_entry(ip, 3010)



                    break



                except:



                    continue



            if not host:



                self._append_log("[!] 连接游戏服失败")



                return



            flow.auth(host, port)



            r = flow.request("connector.roleHandler.getUserInfo", {})



            u = r.get("user", r) if isinstance(r, dict) else {}



            records = u.get("records") or []



            self._append_log("== 存档列表 (共 %d 槽) ==" % len(records))



            options = []



            for rec in records:



                idx = rec.get("index")



                p1 = rec.get("p1") or {}



                p2 = rec.get("p2") or {}



                p1s = (p1.get("name") + " Lv" + str(p1.get("level"))) if p1 else "-"



                p2s = (p2.get("name") + " Lv" + str(p2.get("level"))) if p2 else "-"



                status = {0: "空", 1: "有", 3: "冻结"}.get(rec.get("status"), "?")



                self._append_log("  槽位%d: %s | %s [%s]" % (idx, p1s, p2s, status))



                options.append(str(idx))



            self.cmb_slot.configure(values=options)



            flow.disconnect()



            self._append_log("[*] 存档列表已加载, 下拉框可选")



        except Exception as e:



            self._append_log("[!] 拉存档失败: " + str(e))







    def _clear_log(self):



        self.txt_log.configure(state=tk.NORMAL)



        self.txt_log.delete("1.0", tk.END)



        self.txt_log.configure(state=tk.DISABLED)







    def _append_log(self, text):



        if self.var_save_log.get():



            try:



                with self.log_file_lock:



                    if self.log_file_path is None:



                        folder = os.path.join(HERE, 'logs')



                        os.makedirs(folder, exist_ok=True)



                        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')



                        self.log_file_path = os.path.join(folder, '运行日志_' + stamp + '.log')



                    with open(self.log_file_path, 'a', encoding='utf-8') as stream:



                        stream.write(text + '\n')



                self.lbl_log_file.configure(text=os.path.basename(self.log_file_path))



            except OSError as exc:



                self.var_save_log.set(False)



                text += '\n[!] 日志文件保存失败，已暂停文件保存：' + str(exc)



        self.txt_log.configure(state=tk.NORMAL)



        self.txt_log.insert(tk.END, text + "\n")



        self.txt_log.see(tk.END)



        self.txt_log.configure(state=tk.DISABLED)







    def _gen_config(self, active_keys=None, forced_keys=None):



        lines = ["# -*- coding: utf-8 -*-", "# GUI auto generated", ""]



        lines.append('WISH_POOL_MODE = '+repr('random' if self.wish_pool_panel.mode.get()=='随机许愿' else 'manual'))
        lines.append('WISH_POOL_PLAN = None')
        lines.append('CELEBRATION_SPIRIT_BACKUP = ' + str(self.var_celebration_spirit_backup.get()))
        lines.append('RUN_CARD_CAVE = False')
        lines.append('PICKUP_SUPPLIES = ' + str(self.var_pickup_supplies.get()))



        for name, key, default, paid, note in TASKS:



            enabled = (key in (forced_keys or set()) or self.var_checks[key].get()) and (active_keys is None or key in active_keys)



            if key=='RUN_WISH_POOL_RANDOM' and self.wish_pool_panel.mode.get()!='随机许愿':
                if enabled:self._append_log('[许愿池] 当前为手动许愿，本次执行项目跳过；手动按钮仍可使用。')
                enabled=False
            enabled = enabled and not disabled_reason(key)



            lines.append(key + " = " + str(enabled))

        # 成长挑战：把各分类折叠列表里勾选的 qId 写进 *_IDS
        for switch_key, id_vars in getattr(self, 'var_growth_ids', {}).items():
            selected = [str(qid) for qid, var in id_vars.items() if var.get()]
            lines.append(switch_key + '_IDS = ' + repr(selected))
        # 永久时装·玉珠商店：勾选的商品与数量写进 RUN_FASHION_SHOP_QTY；未勾选写 {}（不买）
        _fashion_shop_ids = getattr(self, 'var_fashion_shop_ids', None)
        if _fashion_shop_ids is not None:
            _fashion_qty = getattr(self, 'var_fashion_shop_qty', {}) or {}
            _qty_map = {}
            for sid, var in _fashion_shop_ids.items():
                if not var.get():
                    continue
                raw = _fashion_qty.get(sid)
                try:
                    n = int(str(raw.get()).strip()) if raw is not None else 1
                except ValueError:
                    n = 1
                _qty_map[int(sid)] = max(1, n)
            lines.append('RUN_FASHION_SHOP_QTY = ' + repr(_qty_map))

        # 成长挑战至尊特权确认锁：只有手动按钮通过口令后才会写入口令，其余情况一律为空
        _vip_unlock = getattr(self, 'var_growth_vip_unlock', None)
        lines.append('GROWTH_VIP_CONFIRM = ' + repr(
            '确认购买至尊特权' if (_vip_unlock is not None and _vip_unlock.get()) else ''))



        for label, key, lo, hi, default in TIMES_TASKS:



            lines.append(key + " = " + str(self.var_times[key].get()))



        lines.append('PAID_CONFIRM_BITS = ' + repr(''.join(



            '1' if var.get() else '0' for var in self.var_paid_confirm)))



        lines.append('FLUSHOU_MODE = ' + repr(self.var_flushou_mode.get()))



        lines.append('ARENA_MODE = ' + repr(self.var_arena_mode.get()))



        lines.append('PET_ARENA_MODE = ' + repr(self.var_pet_arena_mode.get()))



        for key, var in (



                ('ARENA_TARGET_UID', self.var_arena_target_uid),



                ('ARENA_TARGET_R_NUMBER', self.var_arena_target_r_number),



                ('ARENA_TARGET_ROUNDS', self.var_arena_target_rounds),



                ('PET_ARENA_TARGET_UID', self.var_pet_arena_target_uid),



                ('PET_ARENA_TARGET_R_NUMBER', self.var_pet_arena_target_r_number),



                ('PET_ARENA_TARGET_ROUNDS', self.var_pet_arena_target_rounds),



                ('ARENA_TOP_N', self.var_arena_top_n),



                ('PET_ARENA_TOP_N', self.var_pet_arena_top_n),



                ('ARENA_TARGET_INPUT', self.var_arena_target_input),



                ('ARENA_TARGET_RID', self.var_arena_target_rid),



                ('PET_ARENA_TARGET_INPUT', self.var_pet_arena_target_input),



                ('PET_ARENA_TARGET_RID', self.var_pet_arena_target_rid),



                ('ARENA_BATTLE_WAIT', self.var_arena_battle_wait),



                ('ARENA_ROUND_WAIT', self.var_arena_round_wait),



                ('PET_ARENA_BATTLE_WAIT', self.var_pet_arena_battle_wait),



                ('PET_ARENA_ROUND_WAIT', self.var_pet_arena_round_wait)):



            lines.append(key + ' = ' + repr(var.get()))







        lines.append('FOREST_AUTO_CRYSTAL = '+str(self.forest_crystal_controls.is_low_vip() and self.var_forest_auto_crystal.get()))
        lines.append('FOREST_MODE = ' + repr(self.var_forest_mode.get()))



        if (self.var_checks['RUN_FREE_MAZE'].get() or 'RUN_FREE_MAZE' in (forced_keys or set())) and (active_keys is None or 'RUN_FREE_MAZE' in active_keys):



            maze_mode, maze_code, maze_fingerprint = self.maze_target_controls.config()



        else:



            maze_mode, maze_code, maze_fingerprint = self.var_free_maze_mode.get(), '', ''



        lines.append('FREE_MAZE_WAIT = '+repr(self.maze_target_controls.wait_seconds()))
        lines.append('FREE_MAZE_MODE = ' + repr(maze_mode))



        lines.append('FREE_MAZE_TARGET_CODE = ' + repr(maze_code))



        lines.append('FREE_MAZE_FINGERPRINT = ' + repr(maze_fingerprint))



        cave = self.card_cave_target_page



        mode = cave.mode_key()



        fingerprint = ''



        if mode == 'specified' and (('RUN_CARD_CAVE' in self.var_checks and self.var_checks['RUN_CARD_CAVE'].get()) or 'RUN_CARD_CAVE' in (forced_keys or set())) and (active_keys is None or 'RUN_CARD_CAVE' in active_keys):



            account = json.loads(open(os.path.join(HERE, 'account.local.json'), encoding='utf-8-sig').read())



            data = cave.data



            if not data or data.get('mode') != mode or data.get('account') != str(account.get('username','')) or data.get('slot') != int(self.cmb_slot.get()) or data.get('code') != cave.code.get().strip():



                raise ValueError('指定藏宝洞请先在藏宝洞页查询并确认当前账号、槽位与挑战码')



            fingerprint = data['fingerprint']



        wait = float(cave.wait.get())



        if not 0 <= wait <= 3600:



            raise ValueError('藏宝洞等待时间须为0～3600秒')



        lines.append('CARD_CAVE_MODE = ' + repr(mode))



        lines.append('CARD_CAVE_CODE = ' + repr(cave.code.get().strip()))



        lines.append('CARD_CAVE_FINGERPRINT = ' + repr(fingerprint))



        lines.append('CARD_CAVE_WAIT = ' + repr(wait))



        lines.append("RECORD_INDEX = " + str(int(self.cmb_slot.get())))



        lines.append("MAIN_CUSTOM_MID = 0")



        lines.append("MAIN_CUSTOM_TIMES = 0")



        lines.append("STAGE_OVERRIDE = {")



        for label, key, items in STAGE_LABELS:



            v = self.var_stage[key].get().strip()



            if v:



                try:



                    mid = int(v.split()[0])



                    lines.append('    "' + key + '": ' + str(mid) + ",")



                except:



                    lines.append('    "' + key + '": None,')



            else:



                lines.append('    "' + key + '": None,')



        lines.append("}")



        elite_mids = sorted(mid for mid, var in self.elite_vars.items() if var.get())



        lines.append("ELITE_MULTI_MIDS = " + str(elite_mids))



        daily_task_ids = sorted(qid for qid, var in self.daily_task_vars.items() if var.get())



        lines.append("DAILY_TASK_SELECTED_IDS = " + str(daily_task_ids))



        lines.append("ELITE_CLAIM_FREE_CARD = " + str(self.var_elite_card.get()))



        lines.append("ELITE_SELL_BOSS = " + str(self.var_elite_sell_boss.get()))



        lines.append("ELITE_SELL_SMALL = " + str(self.var_elite_sell_small.get()))



        lines.append("ELITE_SELL_MEDICINE = " + str(self.var_elite_sell_medicine.get()))



        lines.append("NIGHTMARE_MID = " + self.var_nightmare_stage.get().split()[0])



        lines.append("NIGHTMARE_CLAIM_FREE_CARD = " + str(self.var_nightmare_card.get()))



        card_strategy = self.nightmare_card_strategies[self.var_nightmare_card_strategy.get()]



        lines.append("NIGHTMARE_CARD_STRATEGY = " + repr(card_strategy))



        lines.append("NIGHTMARE_CARD_PAID = " + str(card_strategy != 'free'))



        lines.append("FIGHT_DELAY = " + str(self.var_fight_delay.get()))



        # 蛮荒关卡: 留空=0(自动最高)



        _mhs = self.var_mh_stage.get().strip()



        if _mhs:



            try:



                _mh_mid = int(_mhs.split()[0])



            except:



                _mh_mid = 0



        else:



            _mh_mid = 0



        lines.append('MANHUANG_MID = ' + str(_mh_mid))



        # 蛮荒副本模式: 多人版=multi, 单人版=solo



        _mh = self.var_mh_mode.get()

        if '多人组队' in _mh:
            _mh_mode = 'team3' if '3号' in _mh else 'team2'
        else:
            _mh_mode = 'solo' if '单人' in _mh else 'multi'

        lines.append('MANHUANG_MODE = "' + _mh_mode + '"')



        _halo_mode = self.var_halo_score.get()

        lines.append('HALO_TARGET_SCORE = ' + ('1000' if '1000' in _halo_mode else '3000'))

        _halo_team = ('three_main' if '仅主号' in _halo_mode
                      else ('three' if '三人' in _halo_mode else 'single'))

        lines.append('HALO_TEAM_MODE = "' + _halo_team + '"')



        try:



            from climb_high import parse_score



            climb_score = parse_score(self.var_climb_score.get())



        except ValueError:



            climb_score = 100



        lines.append('CLIMB_HIGH_SCORE = ' + str(climb_score))



        _tower_range = self.var_tower_range.get()



        _tower_layer = (int(_tower_range.split('-', 1)[0]) - 1) // 10 + 1 if '-' in _tower_range else 0



        lines.append('DEMON_TOWER_TARGET_LAYER = ' + str(_tower_layer))



        fairy_positions = [0, 1, 2] if self.var_fairy_daily_scope.get() == '全部可派档位' else [int(self.var_fairy_daily_pos.get()) - 1]
        lines.append('FAIRY_DAILY_POSITIONS = ' + repr(fairy_positions))
        lines.append('FAIRY_DAILY_PREFERENCES = ' + repr(self.fairy_preferences.value()))

        cfg_path = os.path.join(HERE, "gui_config.py")



        with open(cfg_path, "w", encoding="utf-8") as f:



            f.write("\n".join(lines))



        return cfg_path







    def _start_celebration_rewards(self, kind):



        if self.running or not self._save_selected_slot():



            return



        self._launch([os.path.join(HERE, 'celebration_rewards.py'), '--kind', kind])







    def _start_single_task(self, page_title):



        selected, choices = self.single_task_choices[page_title]



        self._start(page_title, task_key=choices[selected.get()])







    def _start_landing(self, key):
        """登录有礼按钮：临时勾选对应开关让 _start 生成配置，返回后恢复 False。"""
        var = self.var_checks.get(key)
        if var is None:
            return
        old = var.get()
        var.set(True)
        try:
            self._start('登录有礼', group_keys=(key,))
        finally:
            var.set(old)

    def _start_novice(self, key):
        """新手有礼按钮：临时勾选对应开关让 _start 生成配置，返回后恢复 False。"""
        var = self.var_checks.get(key)
        if var is None:
            return
        old = var.get()
        var.set(True)
        try:
            self._start('新手有礼', group_keys=(key,))
        finally:
            var.set(old)

    def _start(self, page_title=None, task_key=None, task_keys=None, free_only=False, group_keys=None):




        if self.running:



            return



        active_keys = None



        forced_keys = set()



        if task_keys is not None:



            allowed = set(self.my_daily_window.full_catalog)



            if not task_keys or not set(task_keys) <= allowed:



                messagebox.showerror('我的日常', '包含不存在或点券任务。')



                return



            active_keys = {key for key in task_keys if not disabled_reason(key)}



            if not active_keys:



                messagebox.showinfo('我的日常', '所选任务当前均未开放。')



                return



            forced_keys = set(active_keys)



            if 'RUN_ELITE' in active_keys:



                active_keys.add('RUN_ACCEPT_DAILY_TASKS'); forced_keys.add('RUN_ACCEPT_DAILY_TASKS')



            free_only = True



        elif task_key is not None:



            if task_key not in TASK_PAGES.get(page_title, ()):



                return



            unavailable = disabled_reason(task_key)



            if unavailable:



                messagebox.showinfo(page_title, unavailable)



                return



            active_keys = {task_key}



            forced_keys = {task_key}



            dependencies = {"ARENA_PAID_EXTRA": "RUN_ARENA", "PET_ARENA_PAID_EXTRA": "RUN_PET_ARENA"}



            if task_key in dependencies:



                active_keys.add(dependencies[task_key]); forced_keys.add(dependencies[task_key])



            if task_key == "RUN_ELITE":



                active_keys.add("RUN_ACCEPT_DAILY_TASKS")



        elif page_title is not None:



            page_key_set = set(group_keys if group_keys is not None else TASK_PAGES[page_title])
            active_keys = set(page_key_set)



            if page_title == "日常副本":



                active_keys.add("RUN_ACCEPT_DAILY_TASKS")



            if not any(self.var_checks[key].get() for key in page_key_set):



                messagebox.showinfo(page_title, "本页尚未勾选执行项目。")



                return



        selected_tasks = [qid for qid, var in self.daily_task_vars.items() if var.get()]



        if (active_keys is None or "RUN_ELITE" in active_keys) and (self.var_checks["RUN_ELITE"].get() or "RUN_ELITE" in forced_keys) and self.var_checks["RUN_ACCEPT_DAILY_TASKS"].get() and selected_tasks:



            if self.daily_task_quota is None:



                messagebox.showerror("精英日常任务", "请先读取当前存档的 VIP 与每日任务剩余次数。")



                return



            new_tasks = [qid for qid in selected_tasks if qid not in self.daily_task_statuses]



            if len(new_tasks) > self.daily_task_quota["remaining"]:



                messagebox.showerror("精英日常任务", "本次新选%d项，但今日只剩%d次接取机会。" %



                                     (len(new_tasks), self.daily_task_quota["remaining"]))



                return



        paid_on = [name for name, key, _, paid, _ in TASKS



                   if paid and (self.var_checks[key].get() or key in forced_keys) and (active_keys is None or key in active_keys)]



        if paid_on:



            try:



                self.spend_permissions.require('daily')



            except ValueError as exc:



                messagebox.showerror('日常点券权限', str(exc))



                return



            if not messagebox.askyesno("警告", "以下任务可能消耗点券:\n  " + ", ".join(paid_on) + "\n\n确定要继续吗？"):



                return



        if (active_keys is None or "RUN_CLIMB_HIGH" in active_keys) and (self.var_checks["RUN_CLIMB_HIGH"].get() or "RUN_CLIMB_HIGH" in forced_keys):



            try:



                from climb_high import parse_score



                parse_score(self.var_climb_score.get())



            except ValueError as exc:



                messagebox.showerror("重阳采菊", str(exc))



                return



        target_confirmations = {}



        try:



            for handler, key, mode in (



                    ('arena', 'RUN_ARENA', self.var_arena_mode),



                    ('petArena', 'RUN_PET_ARENA', self.var_pet_arena_mode)):



                enabled = (self.var_checks[key].get() or key in forced_keys) and (active_keys is None or key in active_keys)



                if enabled:



                    from arena_targets import wait_seconds



                    prefix = 'var_arena' if handler == 'arena' else 'var_pet_arena'



                    wait_seconds(getattr(self, prefix + '_battle_wait').get())



                    wait_seconds(getattr(self, prefix + '_round_wait').get())



                if enabled and mode.get() == 'rank_random':



                    from arena_targets import top_n_value



                    top_n_value(self.var_arena_top_n.get() if handler == 'arena' else self.var_pet_arena_top_n.get())



                if enabled and mode.get() in ('specified', 'borrowed'):



                    target_confirmations[handler] = self.arena_target_controls[handler].require()



        except (OSError, ValueError) as exc:



            for control in self.arena_target_controls.values():



                control.invalidate()



            messagebox.showerror('竞技场/斗宠设置', str(exc) + '\n请修正设置；指定对手和借用列表须先查询并确认。')



            return



        if self.running or self.execution_gate.busy:



            return



        fun_plan=None
        if task_keys is not None:
            try:
                from my_daily_catalog import build_plan
                with open(ACCOUNT_FILE,encoding='utf-8-sig') as stream:fun_account=json.load(stream)
                fun_plan=build_plan(self,set(task_keys),fun_account,int(self.cmb_slot.get()))
            except (ValueError,OSError,KeyError) as exc:
                messagebox.showerror('我的日常设置',str(exc));return

        try:



            cfg = self._gen_config(active_keys, forced_keys)



        except (ValueError, OSError) as exc:



            messagebox.showerror('执行设置', str(exc))



            return



        label = next((name for name, key, *_ in TASKS if key == task_key), page_title or "全部勾选")



        self._append_log("[*] %s配置已生成: %s" % (label, cfg))



        if not self._save_selected_slot():



            return



        elite_password = self.var_elite_sell_password.get()



        self.var_elite_sell_password.set('')



        forest_crystal_password = self.var_forest_crystal_password.get()
        self.var_forest_crystal_password.set('')
        celebration_password = self.var_celebration_password.get()
        self.var_celebration_password.set('')
        fashion_shop_password = (self.var_fashion_shop_password.get()
                                 if hasattr(self, 'var_fashion_shop_password') else '')
        if hasattr(self, 'var_fashion_shop_password'):
            self.var_fashion_shop_password.set('')
        white_dragon_password = (self.var_white_dragon_password.get()
                                 if hasattr(self, 'var_white_dragon_password') else '')
        if hasattr(self, 'var_white_dragon_password'):
            self.var_white_dragon_password.set('')
        worker_args = [os.path.join(HERE, 'daily_auto.py')]



        if free_only:



            worker_args = [os.path.join(HERE, 'my_daily_runner.py'), '--tasks', json.dumps(sorted(task_keys), ensure_ascii=False)]
            if fun_plan:worker_args+=['--fun-plan',json.dumps(fun_plan,ensure_ascii=False)]



        self._launch(worker_args, extra_env={'ZM5_FOREST_CRYSTAL_PASSWORD': forest_crystal_password, 'ZM5_ELITE_SELL_PASSWORD': elite_password, 'ZM5_CELEBRATION_PASSWORD': celebration_password, 'ZM5_FASHION_SHOP_PASSWORD': fashion_shop_password, 'ZM5_WHITE_DRAGON_PASSWORD': white_dragon_password,



                        'ZM5_ARENA_TARGET_CONFIRMATIONS': json.dumps(target_confirmations, ensure_ascii=False)})







    def launch_arena_registration(self, handler):


        if getattr(self, 'running', False) or not self._save_selected_slot():
            return


        try:


            with open(ACCOUNT_FILE, encoding='utf-8-sig') as f:
                acc = json.load(f)
            self._launch([os.path.join(HERE, 'arena_registration.py'), '--handler', handler,
                          '--expected-uid', str(acc['uid']),
                          '--expected-slot', str(int(self.cmb_slot.get()))])


        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror('未执行', str(exc), parent=self.root)


    def _sync_mh_team(self):
        mode = self.var_mh_mode.get()
        team = '多人组队' in mode
        size = 3 if '3号' in mode else 2
        state = 'readonly' if team else 'disabled'
        for index, combo in enumerate(self.manhuang_team_combos):
            combo.configure(state=state if (team and index < size) else 'disabled')
        for index, combo in enumerate(getattr(self, 'manhuang_slot_combos', [])):
            combo.configure(state=state if (team and index < size) else 'disabled')
        for index, btn in enumerate(getattr(self, 'manhuang_claim_buttons', [])):
            btn.state(['!disabled'] if (team and index < size) else ['disabled'])
        self.btn_manhuang_team.configure(state=tk.NORMAL if team else tk.DISABLED)


    def launch_manhuang_team(self):
        if getattr(self, 'running', False):
            return
        mode = self.var_mh_mode.get()
        if '多人组队' not in mode:
            return
        size = 3 if '3号' in mode else 2
        names = [combo.get().strip() for combo in self.manhuang_team_combos[:size]]
        if any(not name for name in names) or len(set(names)) != size:
            messagebox.showerror('未执行', '多人组队需要选择 %d 个不同的账号。' % size, parent=self.root)
            return
        for name in names:
            if not os.path.exists(os.path.join(self.accounts_dir, name + '.json')):
                messagebox.showerror('未执行', '找不到账号文件: %s' % name, parent=self.root)
                return
        slots = [combo.get().strip() or '0' for combo in self.manhuang_slot_combos[:size]]
        if any(not slot.isdigit() or not 0 <= int(slot) <= 7 for slot in slots):
            messagebox.showerror('未执行', '组队存档槽位须为 0～7。', parent=self.root)
            return
        claims = ['1' if var.get() else '0' for var in self.manhuang_claim_vars[:size]]
        try:
            with open(MANHUANG_TEAM_CONFIG, 'w', encoding='utf-8') as _stream:
                json.dump({'accounts': [combo.get().strip() for combo in self.manhuang_team_combos],
                           'slots': [combo.get().strip() or '0' for combo in self.manhuang_slot_combos],
                           'claim': [bool(var.get()) for var in self.manhuang_claim_vars]},
                          _stream, ensure_ascii=False, indent=2)
        except OSError:
            pass
        self._launch([os.path.join(HERE, 'manhuang_team.py'),
                      '--accounts', ','.join(names),
                      '--slots', ','.join(slots),
                      '--claim', ','.join(claims)])


    def _sync_halo_mode(self):
        three = '三人' in self.var_halo_score.get()
        state = 'readonly' if three else 'disabled'
        for combo in self.halo_team_combos:
            combo.configure(state=state)
        for combo in getattr(self, 'halo_slot_combos', []):
            combo.configure(state=state)
        for btn in getattr(self, 'halo_claim_buttons', []):
            btn.state(['!disabled'] if three else ['disabled'])
        self.btn_halo_team.configure(state=tk.NORMAL if three else tk.DISABLED)


    def launch_halo_team(self):
        if getattr(self, 'running', False):
            return
        if '三人' not in self.var_halo_score.get():
            return
        names = [combo.get().strip() for combo in self.halo_team_combos]
        if any(not name for name in names) or len(set(names)) != 3:
            messagebox.showerror('未执行', '三账号模式需要选择三个不同的账号。', parent=self.root)
            return
        for name in names:
            if not os.path.exists(os.path.join(self.accounts_dir, name + '.json')):
                messagebox.showerror('未执行', '找不到账号文件：%s.json' % name, parent=self.root)
                return
        slots = [combo.get().strip() or '0' for combo in self.halo_slot_combos]
        if any(not slot.isdigit() or not 0 <= int(slot) <= 7 for slot in slots):
            messagebox.showerror('未执行', '组队存档槽位须为 0～7。', parent=self.root)
            return
        claims = ['1' if var.get() else '0' for var in self.halo_claim_vars]
        try:
            with open(HALO_TEAM_CONFIG, 'w', encoding='utf-8') as stream:
                json.dump({'accounts': names, 'slots': slots,
                           'claim': [bool(var.get()) for var in self.halo_claim_vars]},
                          stream, ensure_ascii=False, indent=2)
        except OSError as exc:
            messagebox.showerror('未执行', '保存组队账号失败：%s' % exc, parent=self.root)
            return
        command = [os.path.join(HERE, 'halo_team.py'), '--accounts', ','.join(names),
                   '--slots', ','.join(slots), '--claim', ','.join(claims)]
        if '仅主号' in self.var_halo_score.get():
            command.append('--claim-main-only')
        self._launch(command)


    def _save_selected_slot(self):



        try:



            with open(ACCOUNT_FILE, encoding="utf-8") as f:



                acc = json.load(f)



            if int(acc.get('record_index', 0)) != int(self.cmb_slot.get()):



                from account_view_cache import invalidate



                invalidate(self)



            acc["record_index"] = int(self.cmb_slot.get())



            with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:



                json.dump(acc, f, ensure_ascii=False, indent=2)



            return True



        except Exception as e:



            self._append_log("[!] 更新存档槽失败: " + str(e))



            return False







    def _start_farm(self):



        if self.running:



            return



        selected = self.var_farm_stage.get().strip()



        if not selected:



            messagebox.showerror("一键刷图", "请先选择主线关卡。")



            return



        try:



            mid = int(selected.split()[0])



            times = self.var_farm_times.get()



            delays = (self.var_farm_base_delay.get(), self.var_farm_boss_delay.get(),



                      self.var_farm_round_delay.get())



            if not 1 <= times <= 20 or min(delays) < 0:



                raise ValueError("次数须为1–20，等待时间不能为负数")



        except (ValueError, tk.TclError) as exc:



            messagebox.showerror("一键刷图", "设置有误：" + str(exc))



            return



        loot = self.var_farm_loot.get()



        if loot not in ("small", "currency", "spiritPet"):



            key = "hidden" if loot == "hidden" else "normal"



            if key not in _MAIN_BOSS_ROUTES.get(str(mid), {}):



                messagebox.showerror("一键刷图", "所选关卡没有对应的%s房间。" %



                                     ("隐藏 Boss" if key == "hidden" else "普通 Boss"))



                return



        if not self._save_selected_slot():



            return



        args = [os.path.join(HERE, "main_farm.py"),



                "--mid", str(mid), "--times", str(times),



                "--progress", self.var_farm_result.get(),



                "--loot", loot,



                "--base-seconds", str(delays[0]),



                "--boss-seconds", str(delays[1]),



                "--round-seconds", str(delays[2])]



        self._launch(args)







    def _start_world_boss(self):



        if self.running:



            return



        try:



            boss_id = int(self.var_world_boss.get().split()[0])



            dps = float(self.var_world_dps.get())



            target = float(self.var_world_target.get())



            if not math.isfinite(dps) or dps <= 0 or not math.isfinite(target) or not 0 < target <= 100:



                raise ValueError("期望伤害须大于0，目标占比须在0～100%之间")



        except (IndexError, ValueError):



            messagebox.showerror("世界 Boss", "请选择目标 Boss，并填写有效的每秒期望伤害和目标占比。")



            return



        if not self._save_selected_slot():



            return



        args = [os.path.join(HERE, "world_boss.py"), "--boss-id", str(boss_id),



                "--expected-dps", str(dps), "--target-percent", str(target)]



        if not self.var_world_attack_target.get():



            args.append("--no-target")



        if self.var_world_idle.get():



            args.append("--idle-mode")



        self._launch(args)







    def _start_union_boss(self):



        if self.running:



            return



        try:



            raw_dps = self.var_union_dps.get().strip()



            dps = float(raw_dps) if raw_dps else None



            target = float(self.var_union_target.get())



            if (dps is not None and (not math.isfinite(dps) or dps <= 0)) or not math.isfinite(target) or not 0 < target <= 100:



                raise ValueError("期望伤害须大于0，目标占比须在0～100%之间")



        except ValueError:



            messagebox.showerror("联盟 Boss", "请填写有效的每秒期望伤害和目标占比；伤害留空则自动计算。")



            return



        if not self._save_selected_slot():



            return



        args = [os.path.join(HERE, "union_boss.py"), "--level", "0",



                "--target-percent", str(target)]



        if dps is not None:



            args.extend(["--expected-dps", str(dps)])



        if not self.var_union_attack_target.get():



            args.append("--no-target")



        if self.var_union_idle.get():



            args.append("--idle-mode")



        self._launch(args)







    def _start_tongtian_action(self, action):



        if self.running:



            return



        automatic=action in ('status','refresh','upgrade','escort')
        slot_action='escort' if automatic else action
        try:
            slot=None
            if not automatic:
                if not self.var_ttr_slots[slot_action].get().strip():raise ValueError('请先选择本次操作的存档槽位')
                slot=int(self.var_ttr_slots[slot_action].get())
                if not 0<=slot<=7:raise ValueError('存档须为0～7')
            minutes = self.var_rob_wait.get() if action == "rob" else 10



            if action == "rob" and not 1 <= minutes <= 60:



                raise ValueError("等待时间须为1～60分钟")



        except (ValueError, tk.TclError) as exc:



            messagebox.showerror("通天河", str(exc))



            return



        if not os.path.exists(ACCOUNT_FILE) and not os.path.exists(os.path.join(HERE, "account.enc")):



            messagebox.showerror("通天河", "请先载入账号")



            return



        action_names = {"status": "查看船档", "refresh": "免费刷新一次", "upgrade": "免费刷到海舰",



                        "escort": "发船", "reward": "领奖", "rob": "抢船"}



        self._append_log('[*] 通天河%s：%s'%(action_names[action],'自动选择最低等级≥40存档' if automatic else '使用存档槽%s'%slot))



        if action == "rob":



            self._append_log("[*] 抢船模式：%s" % ("只抢海舰" if self.var_ttr_target_mode.get() == "sea_only"



                                            else "海舰优先；没有可抢海舰时抢其他船"))



        args=[os.path.join(HERE,'tongtian_rob.py'),'--action',action,'--max-wait',str(minutes*60)]
        if slot is not None:args.extend(['--slot',str(slot)])

        if action=='escort':
            strategy=next((k for k,v in self.ttr_escort_strategies.items() if v==self.var_ttr_escort_strategy.get()),None)
            if strategy is None:
                messagebox.showerror('通天河','请选择发船策略');return
            args.extend(['--escort-strategy',strategy])
        if action=='rob' and not self.var_ttr_full_reward.get():args.append('--allow-reduced-reward')
        if action == "rob" and self.var_ttr_target_mode.get() == "sea_only":



            args.append("--sea-only")



        if action == "rob" and self.var_ttr_qi_only.get():



            selected_kind = self.var_ttr_qi_kind.get()



            kinds = {'both':[('heaven','天清气'),('earth','地浊气')],



                     'heaven':[('heaven','天清气')],



                     'earth':[('earth','地浊气')]}.get(selected_kind)



            if kinds is None:



                messagebox.showerror('通天河', '请选择天清气＋地浊气、天清气或地浊气')



                return



            args.append("--qi-only")



            for kind,label in kinds:args.extend(['--qi-kind',kind])



            self._append_log("[*] 货物筛选：仅%s海舰" % '／'.join(label for kind,label in kinds))



        if action == 'rob':



            try:



                battle_wait = int(self.var_ttr_battle_wait.get().strip())



                if not 1 <= battle_wait <= 30:



                    raise ValueError()



            except (ValueError, tk.TclError):



                messagebox.showerror('通天河', '结算等待时间须为1至30秒整数')



                return



            args.extend(['--battle-wait', str(battle_wait)])



            self._append_log('[*] 入场后结算等待：%s秒' % battle_wait)



            if not self.var_ttr_chain_twice.get():



                args.append('--no-chain')



            self._append_log('[*] 原船连抢两次：%s' % ('开启' if self.var_ttr_chain_twice.get() else '关闭'))



        self._launch(args)







    def _start_timeboat(self, action):



        if self.running:



            return



        try:



            if not self.var_timeboat_slot.get().strip():



                raise ValueError("请先选择兑换存档")



            slot = int(self.var_timeboat_slot.get())



            if not 0 <= slot <= 7:



                raise ValueError("存档须为0～7")



            args = [os.path.join(HERE, "time_energy.py"), "--slot", str(slot)]



            if action == "status":



                args.append("--status")



            else:



                choice = self.var_timeboat_choice.get().strip()



                if not choice:



                    raise ValueError("请先选择兑换项目")



                energy_id = int(choice.split()[0])



                times = self.var_timeboat_times.get()



                if not 1 <= times <= 15:



                    raise ValueError("兑换次数须为1～15")



                args.extend(["--energy-id", str(energy_id), "--times", str(times)])
                if action == "exchange_run":
                    self._gen_config()
                    args.append("--run-after")
                    if energy_id == 6:
                        with open(ACCOUNT_FILE, encoding='utf-8-sig') as stream:
                            account = json.load(stream)
                        plan = self.fun_batch_page.build(['藏宝洞免费挑战'], account, slot)
                        args.extend(['--cave-plan', json.dumps(plan, ensure_ascii=False)])




        except (ValueError, tk.TclError) as exc:



            messagebox.showerror("时光之舟", str(exc))



            return



        if not os.path.exists(ACCOUNT_FILE) and not os.path.exists(os.path.join(HERE, "account.enc")):



            messagebox.showerror("时光之舟", "请先载入账号")



            return



        self._append_log("[*] 时光之舟%s使用存档槽 %d" %



                         ("查看状态" if action == "status" else "兑换", slot))



        self._launch(args)







    def _start_pet_brawl(self):



        if self.running:



            return



        try:



            matches = self.var_pet_brawl_matches.get()



            if matches < 1:



                raise ValueError("本次匹配场数须为正整数")



        except (ValueError, tk.TclError) as exc:



            messagebox.showerror("灵宠乱斗", str(exc))



            return



        if not self._save_selected_slot():



            return



        args = [os.path.join(HERE, "pet_brawl.py"), "--matches", str(matches)]



        self._launch(args)







    def _start_pet_brawl_manual(self):



        if self.running:



            return



        if not self._save_selected_slot():



            return



        self._launch([os.path.join(HERE, "pet_brawl_manual.py")])







    def _start_pvp(self):



        if self.running:



            return



        try:



            matches = self.var_pvp_matches.get()



            if matches < 1:



                raise ValueError("本次匹配场数须为正整数")



        except (ValueError, tk.TclError) as exc:



            messagebox.showerror("斗神大会", str(exc))



            return



        if not self._save_selected_slot():



            return



        self._launch([os.path.join(HERE, "pvp_idle.py"), "--matches", str(matches)])







    def _refresh_wish_choices(self):



        day = _national_day_today()



        choices = _NATIONAL_DAY_CHOICES.get(day)



        if getattr(self, "wish_display_day", None) != day:



            self.var_wish_choice.set(0)



        self.wish_display_day = day



        if choices:



            self.var_wish_day.set("%s月%s日：当天免费选1项；其余选项及补签需要付费，本工具不执行。"



                                  % (int(day[4:6]), int(day[6:8])))



        else:



            self.var_wish_day.set("2026年10月1日至7日开放当天免费签到；今天不在活动日期内。")



        for index, button in enumerate(self.wish_choice_buttons):



            if choices:



                option = choices[index]



                button.configure(text="%d. %s：%s" %



                                 (index + 1, option["title"], option["items"]), state=tk.NORMAL)



            else:



                button.configure(text="%d. 今日未开放" % (index + 1), state=tk.DISABLED)



        self.btn_wish_sign.configure(state=tk.NORMAL if choices and not self.running else tk.DISABLED)







    def _start_national_day_wish(self, status_only):



        if self.running:



            return



        self._refresh_wish_choices()



        if self.wish_display_day not in _NATIONAL_DAY_CHOICES:



            messagebox.showinfo("十一许愿", "今天不在免费签到日期内。")



            return



        if not status_only and self.var_wish_choice.get() not in (1, 2, 3):



            messagebox.showinfo("十一许愿", "请先在今天的三个奖励中选择一项。")



            return



        if not self._save_selected_slot():



            return



        args = [os.path.join(HERE, "national_day_wish.py")]



        if not status_only:



            args += ["--choice", str(self.var_wish_choice.get())]



        self._launch(args)







    def _launch(self, args, extra_env=None):



        if self.running or self.execution_gate.busy:



            self._append_log('[执行锁] 已有任务运行，忽略重复启动')



            return False



        if any(control.querying for control in getattr(self, 'arena_target_controls', {}).values()):



            messagebox.showinfo('查询对手', '请等待对手资料查询完成后再启动任务。')



            return



        try:



            with open(ACCOUNT_FILE, encoding='utf-8-sig') as stream:



                account = json.load(stream)



            extra_env = dict(extra_env or {})



            extra_env.update(self.spend_permissions.environment(account, args))



        except (OSError, ValueError, KeyError) as exc:



            messagebox.showerror('分类点券检测', str(exc))



            return False



        run_id = self.execution_gate.acquire()



        if run_id is None:



            return False



        self.running = True



        self._stop_requested = False



        for control in (self.cmb_account, self.cmb_slot, self.btn_login, self.btn_cookie_login):



            control.configure(state=tk.DISABLED)



        for button in self.feature_buttons + self.celebration_buttons:



            button.configure(state=tk.DISABLED)



        self.btn_run.configure(state=tk.DISABLED)



        for button in self.page_run_buttons.values():



            button.configure(state=tk.DISABLED)



        self.btn_farm.configure(state=tk.DISABLED)



        self.btn_world_boss.configure(state=tk.DISABLED)



        self.btn_union_boss.configure(state=tk.DISABLED)



        self.btn_pet_brawl.configure(state=tk.DISABLED)



        self.btn_pvp.configure(state=tk.DISABLED)



        self.btn_wish_status.configure(state=tk.DISABLED)



        self.btn_wish_sign.configure(state=tk.DISABLED)



        self.btn_teacher.configure(state=tk.DISABLED)



        self.btn_student.configure(state=tk.DISABLED)



        for button in self.btn_ttr_actions.values():



            button.configure(state=tk.DISABLED)



        self.btn_timeboat_status.configure(state=tk.DISABLED)



        self.btn_timeboat_exchange.configure(state=tk.DISABLED)



        self.btn_stop.configure(state=tk.NORMAL)



        try:



            threading.Thread(target=self._run_process, args=(args, extra_env, getattr(self, '_account_view_epoch', 0), run_id), daemon=True).start()



        except Exception as exc:



            self.log_queue.put('[启动失败] '+type(exc).__name__)



            self.log_queue.put(('__PROCESS_DONE__', run_id))



        return True







    def _run_process(self, args, extra_env=None, view_epoch=None, run_id=None):



        proc = None
        self._my_daily_result = None



        try:



            if self._stop_requested:



                return



            env = os.environ.copy(); env.update(extra_env or {})



            env['PYTHONPATH'] = HERE; env['PYTHONIOENCODING'] = 'utf-8'



            proc = subprocess.Popen(



                ([sys.executable, '--worker'] + args) if getattr(sys, 'frozen', False) else ([sys.executable, '-u'] + args),



                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=HERE, env=env,
                stdin=subprocess.PIPE if '--review-result' in args and os.path.basename(args[0])=='wash_run.py' else None,



                encoding='utf-8', errors='replace',



                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)



            self.proc = proc



            if self._stop_requested:



                proc.kill()



            for line in proc.stdout:



                output = line.rstrip()



                self.log_queue.put((view_epoch, output) if output.startswith('__') else output)



            proc.wait()



            self._my_daily_result = proc.returncode
            self.log_queue.put('[*] 进程结束，返回码：'+str(proc.returncode))



        except Exception as exc:



            self.log_queue.put('[工作进程异常] '+type(exc).__name__)



        finally:



            if proc is not None and proc.poll() is None:



                proc.kill(); proc.wait()



            self.log_queue.put(('__PROCESS_DONE__', run_id))







    def _poll_log(self):



        try:



            while True:



                line = self.log_queue.get_nowait()



                if isinstance(line, tuple) and line[0] == '__PROCESS_DONE__':



                    if not self.execution_gate.release(line[1]):



                        continue



                    self.proc = None



                    line = '__DONE__'



                if isinstance(line, tuple):



                    view_epoch, line = line



                    from account_view_cache import current



                    if not current(view_epoch, self):



                        self._append_log('[状态刷新] 已忽略切换账号或存档前的旧查询结果')



                        continue



                if line == "__DONE__":



                    self.running = False



                    self.cmb_account.configure(state='readonly'); self.cmb_slot.configure(state='readonly')



                    self.btn_login.configure(state=tk.NORMAL); self.btn_cookie_login.configure(state=tk.NORMAL)



                    for button in self.feature_buttons + self.celebration_buttons:



                        button.configure(state=tk.NORMAL)



                    self.btn_run.configure(state=tk.NORMAL)



                    for button in self.page_run_buttons.values():



                        button.configure(state=tk.NORMAL)



                    self.btn_farm.configure(state=tk.NORMAL)



                    self.btn_world_boss.configure(state=tk.NORMAL)



                    self.btn_union_boss.configure(state=tk.NORMAL)



                    self.btn_pet_brawl.configure(state=tk.NORMAL)



                    self.btn_pvp.configure(state=tk.NORMAL)



                    self.btn_wish_status.configure(state=tk.NORMAL)



                    self._refresh_wish_choices()



                    self.btn_teacher.configure(state=tk.NORMAL)



                    self.btn_student.configure(state=tk.NORMAL)



                    for button in self.btn_ttr_actions.values():



                        button.configure(state=tk.NORMAL)



                    self.btn_timeboat_status.configure(state=tk.NORMAL)



                    self.btn_timeboat_exchange.configure(state=tk.NORMAL)



                    self.btn_stop.configure(state=tk.DISABLED)



                else:



                    if line.startswith('__WASH_REVIEW__'):
                        try:
                            from wash_free_ui import review as review_wash
                            review_wash(self,json.loads(line[len('__WASH_REVIEW__'):]))
                        except Exception as exc:self._append_log('[灵符洗练] 结果确认失败：'+str(exc))
                        continue

                    if line.startswith('__WASH_FREE_STATE__'):
                        try:
                            from wash_free_ui import render as render_wash
                            render_wash(self,json.loads(line[len('__WASH_FREE_STATE__'):]))
                        except Exception as exc:self._append_log('[免费洗练] 列表更新失败：'+str(exc))
                        continue

                    if line.startswith('__FAIRY_FEED_STATE__'):
                        try:
                            self.fairy_feed_panel.render(json.loads(line[len('__FAIRY_FEED_STATE__'):]))
                        except Exception as exc:
                            self._append_log('[幻兽喂养] 列表更新失败：'+str(exc))

                    if line.startswith('__TTR_ESCORT_ABORT__'):
                        try:
                            reason=json.loads(line[len('__TTR_ESCORT_ABORT__'):]).get('message') or '策略状态需要核查。'
                        except (ValueError,TypeError):reason='策略状态需要核查，请查看运行日志。'
                        self._append_log('[通天河已中止] '+str(reason))
                        messagebox.showwarning('通天河已中止',str(reason),parent=self.root)
                    elif line.startswith('__BLACK_MARKET_STATE__'):



                        try:



                            self.black_market_page.render(json.loads(line[len('__BLACK_MARKET_STATE__'):]))



                        except Exception as exc:



                            self._append_log('[黑市] 状态显示失败：'+str(exc))



                    elif line.startswith('__MAZE_TARGET_STATE__'):



                        try:



                            self.maze_target_controls.render(json.loads(line[len('__MAZE_TARGET_STATE__'):]))



                        except Exception as exc:



                            self._append_log('[指定迷宫] 显示失败：'+str(exc))



                    elif line.startswith('__CARD_CAVE_RANK_STATE__'):



                        try:



                            self.card_cave_target_page.render_rank(json.loads(line[len('__CARD_CAVE_RANK_STATE__'):]))



                        except Exception as exc:



                            self._append_log('[藏宝洞榜单] 显示失败：'+str(exc))



                    elif line.startswith('__CARD_CAVE_TARGET_STATE__'):



                        try:



                            self.card_cave_target_page.render(json.loads(line[len('__CARD_CAVE_TARGET_STATE__'):]))



                        except Exception as exc:



                            self._append_log('[指定藏宝洞] 显示失败：'+str(exc))



                    elif line.startswith('__PET_ARENA_PAID_STATE__'):
                        try:
                            self.pet_arena_paid_panel.render(json.loads(line[len('__PET_ARENA_PAID_STATE__'):]))
                        except Exception as exc:
                            self._append_log('[点券斗宠] 显示失败：'+str(exc))
                    elif line.startswith('__TIME_CRYSTAL_STATE__'):
                        try:self.time_crystal_panel.render(json.loads(line[len('__TIME_CRYSTAL_STATE__'):]))
                        except Exception as exc:self._append_log('[时光水晶] 状态显示失败：'+str(exc))
                    elif line.startswith('__WISH_POOL_STATE__'):
                        try:self.wish_pool_panel.render(json.loads(line[len('__WISH_POOL_STATE__'):]))
                        except Exception as exc:self._append_log('[许愿池] 状态显示失败：'+str(exc))
                    elif line.startswith('__REBIRTH_STATE__'):

                        try:

                            self.rebirth_trial_page.render(json.loads(line[len('__REBIRTH_STATE__'):]))

                        except Exception as exc:

                            self._append_log('[轮回试炼] 状态显示失败：'+str(exc))

                    elif line.startswith('__STOVE_STATE__'):



                        try:



                            self.stove_page.render(json.loads(line[len('__STOVE_STATE__'):]))



                        except Exception as exc:



                            self._append_log('[炼丹炉] 状态显示失败：'+str(exc))



                    elif line.startswith('__PET_MATING_STATE__'):



                        try:



                            self.pet_mating_page.render(json.loads(line[len('__PET_MATING_STATE__'):]))



                        except Exception as exc:



                            self._append_log('[宠物上推荐] 状态显示失败：'+str(exc))



                    elif line.startswith('__PET_UTILITY_STATE__'):



                        try:



                            self.pet_utility_page.render(json.loads(line[len('__PET_UTILITY_STATE__'):]))



                        except Exception as exc:



                            self._append_log('采集/怪物卡/藏宝显示失败：%s' % exc)



                    elif line.startswith('__MATERIAL_EXCHANGE_STATE__'):



                        try:



                            self.material_exchange_page.render(json.loads(line[len('__MATERIAL_EXCHANGE_STATE__'):]))



                        except Exception as exc:



                            self._append_log('材料置换显示失败：%s' % exc)



                    elif line.startswith('__MAIL_STATE__'):



                        try:



                            self.mail_page.render(json.loads(line[len('__MAIL_STATE__'):]))



                        except Exception as exc:



                            self._append_log('邮件显示失败：%s' % exc)



                    elif line.startswith('__BAG_STATE__'):



                        try:



                            self.bag_warehouse_page.render(json.loads(line[len('__BAG_STATE__'):]))



                        except Exception as exc:



                            self._append_log('背包显示失败：%s' % exc)



                    elif line.startswith('__UNION_STATUS__'):



                        try:



                            state = json.loads(line[len('__UNION_STATUS__'):])



                            self.union_summary.set('%s｜魂石 %s｜魂玉 %s｜联盟贡献 %s｜今日材料购买 %s 次、贡献购买 %s 次、捐献 %s 次' %



                                (state['name'],state['stone'],state['jade'],state['contribution'],state['buyUsed'],state['contributionBuyUsed'],state['sellUsed']))



                            self.union_stock.configure(state=tk.NORMAL)



                            self.union_stock.delete('1.0',tk.END)



                            for row in state['rows']:



                                self.union_stock.insert(tk.END,'%s（%s）  仓库 %s  背包 %s  每件 %s %s / %s 贡献\n' %



                                    (row['name'],row['id'],row['stock'],next((b['count'] for b in state['bag'] if b['id']==row['id']),0),



                                     '%g'%row['currentCost'],'魂石' if row['currency']==101026007 else '魂玉',row['unionMoney']))



                            self.union_stock.configure(state=tk.DISABLED)



                        except Exception as exc:



                            self._append_log('联盟仓库状态显示失败：%s' % exc)



                    else:



                        self._append_log(line)



        except queue.Empty:



            pass



        self.root.after(100, self._poll_log)







    def _stop(self):



        if not self.running and not self.execution_gate.busy:



            return



        self._stop_requested = True



        self._append_log('[*] 已请求停止，等待子进程退出后才允许再次启动。未确认的游戏请求请刷新状态，不会自动重发。')



        self.btn_stop.configure(state=tk.DISABLED)



        if self.proc is not None:



            try:



                self.proc.kill()



            except OSError:



                pass











if __name__ == "__main__":



    root = tk.Tk()



    app = DailyGUI(root)



    root.after(100, app._poll_log)



    root.mainloop()











