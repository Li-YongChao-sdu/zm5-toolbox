# -*- coding: utf-8 -*-
"""一键日常(均已对真实服验证):
  登录: cookie -> fetch_game_token -> queryEntry -> auth -> connector.entryHandler.entry
  领VIP礼包 / 联盟贡献 / 竞技场扫荡 / 斗宠扫荡 / 神秘商店 / 藏宝洞 / 活跃里程碑
  自选关卡副本(森林/十殿/天树王/九宫玄塔): 游戏内可自选关卡, 默认自动打【最高已解锁关】,
     也可用 STAGE_OVERRIDE 指定关卡; 每日免费次数为同组共享, 用尽即停(超出会静默扣点券/ticket!)。
  跳过战斗: create{mid,rnd} -> finish{win:1,rnd,star:3}; 噩梦额外开共享宝箱 getDungeonTreasureDrop。
     ★所有会扣票/扣点券的 create 前都先按服务器存档 dailyCount 算免费剩余, 用尽即停。
  战斗层: 九宫玄塔(全塔共享3次/天, 默认重复打最高关)、镇妖塔、灵宠试炼、活动Boss、十绝阵/蛮荒。
  掉落聚合写入 drops_log.jsonl。

反作弊: 游戏有 playerCheat 上报。单次、限速、别多号同节奏, 防封号。
"""
import time, random, json, os
from arena_selection import MODES as ARENA_MODES, choose_opponent, opponent_power
from collections import defaultdict
from game_version import GAME_VERSION, XIE_ROLE_SWITCHES, active_xie_names, active_xie_switches
from daily_task_quota import quota_from_info
from pypomelo.login4399 import fetch_game_token
from pypomelo.flow import GameLoginFlow

# 账号来源(优先级): account.enc -> account.local.json -> 运行时交互输入
def _prompt_account():
    print("\n=== 账号登录方式 ===")
    print("  1) 账密直登 (输4399账号/密码, 自动拿cookie)")
    print("  2) 手动粘贴 cookie (从浏览器 F12->Cookies->ptlogin.4399.com 复制)")
    mode = input("选 1 或 2 (回车默认2): ").strip() or "2"
    if mode == "1":
        import getpass
        from ptlogin_login import login_by_password
        username = input("4399登录账号/手机号: ").strip()
        password = getpass.getpass("密码(输入不显示): ").strip()
        res = login_by_password(username, password)
        if res.get("need_captcha"):
            print("[!] 该账号触发验证码/异地校验, 自动登录无法过验证码, 请改用方式2。")
            return _prompt_account()
        if not res.get("ok"):
            print("[!] 登录失败:", res.get("error"))
            return _prompt_account()
        cks = res["cookies"]
        uid = res.get("uid") or input("数字uid (自动解析失败, 请手输): ").strip()
        idx = input("存档槽位(0-7, 回车默认0, 主存档不在1号位就填它所在槽): ").strip()
        acc = {"uid": uid, "username": cks.get("Puser") or username,
               "record_index": int(idx) if idx.isdigit() else 0, "cookies": cks}
        print("账密登录成功: uid=%s, USESSIONID=%s ..." % (uid, cks.get("USESSIONID", "")[:8]))
    else:
        print("\n请输入你自己的账号(从浏览器F12->Cookies->ptlogin.4399.com复制):")
        uid = input("数字uid (如 266089266): ").strip()
        username = input("登录账号 (Puser): ").strip()
        print("—— 以下 Cookie 值整串粘贴 ——")
        uses = input("USESSIONID: ").strip()
        uauth = input("Uauth: ").strip()
        pauth = input("Pauth: ").strip()
        xauth = input("Xauth: ").strip()
        idx = input("存档槽位(0-7, 回车默认0, 主存档不在1号位就填它所在槽): ").strip()
        acc = {"uid": uid, "username": username, "record_index": int(idx) if idx.isdigit() else 0,
               "cookies": {"USESSIONID": uses, "Uauth": uauth, "Pauth": pauth,
                           "Puser": username, "Xauth": xauth}}
    if input("是否保存到 account.local.json 下次免输? (y/N): ").strip().lower() == "y":
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "account.local.json"), "w", encoding="utf-8") as f:
            json.dump(acc, f, ensure_ascii=False, indent=2)
        print("已保存 account.local.json")
    return acc


def _load_account():
    here = os.path.dirname(os.path.abspath(__file__))
    enc = os.path.join(here, "account.enc")
    if os.path.exists(enc):
        pwd = os.environ.get("ACCOUNT_PASSWORD")
        if not pwd:
            import getpass
            pwd = getpass.getpass("输入账号加密密码: ")
        from account_crypto import decrypt_bytes
        return json.loads(decrypt_bytes(open(enc, "rb").read(), pwd).decode("utf-8"))
    local = os.path.join(here, "account.local.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    return _prompt_account()

_ACC = _load_account()
COOKIES = _ACC["cookies"]
UID = _ACC["uid"]; USERNAME = _ACC["username"]
GATE_IPS = ["82.157.236.253", "101.43.232.80", "101.42.229.203",
            "101.43.164.20", "82.157.236.99", "43.143.171.37",
            "82.157.238.37", "43.143.246.102"]
PORT = 3010
RECORD_INDEX = int(_ACC.get("record_index", 0))  # 存档槽位(0起), 在账号文件 account.enc/local.json 里配 "record_index"

RUN_VIP_GIFT = True
RUN_ARENA_REWARD = False
RUN_PET_ARENA_REWARD = False
RUN_ARENA_SIGNUP = False
RUN_PET_ARENA_SIGNUP = False
RUN_MONTHCARD_REWARD = False
RUN_SHANFA_LIKE = False
RUN_WISH_POOL_REWARD = False
RUN_WISH_POOL_RANDOM = False
WISH_POOL_MODE = 'manual'
WISH_POOL_PLAN = None
RUN_FAIRY_REWARD = False
RUN_ACCEPT_DAILY_TASKS = True
DAILY_TASK_SELECTED_IDS = []  # GUI 自选接取的每日任务 ID；独立于精英关卡勾选
RUN_DEVOTE = True
RUN_APPRENTICE_LEARN = True  # 学艺只使用每日免费次数
RUN_APPRENTICE_TEACH = True  # 授课每日一次
RUN_ARENA = True
RUN_PET_ARENA = True
ARENA_MODE = "fixed"       # fixed=随机选一人连续挑战; refresh=每场重新获取推荐对手
PET_ARENA_MODE = "fixed"
ARENA_TARGET_UID = ""
ARENA_TARGET_SLOT = "0"
ARENA_TARGET_ROUNDS = 5
PET_ARENA_TARGET_UID = ""
PET_ARENA_TARGET_SLOT = "0"
PET_ARENA_TARGET_ROUNDS = 5
ARENA_TARGET_INPUT = 'r_number'
ARENA_TARGET_RID = ''
PET_ARENA_TARGET_INPUT = 'r_number'
PET_ARENA_TARGET_RID = ''
ARENA_TARGET_R_NUMBER = ''
PET_ARENA_TARGET_R_NUMBER = ''
ARENA_TOP_N = 20
PET_ARENA_TOP_N = 20
ARENA_BATTLE_WAIT = 22
ARENA_ROUND_WAIT = 22
PET_ARENA_BATTLE_WAIT = 2
PET_ARENA_ROUND_WAIT = 8


ARENA_REFRESH_INTERVAL = 5  # refresh 模式每场结算后的最短间隔(秒)
RUN_FOREST = True
FOREST_AUTO_CRYSTAL = False
FOREST_MODE = "sweep"  # 默认速通扫荡；manual=固定关卡手打，preview=只查看材料
RUN_MYSTERY_SHOP = True
MYSTERY_BUY_TIMES = 10
RUN_CARD_CAVE = True
CARD_CAVE_MODE = 'specified'  # 默认指定挑战码；recommend=每局刷新推荐选最高守备
CARD_CAVE_CODE = '3922097053_r3_1'
CARD_CAVE_FINGERPRINT = '2978a418286247eaff18f8ee65d53ddfd4ecd8c6c3888ab04ed1cfb5f8229df3'
CARD_CAVE_WAIT = 2
CARD_CAVE_TIMES = 5        # 本次最多挑战1–5次；仅使用每日剩余免费次数
RUN_HALO = True
HALO_TARGET_SCORE = 3000  # 十绝阵奖励档位：1000 或 3000
HALO_TEAM_MODE = 'single'  # single=单人；three=三人3000分（日常单账号跳过，用“三人组队开打”）
# 十绝阵奖励次数每天恢复1次，最多存5次；执行时以服务器返回的剩余次数为准。
DEMON_TOWER_TARGET_LAYER = 0  # 0=最高已解锁层段；1=1-5、2=11-15、...、16=151-155
RUN_MANHUANG = True
# 蛮荒副本列表(按解锁顺序): 荒蛇->白泽->饕餮->混沌->穷奇->诸怀->烛龙->鲲鹏->...->北冥鲲
# 默认自动打最高已解锁关; 也可在 gui_config.py 用 MANHUANG_MID 指定具体关卡
MANHUANG_MIDS = [
    (1400101, "九江穴"), (1400102, "瑶碧山"), (1400103, "太山"),
    (1400104, "鹿吴之山"), (1400105, "谯明之河"), (1400106, "小次之山"),
    (1400107, "极渊"), (1400108, "北极柜山"), (1400109, "荒域"),
    (1400110, "圭阝山"), (1400111, "钩吾山谷"), (1400112, "洪蒙金山"),
    (1400113, "北冥"),
]
MANHUANG_MID = 0  # 0=自动选最高已解锁, 否则指定具体mid
# 蛮荒副本模式: multi=多人版(1400xxx, 宝箱掉2~4个), solo=单人版(1410xxx, 宝箱掉1~3个)
# 多人版掉落更多, 默认多人版; gui_config.py 可覆盖 MANHUANG_MODE
MANHUANG_MODE = "multi"
RUN_FLUSHOU = True
FLUSHOU_MODE = "all"       # all=用完剩余免费次数；once=每项本次仅执行一次
FLUSHOU_MIDS = [(200101, "福"), (200201, "禄"), (200301, "寿")]
RUN_ACTIVITY = True
ACTIVE_XIE_SWITCHES = active_xie_switches()
ACTIVITIES = [
    {"name": "刑天", "normal": 500105, "hard": 500111, "shared": [500105, 500111], "max": 2},
    {"name": "牛魔王",  "normal": 500104, "hard": 500110, "shared": [500104, 500110], "max": 2},
    {"name": "魔龙",    "normal": 500107, "hard": 500108, "shared": [500107, 500108], "max": 2},
    {"name": "GM切磋",  "normal": 500120, "hard": 500127, "shared": [500120, 500127], "max": 2},
    {"name": "挑战GM",  "normal": 500112, "hard": 500113, "shared": [500112, 500113], "max": 3},
    {"name": "邪·悟空", "normal": 500114, "hard": 500115, "shared": [500114, 500115], "max": 1},
    {"name": "邪·瑶瑶", "normal": 500137, "hard": 500138, "shared": [500137, 500138], "max": 1},
    {"name": "邪·唐僧", "normal": 500116, "hard": 500117, "shared": [500116, 500117], "max": 1},
    {"name": "邪·龙女", "normal": 500118, "hard": 500119, "shared": [500118, 500119], "max": 1},
    {"name": "邪·二郎神", "normal": 500121, "hard": 500122, "shared": [500121, 500122], "max": 1},
    {"name": "邪·八戒", "normal": 500123, "hard": 500124, "shared": [500123, 500124], "max": 1},
    {"name": "邪·沙僧", "normal": 500125, "hard": 500126, "shared": [500125, 500126], "max": 1},
    {"name": "邪·白龙", "normal": 500128, "hard": 500129, "shared": [500128, 500129], "max": 1},
]
ACTIVITY_PREFER = "hard"    # hard=免费次数优先噩梦; normal=普通
# 各活动独立开关
RUN_ACT_XINGTIAN = True  # 刑天：普通/噩梦每日共享2次免费
RUN_ACT_MONKIAN = True
RUN_ACT_DRAGON = True
RUN_ACT_GM = False  # GM切磋：每日共享2次免费机会
RUN_ACT_FIGHT_GM = True  # 挑战GM（挑战萌哥）：普通/噩梦每日共享3次免费
RUN_ACT_XWUKONG = "RUN_ACT_XWUKONG" in ACTIVE_XIE_SWITCHES
RUN_ACT_XYAOYAO = "RUN_ACT_XYAOYAO" in ACTIVE_XIE_SWITCHES
RUN_ACT_XTANG = "RUN_ACT_XTANG" in ACTIVE_XIE_SWITCHES
RUN_ACT_XLONG = "RUN_ACT_XLONG" in ACTIVE_XIE_SWITCHES
RUN_ACT_XYANGJIAN = "RUN_ACT_XYANGJIAN" in ACTIVE_XIE_SWITCHES
RUN_ACT_XBAJIE = "RUN_ACT_XBAJIE" in ACTIVE_XIE_SWITCHES
RUN_ACT_XSHASENG = "RUN_ACT_XSHASENG" in ACTIVE_XIE_SWITCHES
RUN_ACT_XBAILONG = "RUN_ACT_XBAILONG" in ACTIVE_XIE_SWITCHES
RUN_NINE_TOWER = True
RUN_XUANTA_EVENT = True  # 限时任务「玄塔有灵」：接取、免费通关一次、领奖
RUN_SKY = False            # 天树王：按关卡设置选择，每日共享免费2次
RUN_ELITE = True           # 精英关：只刷 ELITE_MULTI_MIDS 选中的关卡，每关每天最多免费2次
ELITE_MULTI_MIDS = []      # 只刷界面明确选中的精英关
ELITE_CLAIM_FREE_CARD = True  # 每次通关后先取牌面，再翻一次免费牌
ELITE_SELL_BOSS = False
ELITE_SELL_SMALL = False
ELITE_SELL_MEDICINE = False
RUN_TEN = True             # 十殿阎罗/五毒炼狱：每日合计共享3次
RUN_NIGHTMARE_SKY = False  # 噩梦天树王：每周2次，独立于日常天树王
RUN_SKY = False
RUN_DEMON_TOWER = True
RUN_DEMON_TOWER2 = True  # 镇妖塔，独立于噩梦关卡
NIGHTMARE_CLAIM_FREE_CARD = True
NIGHTMARE_CARD_PAID = False  # 显式开启才允许消耗翡翠钥匙额外翻牌
NIGHTMARE_CARD_STRATEGY = 'dynamic'  # free / static / dynamic，默认动态策略
RUN_PET_TOWER = True
RUN_FREE_MAZE = True       # 造梦迷宫：每日活跃任务最多3次
FREE_MAZE_TARGET_CODE = ''
FREE_MAZE_FINGERPRINT = ''
FREE_MAZE_WAIT = 30
FREE_MAZE_MODE = "high"   # high=高挑战次数/高通关率，low=高挑战次数/低通关率
RUN_LIVENESS = True
RUN_PERMANENT_FASHION = True
RUN_WHITE_DRAGON = True
RUN_GROWTH_BUFF = True       # 成长挑战：每日登录领取2小时双倍buff（掉宝100%+灵魂100%+经验100%）
RUN_LANDING_NEW = False      # 新手8天登录有礼：默认新版路由（带 loginAct，服务端下发值）
RUN_LANDING_LEGACY = False   # 新手8天登录有礼：老版备用路由（不带 loginAct）
RUN_NOVICE_GIFT = False      # 新手有礼（活动173，第1~6天）：一键领取已完成任务+当天礼包
RUN_NOVICE_CHECK = False     # 新手有礼：只查询状态不领取
RUN_WEEKEND_BUFF = True      # 周末在线福利·第一档双倍buff（960001，仅周五/周六/周日有任务）
RUN_WEEKEND_ONLINE = True    # 周末在线福利·在线2/5/10/20分钟档+累计5档礼包（960002~960006）
RUN_GROWTH_DUNGEON = True    # 成长挑战：通关主线任务（昆仑宫/天墉城/…），自动接取→通关→领奖
RUN_GROWTH_ACCEPTALL = True  # 成长挑战：一键接取全部47个任务（免费，不看勾选）
RUN_GROWTH_FREE = True       # 成长挑战：一键完成【只限主线+蛮荒】（不耗额外次数/点券，不看勾选）
RUN_GROWTH_ACCEPT = True     # 成长挑战：按勾选接取任务（含祖巫只接不打）
RUN_GROWTH_MANHUANG = True   # 成长挑战：蛮荒4关各通关5次领奖（不领共享宝箱）
RUN_GROWTH_HALO = True       # 成长挑战：十绝阵831029~034按奖励次数补打领奖
RUN_GROWTH_DAN = True        # 成长挑战：炼丹831039~047（缺基础材料自动置换）
RUN_GROWTH_POINT = True      # 成长挑战：积分档位奖励1001~1018
RUN_GROWTH_CLAIM_ONLY = True # 成长挑战：一键领取（只提交已完成任务+积分档位，不接取不打本、不耗次数）
RUN_GROWTH_BUY_VIP = False   # 成长挑战：购买至尊特权（3600点券）；默认关，必须配合确认锁口令
GROWTH_VIP_CONFIRM = ""      # 确认锁：必须严格等于 "确认购买至尊特权" 才会真正扣点券
GROWTH_VIP_COST = 3600       # 至尊特权价格（GrowthHelper.json 的 open_ticket）
# 成长挑战细分选择：None=该类别全部执行；列表=只执行这些任务qId（GUI 折叠列表勾选后写入 gui_config.py）
RUN_GROWTH_ACCEPT_IDS = None    # 831001~831047 中要接取的
RUN_GROWTH_DUNGEON_IDS = None   # 831001~831016 中要通关的
RUN_GROWTH_MANHUANG_IDS = None  # 831035~831038
RUN_GROWTH_HALO_IDS = None      # 831029~831034
RUN_GROWTH_DAN_IDS = None       # 831039~831047
RUN_GROWTH_POINT_IDS = None     # 1001~1018 / 2001~2018
RUN_FASHION_SIGNIN = True       # 永久时装：每日签到领奖
RUN_FASHION_ONLINE = True       # 永久时装：在线20分钟任务 970002 领奖（不挂机）
RUN_FASHION_SHOP = False        # 永久时装：玉珠商店购买（只花玉珠，按 purchaseMaxNum 限购）；默认关
RUN_FASHION_SHOP_QTY = None     # None=不买；{shopId: 数量}（GUI 勾选并填数量后写入）
RUN_CELEBRATION = False
RUN_CELEBRATION_ONLINE = False
CELEBRATION_SPIRIT_BACKUP = False
RUN_CLIMB_HIGH = True  # 重阳采菊：100分，剩余免费次数
CLIMB_HIGH_SCORE = 100
RUN_STAR_MAZE = True       # 星斗幻境: 一次通关三大层(只走免费, 不花点券/ticket)
RUN_MID_AUTUMN = True     # 中秋博饼: 免费掷骰
RUN_JIN_QIU = True        # 金秋送福: 金秋蜜意红包每日免费开箱1次
RUN_DRAGON_TREASURE_TASKS = True  # 龙宫寻宝: 领取已完成任务奖励, 不投骰
RUN_CLOUD_LADDER = True   # 夺宝云梯: 免费1次
RUN_DOG_CARD = False      # 账号共享每日普通抽狗卡；服务端判定剩余次数
RUN_ELITE_STONE = False  # 日常：精英免费翻牌获取每日4个万能强化石
RUN_MAGIC_RABBIT = False  # 主线追加魔玉兔，每日活动次数上限2
RUN_MAGIC_CRYSTAL = False  # 魔法水晶球：手动领取至每日11个
PICKUP_SUPPLIES = False  # 全局逐件拾取：默认不领取萝卜/蟠桃/蓝瓶/蓝壶
RUN_RELIC_TREASURE = False # 遗迹寻宝: 目前暂未开放
RUN_STOVE = True          # 聚灵池/炼丹炉: 免费炼制
RUN_WANXIANG = True        # 万象古树(1400600): 每天免费2次, 开共享宝箱
# 竞技场/斗宠大会分别控制免费次数用尽后的点券续战(20点券/场)。
# 默认均关闭; 开启时按各自次数上限执行。
ARENA_PAID_EXTRA = False
ARENA_PAID_EXTRA_TIMES = 0   # 0=不限场次, 打到点券不足为止; 也可设为具体次数上限
PET_ARENA_PAID_EXTRA = False
PET_ARENA_PAID_EXTRA_TIMES = 0
PAID_CONFIRM_BITS = "000"  # 三个确认框必须恰好为 101，点券续战才可执行

# ===== 自选关卡: 默认自动打"最高已解锁关", 也可在这里手动指定关卡mid(填None=自动) =====
# 判定: 服务器存档 info.dungeon[mid].passNum>0 视为已解锁可打, 取组内最大mid。
STAGE_OVERRIDE = {
    "forest": None,     # 神兽森林(300101~300112), 每日共享4次
    "ten": None,        # 十殿阎罗(400101~401501), 每日共享3次
    "sky": None,        # 天树王(700101/700201/700301), 每日共享2次
    "nine": None,       # 九宫玄塔(全塔), 每日共享3次, 都打在最高关
    "wanxiang": 300113, # 万象古树目前只有丹熏山
    "elite": None,      # 旧版精英单选配置；现由 ELITE_MULTI_MIDS 控制
}

# 各组关卡顺序(用于挑最高解锁关)与共享免费池
_FOREST = list(range(300101, 300113))
_TEN = [400101 + i * 100 for i in range(0, 15)]
_SKY = [700101, 700201, 700301]
_SKY_BOSS_ROOMS = {700101: 700102, 700201: 700202, 700301: 700302}
_NINE_POOL = [100011, 100021, 100031, 100041, 100051, 100061, 100071, 100081, 100091,
              100101, 100102, 100103, 100104, 100105, 100106, 100107, 100108, 100109,
              100201, 100202, 100203, 100204, 100301, 100302, 100303]
NINE_TOWER_MAX = 3
# 精英/主线组: id 末位为0(30010碧玉径…30800七星殿…), 每关独立 dailyCountMax=2、不共享; BOSS关(末位1/2)不计
ELITE_STAGES = list(range(30010, 30801, 10))
ELITE_MAX = 2
# 自选关卡组: stages=可挑关卡, shared=共享计数池, max=每日免费上限, chest=是否开共享宝箱
FARM_GROUPS = [
    {"key": "forest", "stages": _FOREST, "shared": _FOREST, "max": 4, "prefix": "神兽森林", "chest": False},
    {"key": "ten",    "stages": _TEN,    "shared": _TEN,    "max": 3, "prefix": "十殿阎罗/五毒炼狱", "chest": False},
    {"key": "sky",    "stages": _SKY,    "shared": _SKY,    "max": 2, "prefix": "天树王",   "chest": False},
]
# 噩梦关卡自选: 默认七星殿, GUI可覆盖
NIGHTMARE_MID = 40270
DROPS_LOG = "drops_log.jsonl"
DEVOTE_TIERS = [1]
MAX_TIMES = 30
SLEEP = 1.2
FIGHT_DELAY = True  # 模拟战斗延迟(2-3秒), 降低联机检测风险; GUI可关

FAIRY_DAILY_POSITIONS = [0, 1, 2]
FAIRY_DAILY_PREFERENCES = None
RUN_BLACK_MARKET_DAILY = False
RUN_MY_DAILY_FUN = False
MY_DAILY_FUN_JOBS = []

# GUI 覆盖配置: 如果存在 gui_config.py, 用它覆盖上面的开关
try:
    import gui_config as _gc
    for _k in dir(_gc):
        if _k.isupper():
            globals()[_k] = getattr(_gc, _k)
except ImportError:
    pass

# 活动暂未开放；旧版 gui_config.py 即使仍勾选，也不执行该活动。
RUN_RELIC_TREASURE = False

# 旧GUI配置也不能启动过期活动。
from activity_availability import WINDOWS as _ACTIVITY_WINDOWS, disabled_reason as _activity_disabled_reason
for _activity_key in _ACTIVITY_WINDOWS:
    if _activity_disabled_reason(_activity_key):
        globals()[_activity_key] = False

# 配置文件保留用户对本轮活动的勾选，但不能让旧版本配置误开其他轮换组。
for _xie_key in XIE_ROLE_SWITCHES:
    globals()[_xie_key] = bool(globals().get(_xie_key, False)) and _xie_key in ACTIVE_XIE_SWITCHES


def list_slots(flow, record_index=None):
    """枚举账号全部存档槽(connector.roleHandler.getUserInfo), 打印表格, 返回 {index: {p1,p2,status}}。
    0=空槽 1=有角色 3=冻结; p1/p2 为该槽双角色位。"""
    r = flow.request("connector.roleHandler.getUserInfo", {})
    u = r.get("user", r) if isinstance(r, dict) else {}
    records = u.get("records") or []
    print("== 存档列表 (uid=%s 昵称=%s 共%d槽) ==" % (u.get("uid"), u.get("name"), len(records)))
    print("%-4s | %-18s | %-18s | %s" % ("槽位", "角色1(p1)", "角色2(p2)", "状态"))
    slots = {}
    for rec in records:
        def pv(p):
            return "%s Lv%s" % (p.get("name"), p.get("level")) if p else "-"
        st = {0: "空", 1: "有", 3: "冻结"}.get(rec.get("status"), str(rec.get("status")))
        p1, p2 = rec.get("p1"), rec.get("p2")
        slots[rec.get("index")] = {"p1": pv(p1), "p2": pv(p2), "status": rec.get("status")}
        print("%-4s | %-18s | %-18s | %s" % (rec.get("index"), pv(p1), pv(p2), st))
    selected = RECORD_INDEX if record_index is None else int(record_index)
    print(">> 当前使用存档槽位: %d" % selected)
    return slots


def login(record_index=None):
    slot_index = RECORD_INDEX if record_index is None else int(record_index)
    if not 0 <= slot_index <= 7:
        raise ValueError("存档槽位须为 0～7")
    token = fetch_game_token(UID, USERNAME, COOKIES)
    flow = GameLoginFlow(uid=UID, token=token)
    for ip in GATE_IPS:
        try:
            host, port = flow.query_entry(ip, PORT)
            flow.auth(host, port)
            list_slots(flow, slot_index)   # 先确定号+存档, 再进对应槽位
            ent = flow.request("connector.entryHandler.entry",
                               {"index": slot_index, "userAgent": flow.user_agent})
            print("已进游戏(存档槽位 %d)" % slot_index)
            return flow, ent.get("info", {})
        except Exception as e:
            print(ip, "失败:", e); flow.disconnect()
    raise SystemExit("登录失败")


def _dungeon_rec(info, mid):
    rec = info.get("dungeon", {}).get(str(mid))
    return rec if isinstance(rec, dict) else None


def _dungeon_dcount(info, mid):
    rec = _dungeon_rec(info, mid)
    return rec.get("dailyCount", 0) if rec else 0


def quota_remain(info, shared, free_max):
    """共享池剩余免费次数; free_max<0 表示无上限(返回 None)。"""
    if free_max is None or free_max < 0:
        return None
    return free_max - sum(_dungeon_dcount(info, m) for m in shared)


def pick_highest_cleared(info, stages):
    """组内 passNum>0(已解锁可打) 的最高关卡; 一个都没打过就回退第一关。"""
    avail = [m for m in stages if (lambda r: r and r.get("passNum", 0) > 0)(_dungeon_rec(info, m))]
    return max(avail) if avail else stages[0]


def forest_selected_materials(flow):
    """读取本轮选中怪物，只显示当前选中的奖励位置和材料。"""
    response = flow.request("scene.copyHandler.getSelectMonster", {})
    selected = response.get("selectMonster") if isinstance(response, dict) else None
    if not isinstance(selected, dict):
        print("[神兽森林] 读取选中怪物失败: %s" % response)
        return
    catalog_path = os.path.join(os.path.dirname(__file__), "forest_rewards.json")
    try:
        with open(catalog_path, encoding="utf-8") as f:
            catalog = json.load(f)
    except (OSError, ValueError) as exc:
        print("[神兽森林] 材料对照表读取失败: %s" % exc)
        return
    for mid in _FOREST:
        row = catalog.get(str(mid), {})
        positions = row.get("positions") or []
        chosen = selected.get(str(mid)) or {}
        fixed_rewards = ("护盔", "护甲", "爪套", "蹄甲", "全强化石（无固定装备）")
        current = [(index, pos) for index, pos in enumerate(positions[:5], 1)
                   if pos.get("monster_id") in chosen]
        if not current:
            print("[神兽森林] %s %s：未返回当前奖励位置" % (mid, row.get("name", "")))
            continue
        for index, pos in current:
            materials = "、".join(item["name"] for item in pos.get("materials") or []) or "配置未列出"
            part = (pos.get("position") or "").split("-", 1)[-1] or pos.get("monster_id")
            if index == 5:
                part = "完全体"
            print("[神兽森林] %s %s：位置%d %s [%s]，材料：%s" %
                  (mid, row.get("name", ""), index, part,
                   fixed_rewards[index - 1], materials))
    print("[神兽森林] 提示：只有通关一次或者每日刷新后，才能更新该位置的掉落。")


def sweep_forest(flow, info, mid, max_runs=4):
    """扫荡前按需最多补1个水晶，只用神兽森林剩余免费次数。"""
    rec = _dungeon_rec(info, mid)
    if not rec or int(rec.get("passNum") or 0) <= 0:
        print("[神兽森林] %s 尚未通关，不能扫荡" % mid)
        return {}
    if FOREST_AUTO_CRYSTAL:
        from forest_crystal import prepare
        prepare(flow,info,RECORD_INDEX,lambda current:quota_remain(current,_FOREST,4),password=os.environ.get('ZM5_FOREST_CRYSTAL_PASSWORD',''))
    energy = int(info.get("sweepEnergy") or 0)
    completed = 0
    bag = defaultdict(int)
    def sweep_ticket_balance():
        reply = flow.request('connector.roleHandler.getUserInfo', {})
        value = (reply.get('user') or {}).get('ticket') if isinstance(reply, dict) else None
        if value is None:
            raise RuntimeError('[神兽森林] 无法确认点券余额，停止扫荡')
        return int(value)
    ticket_before = sweep_ticket_balance()
    for _ in range(min(4, max_runs)):
        fresh = flow.request('connector.entryHandler.entry',
                             {'index': RECORD_INDEX, 'userAgent': flow.user_agent})
        current = fresh.get('info') if isinstance(fresh, dict) else None
        if not isinstance(current, dict) or fresh.get('error'):
            raise RuntimeError('[神兽森林] 无法读取最新速通能量和免费次数，停止')
        info.clear(); info.update(current)
        rec = _dungeon_rec(info, mid)
        if not rec or int(rec.get('passNum') or 0) <= 0:
            print('[神兽森林] 当前关卡未通关，停止扫荡'); break
        if quota_remain(info, _FOREST, 4) <= 0:
            print('[神兽森林] 免费次数用尽，停止扫荡'); break
        if info.get('sweepEnergy') is None:
            raise RuntimeError('[神兽森林] 无法确认最新速通能量，停止')
        energy = int(info['sweepEnergy'])
        if sweep_ticket_balance() != ticket_before:
            raise RuntimeError('[神兽森林] 点券余额变化，停止扫荡')
        if energy < 10:
            print("[神兽森林] 速通能量不足（当前%d，本轮需10），停止扫荡，不使用点券补足" % energy)
            break
        result = flow.request("scene.copyHandler.sweep",
                              {"mid": mid, "type": 0, "passNum": rec["passNum"]})
        if not isinstance(result, dict) or result.get("code") != 200 or result.get("error"):
            print("[神兽森林] 扫荡停止: %s" % result)
            break
        consume = result.get("consume") or []
        if any(item.get("subType") == "ticket" for item in consume if isinstance(item, dict)):
            raise RuntimeError("[神兽森林] 扫荡出现非预期点券消耗，已停止")
        if sweep_ticket_balance() != ticket_before:
            raise RuntimeError('[神兽森林] 扫荡后点券余额变化，已停止')
        server_rec = result.get("dungeon") or {}
        if server_rec.get("id") == mid:
            rec.update(server_rec)
        else:
            rec["dailyCount"] = int(rec.get("dailyCount") or 0) + 1
        energy_left = next((item.get("remian") for item in consume
                            if isinstance(item, dict) and item.get("subType") == "sweepEnergy"
                            and item.get("remian") is not None), None)
        energy = int(energy_left) if energy_left is not None else energy - 10
        info["sweepEnergy"] = energy
        completed += 1
        _agg_drops(bag, result.get("give"))
        print("[神兽森林] 第%d次扫荡成功，剩余速通能量%d，奖励=%s" %
              (completed, energy, result.get("give") or result.get("drops")))
        time.sleep(SLEEP)
    print("[神兽森林] 本次扫荡%d次" % completed)
    return dict(bag)


def claim_vip_gift(flow, info):
    level = int((info.get("vip") or {}).get("level") or 0)
    if level <= 0:
        print("[VIP礼包] 当前没有VIP等级，跳过")
        return
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feature_config", "VIP.json")
    with open(config_path, encoding="utf-8") as stream:
        row = json.load(stream).get(str(level)) or {}
    gift_id = int(row.get("giftBagId") or 0)
    if gift_id <= 0:
        raise RuntimeError("VIP%s未配置每日礼包ID" % level)
    print("[VIP礼包] level=%s 每日giftId=%s" % (level, gift_id))
    reply = flow.request("scene.giftHandler.getGift", {"giftId": gift_id})
    if not isinstance(reply, dict) or reply.get("code") != 200 or reply.get("error"):
        print("[VIP礼包] 领取未成功：%s" % (reply.get("error") if isinstance(reply, dict) else reply))
        return
    print("[VIP礼包] 领取成功：%s" % reply.get("give"))
    for key in ("everyDaySetting", "everyWeekSetting", "gift"):
        if isinstance(reply.get(key), dict):
            info.setdefault(key, {}).update(reply[key])
    return reply


_BUFF_NAMES = {
    "101081": "成长祝福·掉宝率100%",
    "102051": "成长祝福·灵魂100%",
    "103061": "成长祝福·经验100%",
}


def claim_growth_buff(flow, info):
    """成长挑战-每日祝福：领取2小时双倍buff（掉宝/灵魂/经验各100%）。

    任务ID 839001（GrowthChallengeTask.json），奖励 rewardId=12601。
    流程：acceptQuest -> 等待服务端同步 -> commitQuest。
    """
    qid = 839001
    print("[成长双倍buff] 接受任务 qId=%s" % qid)
    acc = flow.request("scene.questHandler.acceptQuest", {"qId": qid})
    if not isinstance(acc, dict):
        print("[成长双倍buff] accept 返回异常：%s" % acc)
        return
    acc_err = acc.get("error")
    acc_code = acc.get("code")
    # 已接受过也可继续领取
    if acc_code != 200 and acc_err not in (None, "任务已接受"):
        print("[成长双倍buff] accept 失败：code=%s error=%s" % (acc_code, acc_err))
        return
    # 服务端需要时间把任务从"已接受"推进到"已完成"，等2秒再领
    time.sleep(2)
    print("[成长双倍buff] 领取奖励 qId=%s" % qid)
    reply = flow.request("scene.questHandler.commitQuest", {"qId": qid})
    if not isinstance(reply, dict):
        print("[成长双倍buff] commit 返回异常：%s" % reply)
        return
    if reply.get("code") != 200 or reply.get("error"):
        print("[成长双倍buff] 领取未成功：%s" % (reply.get("error") or reply.get("code")))
        return
    give = reply.get("give") or []
    names = []
    for g in give:
        sub = str(g.get("subType") or "")
        names.append(_BUFF_NAMES.get(sub, "buff%s" % sub))
    print("[成长双倍buff] 领取成功：%s" % "、".join(names))
    for key in ("everyDaySetting", "roleBuff"):
        if isinstance(reply.get(key), dict) and isinstance(info.get(key), dict):
            info[key].update(reply[key])
    return reply


def claim_landing_reward(flow, info, legacy=False):
    """新手8天登录有礼：默认新版路由 scene.activityHandler.getLandingReward + loginAct。

    - 新版(1840 新成长登录有礼)：{"loginAct": info["loginAct"]}，loginAct 由服务端 entry 下发
    - 老版(156 新版7天登陆)：{}，仅在确认新版异常时作备用
    服务端按 info.landingReward.day(0~8) 记录已领天数，每天只能领当天一档；
    day=7 时下一档才是第8天（莲子幻珠 101036007×1、妖元×3、攻击果×1、大灵魂药水×5）。
    """
    lr = info.get("landingReward")
    lr = lr if isinstance(lr, dict) else {}
    day = int(lr.get("day") or 0)
    if day >= 8:
        print("[登录有礼] 8天已全部领取（day=%d），本次跳过" % day)
        return
    act = int(info.get("loginAct") or 0)
    if legacy:
        payload = {}
        print("[登录有礼] 老版路由（不带 loginAct），当前已领 %d/8 天" % day)
    else:
        if act <= 0:
            print("[登录有礼] 服务端未下发 loginAct，无法走新版路由；可改用老版备用按钮")
            return
        payload = {"loginAct": act}
        print("[登录有礼] 新版路由 loginAct=%d，当前已领 %d/8 天" % (act, day))
    reply = flow.request("scene.activityHandler.getLandingReward", payload)
    if not isinstance(reply, dict):
        print("[登录有礼] 返回异常：%r" % (reply,))
        return
    if reply.get("code") != 200 or reply.get("error"):
        print("[登录有礼] 领取未成功：code=%s error=%s"
              % (reply.get("code"), reply.get("error")))
        return
    give = reply.get("give") or []
    print("[登录有礼] 第 %d 天领取成功：%s" % (
        day + 1,
        "、".join("%s×%s" % (g.get("subType"), g.get("count")) for g in give) or "无道具"))
    if isinstance(reply.get("landingReward"), dict):
        info["landingReward"] = reply["landingReward"]
    return reply


_NEW_PLAYER_TASK_CFG = None


def _new_player_tasks():
    """新手有礼配置（NewPlayerTask.json）：980xxx 任务 + 981001~981006 当天礼包。"""
    global _NEW_PLAYER_TASK_CFG
    if _NEW_PLAYER_TASK_CFG is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "cg_config_out_cg1_20261019_1", "NewPlayerTask.json")
        with open(path, encoding="utf-8") as f:
            _NEW_PLAYER_TASK_CFG = {int(k): v for k, v in json.load(f).items()}
    return _NEW_PLAYER_TASK_CFG


_STATUS_TXT = {1: "进行中", 2: "可领", 3: "已领"}


def claim_new_player_rewards(flow, info, claim=True):
    """新手有礼（活动173，第1~6天）：单任务奖励 + 当天全部完成的礼包。

    - 任务：scene.questHandler.commitQuest {"qId": 980xxx}，仅 status==2 可领
    - 礼包：981001~981006，当天任务全部完成后 status 才会变 2
    claim=False 只查询不领取。
    """
    cfg = _new_player_tasks()
    days = {}
    for tid, v in cfg.items():
        if "作废" in (v.get("name") or ""):
            continue  # 配置里保留但已作废的任务，不参与统计
        d = days.setdefault(v["belongDay"], {"tasks": [], "gift": None})
        if v["shopId"] == -1:
            d["tasks"].append((int(v["order"]), tid, v))
        else:
            d["gift"] = (tid, v)

    def fetch():
        r = flow.request("scene.questHandler.getQuestList", {})
        qs = (r.get("quest") if isinstance(r, dict) else None) or []
        return {int(q.get("id") or 0): q for q in qs}

    by_id = fetch()
    if not by_id:
        print("[新手有礼] 任务列表为空，本角色可能未开启该活动")
        return

    total_can = total_done = total_prog = total_absent = total_claimed = 0
    for day in sorted(days):
        d = days[day]
        can = done = prog = absent = 0
        tasks = sorted(d["tasks"])
        for _, tid, _v in tasks:
            q = by_id.get(tid)
            st = q.get("status") if q else None
            if st == 2:
                can += 1
            elif st == 3:
                done += 1
            elif st == 1:
                prog += 1
            else:
                absent += 1
        total_can += can
        total_done += done
        total_prog += prog
        total_absent += absent

        if claim:
            for _, tid, v in tasks:
                q = by_id.get(tid)
                if not q or q.get("status") != 2:
                    continue
                rr = flow.request("scene.questHandler.commitQuest", {"qId": tid})
                if isinstance(rr, dict) and rr.get("code") == 200 and not rr.get("error"):
                    total_claimed += 1
                    print("[新手有礼] day%d 任务「%s」领取成功" % (day, v.get("name")))
                else:
                    print("[新手有礼] day%d 任务「%s」领取失败：%s"
                          % (day, v.get("name"), rr))
            if can:
                by_id = fetch()  # 领完任务后刷新，礼包状态可能刚变为可领

        gid, gv = d["gift"]
        gst = (by_id.get(gid) or {}).get("status")
        if claim and gst == 2:
            rr = flow.request("scene.questHandler.commitQuest", {"qId": gid})
            if isinstance(rr, dict) and rr.get("code") == 200 and not rr.get("error"):
                total_claimed += 1
                print("[新手有礼] day%d 礼包领取成功（Reward %s）" % (day, gv.get("rewardId")))
                gst = 3
            else:
                print("[新手有礼] day%d 礼包领取失败：%s" % (day, rr))
        print("[新手有礼] day%d：任务 可领%d/已领%d/进行中%d/未下发%d | 礼包 %s" % (
            day, can, done, prog, absent,
            _STATUS_TXT.get(gst, "未下发") if gst != 3 else "已领"))
    print("[新手有礼] 汇总：任务可领%d 已领%d 进行中%d 未下发%d；本次领取%d 项" % (
        total_can, total_done, total_prog, total_absent, total_claimed))
    if not claim:
        print("[新手有礼] 查询模式，未做任何领取")


_WEEKEND_ONLINE_IDS = (960001, 960002, 960003, 960004, 960005, 960006)


def claim_weekend_online(flow, info, part='all'):
    """周末在线福利（活动230，周五/周六/周日开放）：在线时长领 buff/道具 + 累计5档礼包。

    part='buff' 只领 960001（在线0分钟双倍buff）；
    part='rest' 领 960002~960006（在线2/5/10/20分钟档 + 累计5档礼包）；
    part='all' 全领。
    进一步拆成两段是为了「我的日常」把 buff 提前、后几档放到庆典15分钟之后。
    领取统一 scene.questHandler.commitQuest {"qId": 960xxx}，仅 status==2 可领。
    """
    ids = {'buff': (960001,), 'rest': (960002, 960003, 960004, 960005, 960006)}.get(
        part, _WEEKEND_ONLINE_IDS)

    def fetch():
        r = flow.request("scene.questHandler.getQuestList", {})
        qs = (r.get("quest") if isinstance(r, dict) else None) or []
        return {int(q.get("id") or 0): q for q in qs}

    by_id = fetch()
    if not any(by_id.get(i) for i in ids):
        print("[周末在线] 当前无该活动任务（活动230仅周五/周六/周日开放）")
        return

    claimed = 0
    for tid in ids:
        q = fetch().get(tid)  # 每档前刷新：领完前5档后 960006 由 newQuest 补下发
        if not q or q.get("status") != 2:
            continue
        rr = flow.request("scene.questHandler.commitQuest", {"qId": tid})
        if isinstance(rr, dict) and rr.get("code") == 200 and not rr.get("error"):
            claimed += 1
            buff = [g for g in (rr.get("give") or []) if g.get("type") == "buff"]
            print("[周末在线] 第%d档领取成功%s" % (
                tid - 960000, "，双倍buff已激活" if tid == 960001 and buff else ""))
        else:
            print("[周末在线] 第%d档领取失败：%s" % (tid - 960000, rr))

    by_id = fetch()
    waiting = []
    for tid in ids:
        q = by_id.get(tid) or {}
        if q.get("status") == 1:
            waiting.append("第%d档进度%s" % (tid - 960000, q.get("progress") or {}))
    print("[周末在线] 本次领取 %d 档；未完成：%s" % (
        claimed, "；".join(waiting) if waiting else "无"))



# 成长挑战-通关主线任务：qId -> 主线关卡 mid（GrowthChallengeTask.json taskType=0, openModule=battle）
# 必须在 acceptQuest 之后重新通关才算数，旧通关记录不回溯。
_GROWTH_DUNGEON_TASKS = [
    (831001, 3, "昆仑宫"),
    (831002, 6, "天墉城"),
    (831003, 9, "玉英宫"),
    (831004, 12, "瑶池宫"),
    (831005, 15, "雷鼓台"),
    (831006, 18, "化世桥"),
    (831007, 21, "雷罚殿"),
    (831008, 24, "神霄府"),
    (831009, 27, "云上界"),
    (831010, 30, "积雪泉"),
    (831011, 33, "重日殿"),
    (831012, 36, "紫微宫"),
    (831013, 39, "千诵梵音殿"),
    (831014, 42, "瑞光圣泉"),
    (831015, 45, "鲲腹莲池"),
    (831016, 48, "东极妙严宫"),
]


def _growth_quest_map(flow):
    """读取当前任务列表，返回 {qId: quest} 仅含成长挑战通关主线任务。"""
    out = {}
    try:
        r = flow.request("scene.questHandler.getQuestList", {})
        if not isinstance(r, dict) or r.get("code") != 200 or r.get("error"):
            print("[成长通关] 读取任务列表失败: %s" % (r.get("error") if isinstance(r, dict) else r))
            return out
        for q in (r.get("quest") or []):
            qid = q.get("id")
            if isinstance(qid, int) and any(t[0] == qid for t in _GROWTH_DUNGEON_TASKS):
                out[qid] = q
    except Exception as e:
        print("[成长通关] 读取任务列表异常: %s" % e)
    return out


def _clear_main_stage(flow, mid, name):
    """快速通关一个主线关卡（create + finish win=1），不拾取掉落。"""
    client_rnd = random.randint(0, 9999)
    created = flow.request("scene.copyHandler.createSinglePlayerCopy",
                           {"mid": mid, "rnd": client_rnd})
    if not isinstance(created, dict) or created.get("error") or created.get("code") != 200:
        err = created.get("error") if isinstance(created, dict) else str(created)
        print("[成长通关] %s 创建副本失败: %s" % (name, err))
        return False
    time.sleep(0.5)
    finished = flow.request("scene.copyHandler.finishSingleCopy",
                            {"win": 1, "rnd": int(created["rnd"]) ^ client_rnd, "star": 3})
    if not isinstance(finished, dict) or finished.get("error") or finished.get("code") != 200:
        err = finished.get("error") if isinstance(finished, dict) else str(finished)
        print("[成长通关] %s 结算失败: %s" % (name, err))
        return False
    return True


_USE_IDS = object()  # 默认：按 *_IDS 勾选过滤；显式传 None 表示该类别全部执行（一键完成用）


def claim_growth_dungeon_tasks(flow, info, qids=_USE_IDS):
    """成长挑战-通关主线任务：接取→通关主线→领奖。

    任务 831001~831016，每个任务对应一个主线关卡。状态机：
      0/不在列表 → acceptQuest；1(已接取) → 通关后等同步；2(可领) → commitQuest；3(已领) → 跳过。
    """
    dungeon = info.get("dungeon") or {}
    done, skipped = 0, 0
    for qid, mid, name in _growth_pick(_GROWTH_DUNGEON_TASKS,
                                       RUN_GROWTH_DUNGEON_IDS if qids is _USE_IDS else qids):
        # 前置关卡未通关则该关卡未解锁，跳过
        if mid > 1 and not int((dungeon.get(str(mid - 1)) or {}).get("passNum") or 0):
            print("[成长通关] %s(mid=%s) 前置关卡未通关，跳过" % (name, mid))
            skipped += 1
            continue
        qmap = _growth_quest_map(flow)
        quest = qmap.get(qid)
        status = quest.get("status") if quest else 0
        if status == 3:
            continue  # 已领取
        if status in (0, None) or not quest:
            print("[成长通关] 接取任务 %s（%s）" % (qid, name))
            acc = flow.request("scene.questHandler.acceptQuest", {"qId": qid})
            if not isinstance(acc, dict):
                print("[成长通关] %s accept 返回异常: %s" % (name, acc))
                continue
            if acc.get("code") != 200 and acc.get("error") not in (None, "任务已接受"):
                print("[成长通关] %s 接取失败: %s" % (name, acc.get("error") or acc.get("code")))
                continue
            time.sleep(0.5)
            qmap = _growth_quest_map(flow)
            quest = qmap.get(qid)
            if quest is None:
                print("[成长通关] 任务 %s 接取后未被服务端下发，判定该角色不支持成长挑战"
                      "（等级超出18级或活动已结束），中止以免白耗副本次数" % qid)
                return
            status = quest.get("status")
        if status == 1:
            print("[成长通关] 通关 %s(mid=%s) 完成任务" % (name, mid))
            if not _clear_main_stage(flow, mid, name):
                continue
            # 服务端需要时间把通关记录同步到任务进度
            time.sleep(1.5)
            qmap = _growth_quest_map(flow)
            quest = qmap.get(qid)
            status = quest.get("status") if quest else 1
        if status == 2:
            print("[成长通关] 领取奖励 %s（%s）" % (qid, name))
            reply = flow.request("scene.questHandler.commitQuest", {"qId": qid})
            if not isinstance(reply, dict):
                print("[成长通关] %s commit 返回异常: %s" % (name, reply))
                continue
            if reply.get("code") != 200 or reply.get("error"):
                print("[成长通关] %s 领奖失败: %s" % (name, reply.get("error") or reply.get("code")))
                continue
            give = reply.get("give") or []
            items = ", ".join("%s:%s×%s" % (g.get("type"), g.get("subType"), g.get("count"))
                              for g in give if isinstance(g, dict)) or "无"
            print("[成长通关] %s 领奖成功: %s" % (name, items))
            for key in ("everyDaySetting", "roleBuff"):
                if isinstance(reply.get(key), dict) and isinstance(info.get(key), dict):
                    info[key].update(reply[key])
            done += 1
            time.sleep(SLEEP)
        else:
            print("[成长通关] %s 当前状态=%s，暂不可领奖" % (name, status))
    print("[成长通关] 完成 %d 个，跳过 %d 个" % (done, skipped))
    # 至尊特权 3600 点券：默认不买，只能走 GUI 的“购买至尊特权”按钮 + 口令确认锁
    print("[成长通关] 提示：至尊特权需3600点券（scene.activityHandler.buyGrowthChallenge），"
          "默认不自动购买；需要时用成长挑战页的“购买至尊特权”按钮（需输入口令）")


# ---------------- 成长挑战（新手活动）总控 ----------------
_CFG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "cg_config_out_cg1_20261019_1")

# 十绝阵任务：qId -> 要求累计通关次数（GrowthChallengeTask.json 831029~831034）
_GROWTH_HALO_TASKS = [(831029, 1), (831030, 3), (831031, 7), (831032, 15),
                      (831033, 30), (831034, 60)]

# 蛮荒任务：qId -> 单人mid（多人mid+10000），每个要求通关5次
_GROWTH_MANHUANG_TASKS = [
    (831035, 1410101, "九江穴"),
    (831036, 1410102, "瑶碧山"),
    (831037, 1410103, "太山"),
    (831038, 1410104, "鹿吴之山"),
]

# 炼丹任务：每品级有 6 种丹药（热血/魔泉/勇武/铁骨/永恒/辉煌），任务认任意一种
# （GrowthChallengeTask.json 的 targetId "3001;3002;...;3006"），依次挑丹引齐全的那个
_GROWTH_DAN_TASKS = [(831039 + i, [3001 + 6 * i + j for j in range(6)], "%d品丹药" % (i + 1))
                     for i in range(9)]

_ALL_GROWTH_QUEST_IDS = list(range(831001, 831048))  # 831001~831047 共47个（839001每日buff单独处理）


def _load_cfg(name):
    with open(os.path.join(_CFG_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


def _growth_pick(items, qids):
    """按 qId 列表筛选任务；None=全部，空列表=一个也不执行。"""
    if qids is None:
        return list(items)
    want = {int(q) for q in qids}
    out = []
    for it in items:
        qid = int(it[0]) if isinstance(it, (tuple, list)) else int(it)
        if qid in want:
            out.append(it)
    return out


def _growth_quest_status(flow, qids):
    """拉一次任务列表，返回 {qId: quest}。"""
    out = {}
    try:
        r = flow.request("scene.questHandler.getQuestList", {})
        if not isinstance(r, dict) or r.get("code") != 200:
            return out
        for q in (r.get("quest") or []):
            # 服务端有的号返回 id 为字符串、有的为整数，统一转 int 再比对
            try:
                qid = int(q.get("id"))
            except (TypeError, ValueError):
                continue
            if qid in qids:
                out[qid] = q
    except Exception as e:
        print("[成长挑战] 读取任务列表异常: %s" % e)
    return out


def _growth_accept(flow, qid, name):
    """接取一个成长挑战任务；已接受视为成功。"""
    a = flow.request("scene.questHandler.acceptQuest", {"qId": qid})
    if not isinstance(a, dict):
        print("[成长挑战] %s accept 异常: %s" % (name, a))
        return False
    if a.get("code") == 200 or a.get("error") in (None, "任务已接受"):
        return True
    print("[成长挑战] %s 接取失败: %s" % (name, a.get("error") or a.get("code")))
    return False


def _growth_commit(flow, info, qid, name):
    """领取成长挑战任务奖励。"""
    r = flow.request("scene.questHandler.commitQuest", {"qId": qid})
    if not isinstance(r, dict) or r.get("error") or r.get("code") != 200:
        err = r.get("error") if isinstance(r, dict) else r
        print("[成长挑战] %s 领奖失败: %s" % (name, err))
        return False
    give = r.get("give") or []
    items = ", ".join("%s:%s×%s" % (g.get("type"), g.get("subType"), g.get("count"))
                      for g in give if isinstance(g, dict)) or "无"
    print("[成长挑战] %s 领奖成功: %s" % (name, items))
    for key in ("everyDaySetting", "roleBuff", "growthChallenge"):
        if isinstance(r.get(key), dict) and isinstance(info.get(key), dict):
            info[key].update(r[key])
    return True


def accept_all_growth_quests(flow, info, qids=_USE_IDS):
    """把成长挑战 47 个任务全部接取（接取不消耗资源；祖巫只接不打卡）。"""
    cur = _growth_quest_status(flow, set(_ALL_GROWTH_QUEST_IDS))
    newly = 0
    for qid in _growth_pick(_ALL_GROWTH_QUEST_IDS,
                            RUN_GROWTH_ACCEPT_IDS if qids is _USE_IDS else qids):
        if qid in cur:
            continue
        if _growth_accept(flow, qid, str(qid)):
            newly += 1
            time.sleep(0.3)
    print("[成长挑战] 接取完成：本次新接 %d 个（任务共 %d 个）"
          % (newly, len(_ALL_GROWTH_QUEST_IDS)))


def claim_growth_manhuang_tasks(flow, info, qids=_USE_IDS):
    """蛮荒任务 831035~038：接取→单人通关5次→领奖（不领共享宝箱，不消耗宝箱次数）。"""
    for qid, mid, name in _growth_pick(_GROWTH_MANHUANG_TASKS,
                                       RUN_GROWTH_MANHUANG_IDS if qids is _USE_IDS else qids):
        quest = _growth_quest_status(flow, {qid}).get(qid)
        status = quest.get("status") if quest else 0
        if status == 3:
            continue
        if status in (0, None):
            if not _growth_accept(flow, qid, name):
                continue
            time.sleep(0.5)
        for i in range(5):
            quest = _growth_quest_status(flow, {qid}).get(qid) or {}
            if quest.get("status") == 2:
                break
            prog = quest.get("progress") or {}
            cur = int(list(prog.values())[0]) if prog else 0
            if cur >= 5:
                break
            my_rnd = random.randint(0, 9999)
            r1 = flow.request("scene.copyHandler.createSinglePlayerCopy",
                              {"mid": mid, "rnd": my_rnd})
            if not isinstance(r1, dict) or r1.get("error") or r1.get("code") != 200:
                print("[成长蛮荒] %s 创建失败: %s" % (name, r1))
                break
            r2 = flow.request("scene.copyHandler.finishSingleCopy",
                              {"win": 1, "rnd": int(r1["rnd"]) ^ my_rnd, "star": 3})
            if not isinstance(r2, dict) or r2.get("error") or r2.get("code") != 200:
                print("[成长蛮荒] %s 结算失败: %s" % (name, r2))
                break
            print("[成长蛮荒] %s 第%d次通关" % (name, i + 1))
            time.sleep(1.2)
        time.sleep(1.0)
        quest = _growth_quest_status(flow, {qid}).get(qid) or {}
        if quest.get("status") == 2:
            _growth_commit(flow, info, qid, name)


def claim_growth_halo_tasks(flow, info):
    """十绝阵任务 831029~034：按剩余奖励次数补打并领奖（次数不足则留到明天）。"""
    try:
        from halo_solo import run_halo_solo
    except Exception as e:
        print("[成长十绝阵] 加载 halo_solo 失败: %s" % e)
        return
    g = flow.request("scene.haloHandler.getDungeonId", {})
    did = g.get("dungeonId") if isinstance(g, dict) else None
    if did is None:
        print("[成长十绝阵] 未取到 dungeonId: %s"
              % (g.get("error") if isinstance(g, dict) else g))
        return
    did = int(did)
    remain = int((info.get("halo") or {}).get("haloRewardCnt") or 0)
    print("[成长十绝阵] 当前关卡 %s，奖励次数剩余 %s" % (did, remain))
    for qid, need in _growth_pick(_GROWTH_HALO_TASKS, RUN_GROWTH_HALO_IDS):
        quest = _growth_quest_status(flow, {qid}).get(qid)
        status = quest.get("status") if quest else 0
        if status == 3:
            continue
        if status in (0, None):
            if not _growth_accept(flow, qid, str(qid)):
                continue
            time.sleep(0.5)
        while remain > 0:
            quest = _growth_quest_status(flow, {qid}).get(qid) or {}
            if quest.get("status") == 2:
                break
            prog = quest.get("progress") or {}
            cur = int(list(prog.values())[0]) if prog else 0
            if cur >= need:
                break
            if not run_halo_solo(flow, info, did, RECORD_INDEX, HALO_TARGET_SCORE):
                print("[成长十绝阵] 挑战失败，本次停止")
                return
            remain -= 1
            time.sleep(SLEEP)
        quest = _growth_quest_status(flow, {qid}).get(qid) or {}
        if quest.get("status") == 2:
            _growth_commit(flow, info, qid, "%s(%s次)" % (qid, need))
        elif remain <= 0:
            print("[成长十绝阵] %s 需%s次，今日次数已用完，留待明天" % (qid, need))
            break


def _bag_counts(info):
    """背包物品数量 {itemId: count}。"""
    out = {}
    for k, v in ((info.get("bag") or {}).get("item") or {}).items():
        try:
            out[int(k)] = int(v.get("count") if isinstance(v, dict) else v)
        except Exception:
            continue
    return out


def _pick_exchange_source(prop, bag, target):
    """找一个可用于置换的材料：同大类(木/矿/布)且等级高于目标、库存充足。"""
    t = prop.get(str(target)) or {}
    ttype, tlevel = t.get("type"), t.get("level") or 0
    if ttype is None:
        return None
    best = None
    for k, v in prop.items():
        if v.get("type") != ttype:
            continue
        kid = int(k)
        if (v.get("level") or 0) <= tlevel or bag.get(kid, 0) <= 0:
            continue
        if best is None or bag.get(kid, 0) > bag.get(best, 0):
            best = kid
    return best


def claim_growth_dan_tasks(flow, info):
    """炼丹任务 831039~047：缺基础材料时自动用同大类高等级材料置换，然后合成→领奖。"""
    try:
        comp = _load_cfg("Compose.json")
        prop = _load_cfg("PropExchange.json")
    except Exception as e:
        print("[成长炼丹] 读取配方失败: %s" % e)
        return
    bag = _bag_counts(info)
    for qid, cids, label in _growth_pick(_GROWTH_DAN_TASKS, RUN_GROWTH_DAN_IDS):
        quest = _growth_quest_status(flow, {qid}).get(qid)
        status = quest.get("status") if quest else 0
        if status == 3:
            continue
        # 依次挑第一个“丹引齐全”的配方（同品级 6 种丹药任务都认）
        chosen = None
        miss_all = []
        for cid in cids:
            cfg = comp.get(str(cid)) or {}
            subs = [int(x) for x in str(cfg.get("consume_subType") or "").split(",") if x]
            cnts = [int(x) for x in str(cfg.get("consume_count") or "").split(",") if x]
            need = list(zip(subs, cnts))
            if not need:
                continue
            dan_yin = [(i, n) for i, n in need
                       if not str(i).startswith(("1010020", "1010030", "1010040"))]
            missing = [(i, n, bag.get(i, 0)) for i, n in dan_yin if bag.get(i, 0) < n]
            if missing:
                for m in missing:
                    if m not in miss_all:
                        miss_all.append(m)
                continue
            chosen = (cid, need)
            break
        if chosen is None:
            print("[成长炼丹] %s 六种丹药均缺丹引（不可置换），跳过；缺 %s" % (label, miss_all))
            continue
        cid, need = chosen
        if status in (0, None):
            if not _growth_accept(flow, qid, label):
                continue
            time.sleep(0.4)
        ok = True
        for i, n in need:
            gap = n - bag.get(i, 0)
            while gap > 0:
                src = _pick_exchange_source(prop, bag, i)
                if src is None:
                    print("[成长炼丹] %s 材料 %s 缺 %s 且无可置换来源" % (label, i, gap))
                    ok = False
                    break
                amt = min(gap, bag.get(src, 0))
                r = flow.request("scene.itemHandler.propExchange",
                                 {"tId": i, "sId": src, "num": amt})
                if not isinstance(r, dict) or r.get("error") or r.get("code") != 200:
                    print("[成长炼丹] 置换 %s×%s→%s 失败: %s"
                          % (src, amt, i, r.get("error") if isinstance(r, dict) else r))
                    ok = False
                    break
                bag[src] -= amt
                bag[i] = bag.get(i, 0) + amt
                gap -= amt
                print("[成长炼丹] 置换 %s×%s → %s×%s" % (src, amt, i, amt))
                time.sleep(0.5)
            if not ok:
                break
        if not ok:
            continue
        r = flow.request("scene.itemHandler.compose", {"composeId": cid})
        if not isinstance(r, dict) or r.get("error") or r.get("code") != 200:
            print("[成长炼丹] %s 合成失败: %s"
                  % (label, r.get("error") if isinstance(r, dict) else r))
            continue
        for i, n in need:
            bag[i] = bag.get(i, 0) - n
        print("[成长炼丹] %s 合成成功（composeId=%s）" % (label, cid))
        time.sleep(1.5)
        quest = _growth_quest_status(flow, {qid}).get(qid) or {}
        if quest.get("status") == 2:
            _growth_commit(flow, info, qid, label)
        else:
            print("[成长炼丹] %s 任务状态=%s，未达可领" % (label, quest.get("status")))


def claim_growth_point_rewards(flow, info):
    """成长挑战积分档位奖励：1001~1018；至尊档 2001~ 需至尊等级 lv>=2。"""
    try:
        rew = _load_cfg("GrowthChallengeReward.json")
    except Exception as e:
        print("[成长积分] 读取奖励配置失败: %s" % e)
        return
    gc = info.get("growthChallenge") or {}
    # 服务端常常不下发 exp（实测槽6只有一个 lv 和 rewards），此时不做积分预筛，
    # 逐个尝试未领档位，由服务端判断积分是否足够（不足会返回“积分不足”，不扣任何东西）。
    exp_raw = gc.get("exp")
    exp = int(exp_raw or 0)
    lv = int(gc.get("lv") or 1)
    got = gc.get("rewards") or {}
    print("[成长积分] 当前积分 %s，至尊等级 %s，已领 %s"
          % (exp if exp_raw is not None else "未下发", lv, sorted(got.keys())))
    point_ids = None if RUN_GROWTH_POINT_IDS is None else {int(q) for q in RUN_GROWTH_POINT_IDS}
    for k in sorted(rew, key=int):
        if point_ids is not None and int(k) not in point_ids:
            continue
        v = rew[k]
        need = int(v.get("growthMoneney") or 0)
        if str(k) in got:
            continue
        if exp_raw is not None and exp < need:
            continue
        if v.get("levelType") == 2 and lv < 2:
            continue
        r = flow.request("scene.activityHandler.getGrowthChallenge", {"id": int(k)})
        if not isinstance(r, dict) or r.get("error") or r.get("code") != 200:
            print("[成长积分] 档%s 跳过: %s"
                  % (k, r.get("error") if isinstance(r, dict) else r))
            continue
        give = r.get("give") or []
        print("[成长积分] 档%s(%s分) 领取成功: %s"
              % (k, need, ", ".join("%s:%s×%s" % (g.get("type"), g.get("subType"), g.get("count"))
                                    for g in give if isinstance(g, dict)) or "无"))
        if isinstance(r.get("growthChallenge"), dict) and isinstance(info.get("growthChallenge"), dict):
            info["growthChallenge"].update(r["growthChallenge"])
            got = info["growthChallenge"].get("rewards") or {}


def claim_growth_all_ready(flow, info):
    """一键领取：只提交已完成(status=2)的成长挑战任务并领积分档位。

    不接取任务、不通关副本、不消耗任何次数，可反复执行。
    """
    print("\n=== 成长挑战·一键领取已完成任务 ===")
    qmap = _growth_quest_status(flow, set(_ALL_GROWTH_QUEST_IDS))
    claimed = 0
    for qid in _ALL_GROWTH_QUEST_IDS:
        q = qmap.get(qid) or {}
        if q.get("status") != 2:
            continue
        if _growth_commit(flow, info, qid, str(qid)):
            claimed += 1
        time.sleep(SLEEP)
    print("[成长挑战] 一键领取：共领到 %d 个任务奖励" % claimed)
    claim_growth_point_rewards(flow, info)


def buy_growth_vip(flow, info):
    """购买成长挑战至尊特权：scene.activityHandler.buyGrowthChallenge（3600点券）。

    确认锁：GROWTH_VIP_CONFIRM 必须与口令完全一致，否则直接拒绝；已开通则不重复购买。
    购买前核对点券余额，购买后回读余额与至尊等级，不做任何重试。
    """
    phrase = "确认购买至尊特权"
    gc = info.get("growthChallenge") or {}
    if int(gc.get("lv") or 1) >= 2:
        print("[成长特权] 当前已是至尊等级 %s，无需再买" % gc.get("lv"))
        return False
    if str(GROWTH_VIP_CONFIRM) != phrase:
        print("[成长特权] 确认锁未打开（口令不符），已取消购买")
        return False
    reply = flow.request("connector.roleHandler.getUserInfo", {})
    ticket = None
    if isinstance(reply, dict):
        ticket = (reply.get("user") or {}).get("ticket")
    if ticket is None:
        print("[成长特权] 读取点券余额失败，已取消购买")
        return False
    ticket = int(ticket)
    if ticket < GROWTH_VIP_COST:
        print("[成长特权] 点券不足：余额 %s，需要 %s，已取消" % (ticket, GROWTH_VIP_COST))
        return False
    # 二级密码：客户端对所有请求都把密码放在 param.password，502=密码错误
    pwd = os.environ.get('ZM5_GROWTH_VIP_PASSWORD', '')
    payload = {'password': pwd} if pwd else {}
    print("[成长特权] 点券余额 %s，开始购买至尊特权（%s 点券%s）..."
          % (ticket, GROWTH_VIP_COST, "，已带二级密码" if pwd else "，未带二级密码"))
    r = flow.request("scene.activityHandler.buyGrowthChallenge", payload)
    if isinstance(r, dict) and r.get("code") == 502:
        print("[成长特权] 二级密码错误或该账号需要二级密码（code=502），已停止，不会重试")
        return False
    if not isinstance(r, dict) or r.get("error") or r.get("code") not in (None, 200):
        print("[成长特权] 购买失败: %s" % (r.get("error") if isinstance(r, dict) else r))
        return False
    if isinstance(r.get("growthChallenge"), dict) and isinstance(info.get("growthChallenge"), dict):
        info["growthChallenge"].update(r["growthChallenge"])
    after = flow.request("connector.roleHandler.getUserInfo", {})
    left = (after.get("user") or {}).get("ticket") if isinstance(after, dict) else None
    lv2 = int((info.get("growthChallenge") or {}).get("lv") or 1)
    spent = "" if left is None else "，实际扣 %s" % (ticket - int(left))
    print("[成长特权] 购买完成：至尊等级 %s，点券 %s → %s%s"
          % (lv2, ticket, left if left is not None else "?", spent))
    return lv2 >= 2


_FASHION_SHOP_CACHE = None


def fashion_shop_items():
    """玉珠商店商品：Shop.json 中 consume_subType 含 dailyTaskMoney 的条目。

    返回 [(shopId, 名称, 单价玉珠, 限购上限)]，限购 -1 表示不限购。
    """
    global _FASHION_SHOP_CACHE
    if _FASHION_SHOP_CACHE is None:
        try:
            with open(os.path.join(_CFG_DIR, "Shop.json"), encoding="utf-8-sig") as f:
                shop = json.load(f)
        except Exception as exc:
            print("[玉珠商店] 读取 Shop.json 失败：%s" % exc)
            shop = {}
        items = []
        for row in shop.values():
            if "dailyTaskMoney" not in str(row.get("consume_subType") or ""):
                continue
            try:
                sid = int(row.get("id"))
                cost = int(str(row.get("consume_count") or "0").split(",")[0])
                cap = int(row.get("purchaseMaxNum") or -1)
            except (TypeError, ValueError):
                continue
            items.append((sid, str(row.get("name") or sid), cost, cap))
        _FASHION_SHOP_CACHE = sorted(items)
    return _FASHION_SHOP_CACHE


def claim_fashion_rewards(flow, info):
    """永久时装：签到 + 已完成每日任务领奖 + 阶段奖励（复用 new_player_rewards）。"""
    from new_player_rewards import run as run_new_player_rewards
    run_new_player_rewards(flow, info, RECORD_INDEX, 'fashion')


def claim_fashion_signin(flow, info):
    """永久时装：仅每日签到（scene.dailyTaskHandler.dailyTaskSignIn）。"""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    print("\n=== 永久时装·签到 ===")
    state = info.get('dailyTaskSpecial') or {}
    if not state.get('startTime'):
        print("[永久时装] 当前存档无该活动，跳过")
        return
    tz = _tz(_td(hours=8))
    last = int(state.get('lastSignInTime') or 0)
    if last and _dt.fromtimestamp(last / 1000, tz).date() >= _dt.now(tz).date():
        print("[永久时装] 今日已签到（%s），跳过"
              % _dt.fromtimestamp(last / 1000, tz).strftime('%Y-%m-%d %H:%M'))
        return
    r = flow.request('scene.dailyTaskHandler.dailyTaskSignIn', {})
    if not isinstance(r, dict) or r.get('error') or r.get('code') != 200:
        print("[永久时装] 签到失败：%s" % (r.get('error') if isinstance(r, dict) else r))
        return
    if r.get('consume'):
        print("[永久时装] 签到出现非预期消耗：%s" % r.get('consume'))
    print("[永久时装] 签到成功：%s" % json.dumps(r.get('give') or [], ensure_ascii=False))


def claim_fashion_online(flow, info):
    """永久时装：仅在线 20 分钟任务 970002 领奖（不挂机等待）。"""
    print("\n=== 永久时装·在线任务 970002 ===")
    reply = flow.request('scene.questHandler.getQuestList', {})
    if not isinstance(reply, dict) or reply.get('code') != 200:
        print("[永久时装] 任务列表读取失败：%s"
              % (reply.get('error') if isinstance(reply, dict) else reply))
        return
    target = 1200
    for q in reply.get('quest') or []:
        if str(q.get('id')) != '970002':
            continue
        stored = int((q.get('progress') or {}).get('0', 0) or 0)
        status = int(q.get('status') or 0)
        print("[永久时装] 在线任务 进度 %d/%d 秒，status=%d" % (stored, target, status))
        if status == 3:
            print("[永久时装] 在线任务今日已领取，跳过")
            return
        if status != 2 and stored < target:
            print("[永久时装] 未满 20 分钟，不等待挂机，跳过")
            return
        r = flow.request('scene.questHandler.commitQuest', {'qId': 970002})
        if not isinstance(r, dict) or r.get('error') or r.get('code') != 200:
            print("[永久时装] 在线任务领奖失败：%s"
                  % (r.get('error') if isinstance(r, dict) else r))
            return
        print("[永久时装] 在线任务领奖成功：%s"
              % json.dumps(r.get('give') or [], ensure_ascii=False))
        return
    print("[永久时装] 未找到在线任务 970002（未开放或已领取）")


def buy_fashion_shop(flow, info, shop_ids=None, password=None):
    """玉珠商店购买：只消耗玉珠，严格按 purchaseMaxNum 限购，余额不足即跳过。

    shop_ids: None/空=不买；set={sid,...}=各买1件；dict={sid: 数量}=按数量买（受限购与余额约束）。
    服务端要求二级密码（缺失返回 code=502），密码只从环境变量读取一次，不落盘。
    """
    print("\n=== 永久时装·玉珠商店 ===")
    if password is None:
        password = os.environ.pop('ZM5_FASHION_SHOP_PASSWORD', '') or ''
    money = int((info.get('dailyTaskSpecial') or {}).get('dailyTaskMoney') or 0)
    print("[玉珠商店] 当前玉珠 %d，%s" % (money, "已带二级密码" if password else "未带二级密码"))
    bought = 0
    for sid, name, cost, cap in fashion_shop_items():
        if isinstance(shop_ids, dict):
            want = int(shop_ids.get(sid) or 0)
        elif shop_ids is None:
            want = 0
        else:
            want = 1 if sid in shop_ids else 0
        if want <= 0 or cost <= 0:
            continue
        already = int(((info.get('shop') or {}).get(str(sid)) or {}).get('buyCount') or 0)
        remain = 999 if cap < 0 else cap - already
        if remain <= 0:
            print("[玉珠商店] %s %s 已达限购 %d，跳过" % (sid, name, cap))
            continue
        n = min(want, remain, money // cost)
        if n <= 0:
            print("[玉珠商店] %s %s 玉珠不足（单价 %d，余 %d），跳过" % (sid, name, cost, money))
            continue
        r = flow.request('scene.shopHandler.buy',
                         {'shopId': sid, 'count': n, 'password': password})
        if not isinstance(r, dict) or r.get('error') or r.get('code') != 200:
            print("[玉珠商店] %s %s 购买失败：%s"
                  % (sid, name, r.get('error') if isinstance(r, dict) else r))
            if isinstance(r, dict) and r.get('code') == 502:
                print("[玉珠商店] 服务器要求正确的二级密码，已停止，不会重试")
                return
            continue
        money -= cost * n
        bought += n
        print("[玉珠商店] %s %s×%d 成功，剩余玉珠 %d" % (sid, name, n, money))
        time.sleep(SLEEP)
    print("[玉珠商店] 本次共购买 %d 件" % bought)


def run_growth_challenge(flow, info):
    """成长挑战（新手活动）一次性执行全部环节（GUI 用子标签分别执行，不经过此函数）。

    祖巫任务只接取不打卡（有开放时段限制，按需用 world_boss.py 单独打）。
    至尊特权 3600 点券默认不买，只能走 GUI 按钮 + 口令确认锁（buy_growth_vip）。
    """
    print("\n=== 成长挑战（新手活动）===")
    accept_all_growth_quests(flow, info)
    claim_growth_dungeon_tasks(flow, info)
    claim_growth_manhuang_tasks(flow, info)
    claim_growth_halo_tasks(flow, info)
    claim_growth_dan_tasks(flow, info)
    claim_growth_point_rewards(flow, info)


def do_devote(flow):
    for tid in DEVOTE_TIERS:
        for _ in range(MAX_TIMES):
            r = flow.request("scene.leagueHandler.leagueDevote", {"devoteId": tid})
            err = r.get("error") if isinstance(r, dict) else None
            if err:
                print("[贡献] 档%s 停止: %s" % (tid, err)); break
            print("[贡献] 档%s 成功: %s" % (tid, r.get("give")))
            time.sleep(SLEEP)


def _is_money_err(r):
    """是否命中点券/ticket/元宝等付费扣费错误(命中即停, 绝不静默扣费)。"""
    if not isinstance(r, dict):
        return False
    err = r.get("error")
    return err is not None and any(h in str(err) for h in ("点券", "ticket", "票", "元宝", "支付", "扣费"))


def signup_arena(flow, handler="arena"):
    """竞技场/斗宠报名：本周未报名才发送一次 applyFor；已报名不重发。"""
    import arena_registration
    label = arena_registration.LABELS[handler]
    info = arena_registration.entry_info(flow, RECORD_INDEX)
    if handler == 'petArena' and not (info.get('petTeam') or []):
        print("[%s] 斗宠阵容未设置（请先在游戏内设置斗宠阵容），跳过报名" % label)
        return
    arena_registration.ensure(flow, handler, label, info=info)


def battle_arena(flow, handler="arena", label="竞技场", max_rounds=None, info=None):
    """竞技场/斗宠大会: 不用扫荡, 走"创建战斗->立即结算"快速通关。
    每日免费次数 = Challenge.jjcChallengeNum 按星期(10;5;5;5;5;10;10,
    顺序为 周日~周六: 周日10/周一5/周二5/周三5/周四5/周五10/周六10, 即周567=10)。
    预检: 用 getArenaInfo 的 jjcChallengeNum 当天值做免费上限;
    免费段只调 beginArenaBattle/endArenaBattle, 付费续战仅在开关启用后执行。
    开打前按客户端路由补报名（周五16点~周日22点），斗宠未设阵容则跳过。"""
    import arena_registration
    if info is None:
        info = arena_registration.entry_info(flow)
    if handler == 'petArena' and not (info.get('petTeam') or []):
        print("[%s] 斗宠阵容未设置（请先在游戏内设置斗宠阵容），跳过" % label)
        return
    if not arena_registration.ensure(flow, handler, label, info=info,
                                     require_registration=False):
        print("[%s] 报名未确认且无法继续，跳过对战" % label)
        return
    home = flow.request("scene.%sHandler.getArenaInfo" % handler, {})
    if not isinstance(home, dict) or home.get("error"):
        print("[%s] 读取竞技场信息失败: %s" % (label, home))
        return
    mode = ARENA_MODE if handler == "arena" else PET_ARENA_MODE
    prefix = 'ARENA' if handler == 'arena' else 'PET_ARENA'
    from arena_targets import wait_seconds
    battle_wait = wait_seconds(globals()[prefix + '_BATTLE_WAIT'])
    round_wait = wait_seconds(globals()[prefix + '_ROUND_WAIT'])
    if mode in ('rank_highest', 'specified', 'rank_random', 'borrowed'):
        from arena_targets import run
        prefix = 'ARENA' if handler == 'arena' else 'PET_ARENA'
        planned = globals()[prefix + '_TARGET_ROUNDS']
        if max_rounds is not None:
            # 外部调用只能进一步收紧局数，不能突破5/10配置。
            if int(max_rounds) < int(planned):
                print('[%s] 新模式请在界面选择5局或10局；外部上限不足，停止' % label)
                return
        return run(flow, handler, RECORD_INDEX, mode,
                   globals()[prefix + '_TARGET_UID'],
                   globals()[prefix + ('_TARGET_R_NUMBER' if globals()[prefix + '_TARGET_INPUT'] == 'r_number' else '_TARGET_SLOT')], planned,
                   confirmation=json.loads(os.environ.get('ZM5_ARENA_TARGET_CONFIRMATIONS', '{}')).get(handler),
                   top_n=globals()[prefix + '_TOP_N'], battle_wait=battle_wait, round_wait=round_wait,
                   target_input=globals()[prefix + '_TARGET_INPUT'], explicit_rid=globals()[prefix + '_TARGET_RID'])
    import datetime
    recs = home.get("recommend", [])
    if not recs:
        print("[%s] 无推荐对手" % label); return
    mode = (ARENA_MODE if handler == "arena" else PET_ARENA_MODE)
    mode = mode if mode in ARENA_MODES else "fixed"
    chosen = choose_opponent(recs,handler,mode)
    rid = chosen['rid']
    cfg = str(home.get("jjcChallengeNum") or "10;5;5;5;5;10;10").split(";")
    # 配置按 周日~周六 排列: index0=周日。datetime.weekday(): 周一=0, 周日=6 → (w+1)%7
    limit = int(cfg[(datetime.datetime.now().weekday() + 1) % len(cfg)])
    print("[%s] %s, 今日免费挑战上限 %d 次(不扫荡, 创建战斗快速通关)"
          % (label, "固定对手 %s" % rid if mode == "fixed" else {'refresh':'每场刷新随机选择','highest':'每场刷新选最高战力','lowest':'每场刷新选最低战力'}[mode], limit))
    n = 0
    free_stop = ""  # 免费段停止原因(用于判断是否进入点券续战)

    def _req(route, body):
        """请求, 遇"请勿频繁请求"限流等待重试(最多10次/共约30秒), 其它错误原样返回。"""
        for _ in range(10):
            r = flow.request(route, body)
            err = r.get("error") if isinstance(r, dict) else None
            if err and "频繁" in str(err):
                time.sleep(3); continue
            return r
        return r

    previous_rid = None
    planned_rounds = limit if max_rounds is None else min(limit,max(0,int(max_rounds)))
    for round_index in range(planned_rounds):
        if mode != "fixed" and round_index:
            home = _req("scene.%sHandler.getArenaInfo" % handler, {})
            if not isinstance(home, dict) or home.get("error"):
                print("[%s] 刷新推荐对手失败: %s" % (label, home)); break
            recs = [r for r in home.get("recommend", []) if r.get("rid")]
            if not recs:
                print("[%s] 刷新后无推荐对手, 停止" % label); break
            chosen = choose_opponent(recs,handler,mode,previous_rid)
            rid = chosen['rid']
        print("[%s] 第%d场对手: %s" % (label, round_index + 1, rid))
        if mode in ('highest','lowest'):
            print('[%s] 策略=%s；对手=%s；显示战力=%s（允许再次选中上场对手）' %
                  (label,mode,chosen.get('name',rid),opponent_power(chosen,handler)))
        if handler == "arena":
            b = _req("scene.arenaHandler.beginArenaBattle", {"targetId": rid})
        else:
            b = _req("scene.petArenaHandler.beginArenaBattle", {'targetId':rid} if mode in ('highest','lowest') else {})
        if _is_money_err(b):
            print("[%s] 创建战斗触发付费, 立即停止: %s" % (label, b.get("error"))); break
        if not (isinstance(b, dict) and b.get("code") == 200):
            free_stop = str(b.get("error") if isinstance(b, dict) else b)
            print("[%s] 创建战斗停止: %s" % (label, free_stop)); break
        time.sleep(battle_wait)
        actual_rid = (b.get("userData") or {}).get("rid") or rid
        if actual_rid != rid:
            print('[%s] 注意：服务器返回实际对手%s，与所选%s不一致' % (label,actual_rid,rid))
        e = _req("scene.%sHandler.endArenaBattle" % handler,
                 {"targetId": actual_rid, "win": 1})
        if _is_money_err(e):
            print("[%s] 结算触发付费, 立即停止: %s" % (label, e.get("error"))); break
        err = e.get("error") if isinstance(e, dict) else None
        if err:
            free_stop = str(err)
            print("[%s] 结算停止: %s" % (label, err)); break
        n += 1
        previous_rid = actual_rid
        print("[%s] 第%d场通关: %s" % (label, n, e.get("give") if isinstance(e, dict) else e))
        if round_index + 1 < planned_rounds:
            time.sleep(round_wait)
    print("[%s] 共快速通关 %d/%d 次(免费)" % (label, n, limit))

    # ---- 点券续战: 免费打满后, 20点券(ticket)/场, 每次打印消耗与余额, 不足即停 ----
    paid_enabled = ARENA_PAID_EXTRA if handler == "arena" else PET_ARENA_PAID_EXTRA
    paid_limit = ARENA_PAID_EXTRA_TIMES if handler == "arena" else PET_ARENA_PAID_EXTRA_TIMES
    if not paid_enabled:
        return
    if PAID_CONFIRM_BITS != "101":
        print("[%s] 点券续战已勾选，但三项确认不是 101；已跳过付费战斗" % label)
        return
    # 进入续战条件: 免费已打满, 或免费段因"次数用尽"停止(包括本轮之前已被外部打满的情形)
    if n < limit and "次数" not in free_stop:
        return  # 免费未打满且非次数用尽(其它错误), 不花点券
    print("[%s] 免费次数已用尽, 尝试点券续战(20点券/场)" % label)
    paid = 0
    if n:
        time.sleep(round_wait)
    while True:
        if paid_limit and paid >= paid_limit:
            print("[%s] 已到点券续战上限(%d场), 停止" % (label, paid_limit)); break
        if mode != "fixed":
            fresh = _req("scene.%sHandler.getArenaInfo" % handler, {})
            if not isinstance(fresh, dict) or fresh.get("error"):
                print("[%s] 续战刷新推荐对手失败: %s" % (label, fresh)); break
            choices = [r for r in fresh.get("recommend", []) if r.get("rid")]
            if not choices:
                print("[%s] 续战刷新后无推荐对手, 停止" % label); break
            chosen = choose_opponent(choices,handler,mode,previous_rid)
            rid = chosen['rid']
            print("[%s] 点券续战第%d场对手: %s" % (label, paid + 1, rid))
            if mode in ('highest','lowest'):
                print('[%s] 策略=%s；对手=%s；显示战力=%s' % (label,mode,chosen.get('name',rid),opponent_power(chosen,handler)))
        if handler == "arena":
            b = _req("scene.arenaHandler.beginArenaBattleWithTicket", {"targetId": rid})
        else:
            b = _req("scene.petArenaHandler.beginArenaBattleWithTicket", {"targetId": rid})
        if _is_money_err(b):
            print("[%s] 点券续战被拦截(点券不足/付费错误): %s, 停止"
                  % (label, b.get("error") if isinstance(b, dict) else b)); break
        if not (isinstance(b, dict) and b.get("code") == 200):
            print("[%s] 点券续战创建失败: %s" % (label, b.get("error") if isinstance(b, dict) else b)); break
        cons = b.get("consume") or []
        rem = None
        if cons and isinstance(cons[0], dict):
            rem = cons[0].get("remian")  # 服务器拼写 remain, 剩余点券
        # 结算目标: 优先用付费创建返回的对手 userData.rid(可能与本局推荐rid不同)
        tid = rid
        ud = b.get("userData") or {}
        if ud.get("rid"):
            tid = ud["rid"]
        if rem is not None and rem < 20:
            # begin 已扣 20 点券, 先结算本场再停, 避免白扣不结算
            print("[%s] 点券不足(剩%d<20), 先结算本场再停止续战" % (label, rem))
            e0 = _req("scene.%sHandler.endArenaBattle" % handler,
                      {"targetId": tid, "win": 1})
            if isinstance(e0, dict) and e0.get("error"):
                print("[%s] 本场结算失败: %s" % (label, e0.get("error")))
            else:
                paid += 1
                print("[%s] 点券续战第%d场: -20点券(剩%s) %s"
                      % (label, paid, rem, e0.get("give") if isinstance(e0, dict) else e0))
            break
        time.sleep(battle_wait)
        e = _req("scene.%sHandler.endArenaBattle" % handler, {"targetId": tid, "win": 1})
        if _is_money_err(e):
            print("[%s] 结算被拦截: %s, 停止" % (label, e.get("error") if isinstance(e, dict) else e)); break
        err = e.get("error") if isinstance(e, dict) else None
        if err:
            print("[%s] 点券续战结算失败: %s, 停止" % (label, err)); break
        paid += 1
        previous_rid = tid
        print("[%s] 点券续战第%d场: -20点券(剩%s) %s"
              % (label, paid, rem, e.get("give") if isinstance(e, dict) else e))
        time.sleep(round_wait)
    print("[%s] 点券续战共 %d 场" % (label, paid))


def battle_jjc(flow, info=None):
    battle_arena(flow, "arena", "竞技场", info=info)


def battle_pet_arena(flow, info=None):
    battle_arena(flow, "petArena", "斗宠大会", info=info)


def _agg_drops(bag, drops):
    for d in (drops or []):
        key = d.get("subType") or d.get("type")
        bag[key] += d.get("count", 0)


def clear_dungeon(flow, info, mid, label, open_chest=False, quota=None, claim_card=False,
                  max_runs=None, sell_boss=False, sell_small=False, sell_medicine=False):
    if mid in _NINE_POOL[:9]:
        from nine_tower import clear
        return clear(flow, info, mid, label, max_runs=max_runs)
    # create->(噩梦开宝箱)->finish; quota=(共享池,上限) 指定免费次数, 用尽即停(防静默扣点券/ticket)
    if quota is None:
        quota = ([mid], -1)
    shared, free_max = quota
    dun = info.setdefault("dungeon", {})
    bag = defaultdict(int)
    n = 0
    for _ in range(MAX_TIMES if max_runs is None else max_runs):
        if mid in ELITE_STAGES:
            from teacher_trial import enter as refresh_elite_info
            current = refresh_elite_info(flow, RECORD_INDEX)
            info.clear(); info.update(current); dun = info.setdefault('dungeon', {})
            elite_count_before = int((dun.get(str(mid)) or {}).get('dailyCount') or 0)
        remain = quota_remain(info, shared, free_max)
        if remain is not None and remain <= 0:
            used = sum(_dungeon_dcount(info, m) for m in shared)
            print("[%s] 免费次数已满(%d/%s), 停止(不花点券)" % (label, used, free_max)); break
        sale_before = None
        round_rewards = defaultdict(int)
        round_card_rewards = {}
        if sell_boss or sell_small or sell_medicine:
            if mid not in ELITE_STAGES:
                raise ValueError('材料自动出售仅支持精英关卡')
            from teacher_trial import enter
            sale_before = enter(flow, RECORD_INDEX)
        my_rnd = random.randint(0, 9999)
        # 神兽森林(300101~300112): create 必须带 costGem=0, 且只打 getSelectMonster 选中的那一个怪
        is_forest = 300101 <= mid <= 300112
        cparam = {"mid": mid, "rnd": my_rnd}
        if is_forest:
            cparam["costGem"] = 0
        r1 = flow.request("scene.copyHandler.createSinglePlayerCopy", cparam)
        if isinstance(r1, dict) and r1.get("error"):
            print("[%s] 停止: %s" % (label, r1.get("error"))); break
        if FIGHT_DELAY:
            time.sleep(25 if claim_card else 2)

        # 神兽森林: 必须拿到本关服务器指定要打的目标怪(固定一只)才允许捡掉落。
        # 取不到选中怪时严禁回退成“全捡”(会触发怪物数据异常/踢号)，一律不捡并关闭副本。
        target_mids = None
        if is_forest:
            select_error = None
            try:
                gsm = flow.request("scene.copyHandler.getSelectMonster", {})
            except Exception as exc:
                gsm, select_error = None, "请求异常: %s" % exc
            if not isinstance(gsm, dict):
                select_error = select_error or "返回非预期: %r" % (gsm,)
            else:
                sel = (gsm.get("selectMonster") or {}).get(str(mid)) or {}
                target_mids = set(str(k) for k in sel.keys())
                drop_mids = set(str(d.get("monsterId")) for d in (r1.get("drops") or []))
                if not target_mids:
                    select_error = "本关 %s 未返回选中怪" % mid
                elif not (target_mids & drop_mids):
                    select_error = ("服务器选中怪 %s 不在本副本掉落怪 %s 中，双方不一致"
                                    % (sorted(target_mids), sorted(drop_mids)))
            if select_error:
                print("[%s] 取不到选中怪，拒绝领取任何掉落并关闭副本: %s"
                      % (label, select_error), flush=True)
                try:
                    flow.request("scene.copyHandler.finishSingleCopy",
                                 {"win": 0, "rnd": r1["rnd"] ^ my_rnd, "star": 0})
                except Exception as exc:
                    print("[%s] 关闭副本失败: %s" % (label, exc), flush=True)
                break

        # 真手打掉落链路 syncDropInfo, code=200 则 give 真进包
        # 公式(AS3 PickUpDropItemCmd, + 优先级高于 ^):
        #   index = (DropIndex + ceil(random*10000)) ^ (ServerRand ^ MyRand)
        #   key   = ceil(random*10000) ^ MyRand ; DropIndex=掉落全局数组索引
        server_rand = r1["rnd"]
        xor = server_rand ^ my_rnd
        for i, d in enumerate(r1.get("drops") or []):
            if is_forest and str(d.get("monsterId")) not in target_mids:
                continue  # 神兽森林: 非选中怪的掉落不能捡, 否则报怪物数据异常
            rand = random.randint(1, 10000)
            idx = (i + rand) ^ xor
            key = rand ^ my_rnd
            try:
                sr = flow.request("scene.copyHandler.syncDropInfo", {"index": idx, "key": key})
            except Exception:
                if claim_card:
                    raise
                continue
            if isinstance(sr, dict) and sr.get("code") == 200:
                _agg_drops(bag, sr.get("give"))
                _agg_drops(round_rewards, sr.get("give"))
            elif claim_card:
                raise RuntimeError("[%s] 场景掉落领取失败: %s" % (label, sr))

        chest_drop = None
        if open_chest:
            chest = flow.request("scene.copyHandler.getDungeonTreasureDrop", {})
            chest_drop = chest.get("drop") or []
            if not chest_drop:
                cr0 = r1["rnd"] ^ my_rnd
                flow.request("scene.copyHandler.finishSingleCopy",
                             {"win": 1, "rnd": cr0, "star": 3})
                print("[%s] 共享宝箱已空, 停止" % label); break
            _agg_drops(bag, chest_drop)

        finish_args = {"win": 1, "rnd": r1["rnd"] ^ my_rnd, "star": 3}
        if claim_card:
            finish_args.update({"starInfo": 7, "sceneBuffScore": 0,
                                "maxCombo": 0, "killMonsterCnt": 0,
                                "useMagicWeaponCnt": 0, "useBossCardCnt": 0})
        sky_done = False
        if mid in _SKY_BOSS_ROOMS:
            # 天树王：先 create BOSS 房（700102/700202/700302），只结算 BOSS 房；
            # 先 finish 入口关会报「非法进入关卡」，入口关通关由 finishBId 记账
            bmid = _SKY_BOSS_ROOMS[mid]
            brnd = random.randint(0, 9999)
            b1 = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": bmid, "rnd": brnd})
            if isinstance(b1, dict) and b1.get("code") == 200 and b1.get("rnd") is not None:
                bx = int(b1["rnd"]) ^ brnd
                for i, d in enumerate(b1.get("drops") or []):
                    rand = random.randint(1, 10000)
                    sr = flow.request("scene.copyHandler.syncDropInfo",
                                      {"index": (i + rand) ^ bx, "key": rand ^ brnd})
                    if isinstance(sr, dict) and sr.get("code") == 200:
                        _agg_drops(bag, sr.get("give"))
                        _agg_drops(round_rewards, sr.get("give"))
                b2 = flow.request("scene.copyHandler.finishSingleCopy",
                                  {"win": 1, "rnd": bx, "star": 3})
                sky_done = isinstance(b2, dict) and b2.get("code") == 200 and not b2.get("error")
                if sky_done:
                    _agg_drops(round_rewards, [d for d in (b2.get('give') or []) if isinstance(d, dict)])
                    print("[%s] BOSS房 %s 已结算（入口关 %s 由服务端记通关）" % (label, bmid, mid))
                else:
                    print("[%s] BOSS房 %s 结算失败，回退结算入口关: %s" % (label, bmid, b2))
            else:
                print("[%s] BOSS房 %s 未进入，回退结算入口关: %s" % (label, bmid, b1))
        if not sky_done:
            r2 = flow.request("scene.copyHandler.finishSingleCopy", finish_args)
            if not isinstance(r2, dict) or r2.get("code") != 200 or r2.get("error"):
                print("[%s] 停止: %s" % (label, r2)); break
            _agg_drops(round_rewards, [d for d in (r2.get('give') or []) if isinstance(d, dict)])
        if mid not in ELITE_STAGES:
            rec = dun.setdefault(str(mid), {"id": mid, "dailyCount": 0})
            rec["dailyCount"] = rec.get("dailyCount", 0) + 1
        n += 1
        if claim_card:
            cards = flow.request("scene.copyHandler.getCard", {})
            if not isinstance(cards, dict) or cards.get("code") != 200 or not cards.get("items"):
                raise RuntimeError("[%s] 取牌面失败，已停止后续精英关: %s" % (label, cards))
            turned = flow.request("scene.copyHandler.turnCard", {})
            if not isinstance(turned, dict) or turned.get("code") != 200:
                raise RuntimeError("[%s] 免费翻牌失败，已停止后续精英关: %s" % (label, turned))
            if turned.get("consume"):
                raise RuntimeError("[%s] 翻牌出现非预期消耗，已停止后续精英关: %s"
                                   % (label, turned.get("consume")))
            _agg_drops(bag, turned.get("give"))
            _agg_drops(round_rewards, turned.get("give"))
            for gift in turned.get('give') or []:
                if isinstance(gift,dict) and gift.get('type')=='item':
                    pid=str(gift['subType'])
                    round_card_rewards[pid]=round_card_rewards.get(pid,0)+int(gift.get('count',0))
            print("[%s] 第%d次免费翻牌: %s" % (label, n, turned.get("give")))
        if sale_before is not None:
            from elite_material_sale import sell_round
            from teacher_trial import enter, checked
            current = enter(flow, RECORD_INDEX)
            user = checked(flow.request('connector.roleHandler.getUserInfo', {}), '出售前货币')['user']
            current, _ = sell_round(flow, sale_before, current, user, round_rewards,
                lambda: enter(flow, RECORD_INDEX), boss=sell_boss, small=sell_small,
                password=os.environ.get('ZM5_ELITE_SELL_PASSWORD', ''), card_rewards=round_card_rewards,
                medicine=sell_medicine)
            info.clear(); info.update(current); dun = info.setdefault('dungeon', {})
        if mid in ELITE_STAGES:
            if sale_before is None:
                current = refresh_elite_info(flow, RECORD_INDEX)
                info.clear(); info.update(current); dun = info.setdefault('dungeon', {})
            elite_count_after = int((dun.get(str(mid)) or {}).get('dailyCount') or 0)
            if elite_count_after != elite_count_before + 1:
                raise RuntimeError('[精英] 服务器次数变化不符，停止且不重复计数或重发')
        print("[%s] 第%d次通关 宝箱%d件" % (label, n, len(chest_drop or [])))
        time.sleep(SLEEP)
    if bag:
        print("[%s] 累计掉落: %s" % (label, dict(bag)))
    return n, dict(bag)


def run_nightmare(flow, info, max_runs=2):
    """只用噩梦共享宝箱的现有次数，逐件领取并核对免费翻牌。"""
    mid = int(NIGHTMARE_MID)
    if mid not in range(40010, 40271, 10):
        print("[噩梦] 关卡设置无效，跳过: %s" % mid)
        return
    rec = _dungeon_rec(info, mid)
    if not rec or int(rec.get("passNum") or 0) <= 0:
        print("[噩梦] %s 尚未通关解锁，跳过" % mid)
        return
    available = int(((info.get("dungeonTreasure") or {}).get("1400200") or {}).get("remainCnt") or 0)
    planned = min(available, 2, max_runs)
    print("[噩梦] 关卡=%s，当前共享宝箱=%s次，本轮执行=%s次" % (mid, available, planned))
    for number in range(1, planned + 1):
        if NIGHTMARE_CLAIM_FREE_CARD and NIGHTMARE_CARD_STRATEGY != 'free':
            refreshed = flow.request('connector.entryHandler.entry',
                                     {'index': RECORD_INDEX, 'userAgent': flow.user_agent})
            if refreshed.get('code') != 200 or not isinstance(refreshed.get('info'), dict):
                print('[噩梦] 无法刷新钥匙余额，停止本轮'); break
            info.update(refreshed['info'])
        my_rnd = random.randint(0, 9999)
        created = flow.request("scene.copyHandler.createSinglePlayerCopy",
                               {"mid": mid, "rnd": my_rnd})
        if not isinstance(created, dict) or created.get("code") != 200 or created.get("error"):
            print("[噩梦] 第%s次创建失败: %s" % (number, created)); break
        finished = False
        try:
            xor = int(created["rnd"]) ^ my_rnd
            for ordinal, drop in enumerate(created.get("drops") or []):
                if drop.get("type") == "coin" and drop.get("subType") == "exp":
                    continue
                salt = random.randint(1, 10000)
                claim = flow.request("scene.copyHandler.syncDropInfo", {
                    "index": (int(drop.get("dropIndex", ordinal)) + salt) ^ xor,
                    "key": salt ^ my_rnd})
                if claim.get("code") != 200 or claim.get("error"):
                    raise RuntimeError("场景掉落领取失败: %s" % claim)
            chest = flow.request("scene.copyHandler.getDungeonTreasureDrop", {})
            drops = (chest or {}).get("drop") or []
            if chest.get("code") != 200 or chest.get("error") or chest.get("consume") or not drops:
                raise RuntimeError("共享宝箱无免费奖励: %s" % chest)
            chest_rewards = defaultdict(int)
            for ordinal, drop in enumerate(drops):
                if drop.get("type") == "coin" and drop.get("subType") == "exp":
                    continue
                index = int(drop.get("dropIndex", ordinal))
                claim = flow.request("scene.copyHandler.getDungeonTreasureReward", {"i": index})
                if claim.get("code") != 200 or claim.get("error") or claim.get("consume"):
                    raise RuntimeError("共享宝箱第%s件领取失败: %s" % (index, claim))
                _agg_drops(chest_rewards, claim.get("give"))
            if FIGHT_DELAY:
                time.sleep(25)
            finish = flow.request("scene.copyHandler.finishSingleCopy", {
                "win": 1, "rnd": xor, "star": 3, "starInfo": 7,
                "sceneBuffScore": 0, "maxCombo": 0, "killMonsterCnt": 0,
                "useMagicWeaponCnt": 0, "useBossCardCnt": 0})
            if finish.get("code") != 200 or finish.get("error"):
                raise RuntimeError("结算失败: %s" % finish)
            finished = True
            card_reward = None
            if NIGHTMARE_CLAIM_FREE_CARD:
                from nightmare_cards import claim_cards_gem
                card_reward = claim_cards_gem(flow, info, strategy=NIGHTMARE_CARD_STRATEGY)
            info["dungeon"][str(mid)] = finish.get("dungeon") or info["dungeon"].get(str(mid), {})
            info["dungeonTreasure"]["1400200"]["remainCnt"] -= 1
            print("[噩梦] 第%s次通关；宝箱=%s；翻牌=%s" %
                  (number, dict(chest_rewards), card_reward))
            time.sleep(SLEEP)
        except Exception as exc:
            print("[噩梦] 第%s次停止: %s" % (number, exc))
            if not finished:
                try:
                    flow.request("scene.copyHandler.finishSingleCopy",
                                 {"win": 0, "rnd": int(created["rnd"]) ^ my_rnd,
                                  "star": 0})
                except Exception:
                    pass
            break


def _elite_quest_map(flow):
    """读取任务→日常任务里的精英关卡任务（taskClass=2）。"""
    with open(os.path.join(os.path.dirname(__file__), "elite_daily_tasks.json"), encoding="utf-8-sig") as f:
        catalog = json.load(f)
    out = {row["mid"]: [{"id": row["id"], "taskClass": 2, "status": 0}]
           for row in catalog}
    try:
        r = flow.request("scene.questHandler.getQuestList", {})
        if r.get("code") != 200 or r.get("error"):
            raise RuntimeError(r.get("error") or r)
        for q in (r.get("quest") or []):
            qid = q.get("id")
            if q.get("taskClass") != 2 or not isinstance(qid, int):
                continue
            for row in catalog:
                if row["id"] == qid:
                    out[row["mid"]] = [q]
                    break
    except Exception as e:
        print("[精英任务] 查询失败: %s" % e)
        return {}
    return out


def _claim_elite_quests(flow, mids):
    """通关后重读任务状态，只领取 status=2 的精英任务。"""
    elite_tasks = _elite_quest_map(flow)
    for mid in mids:
        for q in elite_tasks.get(mid, []):
            qid = q.get("id")
            if q.get("status") != 2:
                continue
            try:
                r = flow.request("scene.questHandler.commitQuest", {"qId": qid})
                err = r.get("error") if isinstance(r, dict) else None
                if err:
                    print("[精英任务] 关%s 任务%s %s" % (mid, qid, err))
                else:
                    print("[精英任务] 关%s 任务%s 领取成功: %s"
                          % (mid, qid, json.dumps(r, ensure_ascii=False)[:120]))
            except Exception as e:
                print("[精英任务] 关%s 任务%s 异常: %s" % (mid, qid, e))
            time.sleep(SLEEP)


def run_dungeons(flow, info):
    # 自选关卡组: 默认打最高已解锁关(可用 STAGE_OVERRIDE 指定), 次数共享, 用尽即停
    grand = {}
    for grp in FARM_GROUPS:
        if grp["key"] == "forest":
            continue  # 神兽森林由三分支入口单独处理
        if not globals().get("RUN_" + grp["key"].upper(), False):
            continue
        ov = STAGE_OVERRIDE.get(grp["key"])
        mid = int(ov) if ov else pick_highest_cleared(info, grp["stages"])
        label = "%s·%s(最高关)" % (grp["prefix"], mid)
        remain = quota_remain(info, grp["shared"], grp["max"])
        print("[%s] 选关=%s 今日免费剩余=%s" % (grp["prefix"], mid, remain))
        _, drops = clear_dungeon(flow, info, mid, label, grp["chest"],
                                 quota=(grp["shared"], grp["max"]))
        if drops:
            grand[label] = drops
    # 精英/主线: 每关【独立】2次/天, 不共享
    if RUN_ELITE:
        multi_mids = sorted({int(mid) for mid in ELITE_MULTI_MIDS if int(mid) in ELITE_STAGES})
        if multi_mids:
            # 多选模式：接取在日常任务阶段完成；通关后重新查询任务状态并领奖。
            for emid in multi_mids:
                elabel = "精英·%s" % emid
                remain = quota_remain(info, [emid], ELITE_MAX)
                print("[精英多选] 选关=%s 本关今日剩余=%s(每关独立2次)" % (emid, remain))
                if remain is not None and remain <= 0:
                    print("[精英多选] %s 次数已满, 跳过" % emid)
                    continue
                _, edrops = clear_dungeon(flow, info, emid, elabel, False,
                                          quota=([emid], ELITE_MAX),
                                          claim_card=(ELITE_CLAIM_FREE_CARD or RUN_ELITE_STONE),
                                          sell_boss=ELITE_SELL_BOSS, sell_small=ELITE_SELL_SMALL,
                                          sell_medicine=ELITE_SELL_MEDICINE)
                if edrops:
                    grand[elabel] = edrops
                _claim_elite_quests(flow, [emid])
        else:
            print("[精英] 未勾选关卡，跳过")

    # 主线自定义刷取(无次数限制, 注意 dailycount 封号风险)
    custom_mid = globals().get("MAIN_CUSTOM_MID", 0)
    custom_times = globals().get("MAIN_CUSTOM_TIMES", 0)
    if custom_mid and custom_times > 0:
        dun = info.get("dungeon", {}).get(str(custom_mid), {})
        dc = dun.get("dailyCount", 0)
        print("[主线自定义] mid=%s 次数=%d 当前dailyCount=%d (⚠ 过高会封号)"
              % (custom_mid, custom_times, dc))
        cbag = defaultdict(int)
        done = 0
        for i in range(custom_times):
            my_rnd = random.randint(0, 9999)
            r1 = flow.request("scene.copyHandler.createSinglePlayerCopy",
                              {"mid": custom_mid, "rnd": my_rnd})
            if isinstance(r1, dict) and r1.get("error"):
                print("[主线自定义] 第%d次 创建失败: %s" % (i+1, r1.get("error")))
                break
            time.sleep(0.5)
            r2 = flow.request("scene.copyHandler.finishSingleCopy",
                              {"win": 1, "rnd": r1["rnd"] ^ my_rnd, "star": 3})
            _agg_drops(cbag, r1.get("drops"))
            _agg_drops(cbag, r2.get("drops"))
            done += 1
            print("[主线自定义] 第%d/%d次 完成 掉落: %s" % (done, custom_times, dict(cbag)))
            time.sleep(SLEEP)
        # 刷新 dailyCount
        dun2 = info.get("dungeon", {}).get(str(custom_mid), {})
        print("[主线自定义] 完成%d次(计划%d次), dailyCount: %d -> %d, 掉落: %s"
              % (done, custom_times, dc, dun2.get("dailyCount", 0), dict(cbag)))
        if cbag:
            grand["主线自定义·%s" % custom_mid] = dict(cbag)

    with open(DROPS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), "drops": grand},
                           ensure_ascii=False) + "\n")
    print("掉落已记录到", DROPS_LOG)


def run_forest(flow, info):
    mode = FOREST_MODE if FOREST_MODE in ("manual", "sweep", "preview") else "sweep"
    if mode == "preview":
        forest_selected_materials(flow)
        return
    mid = STAGE_OVERRIDE.get("forest") or pick_highest_cleared(info, _FOREST)
    mid = int(mid)
    if mid not in _FOREST:
        print("[神兽森林] 关卡设置无效: %s" % mid)
        return
    if mode == "sweep":
        drops = sweep_forest(flow, info, mid)
    else:
        print("[神兽森林] 固定关卡 %s，最多手打4次（只用剩余免费次数）" % mid)
        _, drops = clear_dungeon(flow, info, mid, "神兽森林·%s" % mid,
                                 quota=(_FOREST, 4))
    if drops:
        with open(DROPS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()),
                                "drops": {"神兽森林·%s" % mid: drops}},
                               ensure_ascii=False) + "\n")


def clear_activity_once(flow, mid, label):
    my_rnd = random.randint(0, 9999)
    r1 = flow.request("scene.copyHandler.createSinglePlayerCopy",
                      {"mid": mid, "rnd": my_rnd})
    if isinstance(r1, dict) and r1.get("error"):
        return False, {}, r1.get("error")
    bag = defaultdict(int)
    if mid in (500112, 500113, 500120, 500127):
        gm_names = {"906301": "萌哥", "906302": "萌哥", "906303": "汪汪", "906304": "萌哥", "906305": "礼盒",
                    "906311": "萌哥", "906312": "萌哥", "906313": "汪汪", "906314": "萌哥", "906315": "礼盒",
                    "906701": "汪汪", "906705": "汪汪", "906703": "萌哥", "906707": "萌哥", "906704": "教主", "906708": "教主"}
        selected = list(dict.fromkeys(gm_names[str(d.get("monsterId"))] for d in (r1.get("drops") or []) if str(d.get("monsterId")) in gm_names))
        print("[%s] 本场服务器掉落对应：%s；按实际掉落拾取" % (label, "、".join(selected)))
    server_rnd = int(r1["rnd"])
    for ordinal, drop in enumerate(r1.get("drops") or []):
        # 正常单人副本的物品由 syncDropInfo 逐个确认拾取；create 返回的 drops 只是地面掉落列表。
        # 客户端遇到经验直接本地处理，其余普通掉落按 DropIndex + 双随机数生成校验参数。
        if drop.get("type") == "exp":
            continue
        drop_index = int(drop.get("dropIndex", ordinal))
        salt = random.randint(1, 10000)
        payload = {
            "index": (drop_index + salt) ^ (server_rnd ^ my_rnd),
            "key": salt ^ my_rnd,
        }
        picked = flow.request("scene.copyHandler.syncDropInfo", payload)
        if (not isinstance(picked, dict) or picked.get("error")
                or picked.get("code") != 200):
            print("[活动] %s 掉落拾取失败(index=%s): %s"
                  % (label, drop_index, picked.get("error", picked) if isinstance(picked, dict) else picked))
            continue
        _agg_drops(bag, picked.get("give"))
        time.sleep(SLEEP)
    r2 = flow.request("scene.copyHandler.finishSingleCopy",
                      {"win": 1, "rnd": server_rnd ^ my_rnd, "star": 3})
    if isinstance(r2, dict) and r2.get("error"):
        return False, dict(bag), r2.get("error")
    return True, dict(bag), None


def activity_bag_ready(info, label, reserve=5):
    """活动掉落包含材料和消耗品，入场前分别预留两栏空间。"""
    bag = info.get("bag") or {}
    capacity = bag.get("itemBagMax")
    items = bag.get("item")
    if not isinstance(items, dict) or not isinstance(capacity, (int, float)):
        print("[背包检查] %s 无法确认材料栏容量，跳过入场，请重新登录后检查背包" % label)
        return False
    consumable_capacity = bag.get("consumablesBagMax")
    if not isinstance(consumable_capacity, (int, float)):
        print("[背包检查] %s 无法确认消耗品栏容量，本项未入场" % label)
        return False
    used = [0, 0]
    for row in items.values():
        if isinstance(row, dict) and int(row.get("count", 0)) > 0:
            used[int(bool(int(row.get("isConsume", 0) or 0)))] += 1
    ready = True
    for kind, count, maximum in (("普通材料", used[0], int(capacity)),
                                 ("消耗品", used[1], int(consumable_capacity))):
        free = max(0, maximum - count)
        print("[背包检查] %s %s栏 %s/%s，剩余%s格" % (label, kind, count, maximum, free))
        if free < reserve:
            print("[背包空间不足] %s %s栏至少预留%s格，请清理该栏后重新执行；本项未入场" % (label, kind, reserve))
            ready = False
    return ready


def run_activity(flow, info):
    grand = {}
    dun = info.setdefault("dungeon", {})
    _act_map = {
        "刑天": "RUN_ACT_XINGTIAN",
        "牛魔王": "RUN_ACT_MONKIAN",
        "魔龙": "RUN_ACT_DRAGON",
        "GM切磋": "RUN_ACT_GM",
        "挑战GM": "RUN_ACT_FIGHT_GM",
        "邪·悟空": "RUN_ACT_XWUKONG",
        "邪·瑶瑶": "RUN_ACT_XYAOYAO",
        "邪·唐僧": "RUN_ACT_XTANG",
        "邪·龙女": "RUN_ACT_XLONG",
        "邪·二郎神": "RUN_ACT_XYANGJIAN",
        "邪·八戒": "RUN_ACT_XBAJIE",
        "邪·沙僧": "RUN_ACT_XSHASENG",
        "邪·白龙": "RUN_ACT_XBAILONG",
    }
    print("[活动] 游戏版本 v%s，本轮邪角色：%s"
          % (GAME_VERSION, "、".join(active_xie_names())))
    for act in ACTIVITIES:
        name = act["name"]
        # 按独立开关过滤
        _sw = _act_map.get(name)
        if _sw and not globals().get(_sw, True):
            continue
        max_n = act["max"]
        remain = quota_remain(info, act["shared"], max_n)
        if remain is not None and remain <= 0:
            print("[活动] %s 免费次数已满(%d/%d), 跳过(不花点券)"
                  % (name, max_n, max_n))
            continue
        order = ([(act["hard"], "-噩梦"), (act["normal"], "-普通")]
                 if ACTIVITY_PREFER == "hard"
                 else [(act["normal"], "-普通"), (act["hard"], "-噩梦")])
        # 只执行剩余免费次数, 避免已有使用次数后把后续请求变成付费场次
        rounds = max_n if remain is None else min(max_n, max(0, remain))
        done_n = 0
        for round_i in range(rounds):
            got = False
            for mid, suffix in order:
                label = name + suffix
                refreshed = flow.request("connector.entryHandler.entry",
                                         {"index": RECORD_INDEX, "userAgent": flow.user_agent})
                fresh_info = refreshed.get("info") if isinstance(refreshed, dict) else None
                if not isinstance(fresh_info, dict) or not activity_bag_ready(fresh_info, label):
                    print("[活动] %s 背包检查未通过，停止本项；请查看上方提示" % label)
                    break
                if quota_remain(fresh_info, act["shared"], max_n) <= 0:
                    print("[活动] %s 最新免费次数不足，停止本项" % label)
                    break
                ok, drops, err = clear_activity_once(flow, mid, label)
                if ok:
                    print("[活动] %s 第%d次通关: %s" % (label, round_i+1, drops or "无掉落"))
                    if drops:
                        grand[label] = drops
                    rec = dun.setdefault(str(mid), {"id": mid, "dailyCount": 0})
                    rec["dailyCount"] = rec.get("dailyCount", 0) + 1
                    got = True
                    done_n += 1
                    break
                print("[活动] %s 不可打: %s" % (label, err))
                if "点券" in str(err) or "票" in str(err):
                    break
                time.sleep(SLEEP)
            if not got:
                break
            time.sleep(SLEEP)
        if done_n == 0:
            print("[活动] %s 今日跳过(未开放/不满足条件)" % name)
        else:
            print("[活动] %s 共打 %d/%d 次" % (name, done_n, max_n))
        time.sleep(SLEEP)
    if grand:
        with open(DROPS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "drops": grand},
                               ensure_ascii=False) + "\n")


def run_card_cave(flow, info):
    """与藏宝洞页面共用同一开局、结算、免费次数和奖励核查流程。"""
    from card_cave_target import run_matches
    if CARD_CAVE_MODE == 'specified' and not (CARD_CAVE_CODE and CARD_CAVE_FINGERPRINT):
        print("[藏宝洞] 指定模式未配置挑战码或未查询确认，跳过；请先在藏宝洞页查询并确认")
        return
    return run_matches(flow, RECORD_INDEX, int(CARD_CAVE_TIMES), float(CARD_CAVE_WAIT),
                       CARD_CAVE_MODE, CARD_CAVE_CODE, CARD_CAVE_FINGERPRINT)


def clear_copy_once(flow, mid, label):
    my_rnd = random.randint(0, 9999)
    r1 = flow.request("scene.copyHandler.createSinglePlayerCopy",
                      {"mid": mid, "rnd": my_rnd})
    if isinstance(r1, dict) and r1.get("error"):
        print("[%s] mid=%s 失败: %s" % (label, mid, r1.get("error"))); return False
    bag = defaultdict(int)
    _agg_drops(bag, r1.get("drops"))
    r2 = flow.request("scene.copyHandler.finishSingleCopy",
                      {"win": 1, "rnd": r1["rnd"] ^ my_rnd, "star": 3})
    if isinstance(r2, dict) and r2.get("error"):
        print("[%s] mid=%s 结算失败: %s" % (label, mid, r2.get("error"))); return False
    print("[%s] mid=%s 通关 dailyCount=%s 掉落=%s"
          % (label, mid, r2.get("dungeon", {}).get("dailyCount"),
             dict(bag) or "无(首通/任务奖另行结算)"))
    return True


def run_halo(flow, info):
    if str(HALO_TEAM_MODE).lower() in ("three", "three_main"):
        print("[十绝阵] 当前为“三人3000分”模式，日常单账号跳过；请用周常页的“三人组队开打”。")
        return
    from halo_solo import run_halo_solo
    g = flow.request("scene.haloHandler.getDungeonId", {})
    did = g.get("dungeonId")
    if did is None:
        print("[十绝阵] 未取到 dungeonId:", g.get("error") or g); return
    did = int(did)
    print("[十绝阵] 当前关卡 %s, 选择 %s 分档, 奖励剩余 %s 次"
          % (did, HALO_TARGET_SCORE, (info.get("halo") or {}).get("haloRewardCnt", 0)))
    if run_halo_solo(flow, info, did, RECORD_INDEX, HALO_TARGET_SCORE):
        time.sleep(SLEEP)


def run_manhuang(flow, info):
    if str(MANHUANG_MODE).lower() in ("team2", "team3"):
        print("[蛮荒] 当前为多人组队模式，日常单账号跳过；请用周常页“蛮荒设置”的“组队开打”。")
        return
    # 确定目标关卡: MANHUANG_MID>0 用指定的, 否则自动选最高已解锁
    if MANHUANG_MID and MANHUANG_MID > 0:
        target_mid = MANHUANG_MID
        target_name = dict(MANHUANG_MIDS).get(target_mid, str(target_mid))
    else:
        target_mid = pick_highest_cleared(info, [m for m, _ in MANHUANG_MIDS])
        target_name = dict(MANHUANG_MIDS).get(target_mid, str(target_mid))

    # 根据模式转换mid: 多人版1400xxx, 单人版1410xxx(+10000)
    mode_label = "多人版" if MANHUANG_MODE == "multi" else "单人版"
    actual_mid = target_mid if MANHUANG_MODE == "multi" else target_mid + 10000

    # 登录/重新进存档时已有共享宝箱次数；getDungeonTreasureDrop 只在 BOSS 死后调用。
    # 不为了查询次数额外发该请求，避免改变当前副本的宝箱状态。
    treasure = info.get("dungeonTreasure") or {}
    record = treasure.get("1400100") or treasure.get(1400100) or {}
    remain = int(record.get("remainCnt", 0))
    print("[蛮荒] 目标=%s(%s, mid=%s) 共享宝箱剩余=%s次(所有副本共享, 用尽即停不扣点券)"
          % (target_name, mode_label, actual_mid, remain))
    if remain <= 0:
        print("[蛮荒] 今日共享宝箱次数已用完, 跳过(不发请求不扣点券)"); return

    # 蛮荒完整流程: 创建→BOSS死(查看宝箱getDungeonTreasureDrop)→领取(getDungeonTreasureReward)→结算
    my_rnd = random.randint(0, 9999)
    r1 = flow.request("scene.copyHandler.createSinglePlayerCopy",
                      {"mid": actual_mid, "rnd": my_rnd})
    if not isinstance(r1, dict) or r1.get("error") or "rnd" not in r1:
        print("[蛮荒-%s] 创建失败: %s" % (target_name, r1)); return

    # BOSS死亡时查看宝箱掉落(必须在结算前调用)
    chest_bag = defaultdict(int)
    try:
        cd = flow.request("scene.copyHandler.getDungeonTreasureDrop", {})
        if not isinstance(cd, dict) or cd.get("error") or cd.get("code") not in (None, 200):
            raise ValueError("查询宝箱失败: %s" % cd)
        chest_drops = cd.get("drop") or []
        # 客户端按每件掉落的 dropIndex 发送 {"i": index}，不能用空参数一次领取。
        for i, drop in enumerate(chest_drops):
            if not isinstance(drop, dict):
                continue
            index = drop.get("dropIndex", i)
            cr = flow.request("scene.copyHandler.getDungeonTreasureReward", {"i": index})
            if not isinstance(cr, dict) or cr.get("error") or cr.get("code") != 200:
                print("[蛮荒-%s] 宝箱第%s件领取失败: %s" % (target_name, index, cr))
                continue
            give = cr.get("give") or []
            if isinstance(give, dict):
                give = [give]
            _agg_drops(chest_bag, give)
        if not chest_drops:
            print("[蛮荒-%s] 宝箱无掉落" % target_name)
    except Exception as e:
        print("[蛮荒-%s] 宝箱异常: %s" % (target_name, e))

    # 最后结算
    r2 = flow.request("scene.copyHandler.finishSingleCopy",
                      {"win": 1, "rnd": r1["rnd"] ^ my_rnd, "star": 3})
    if not isinstance(r2, dict) or r2.get("error") or r2.get("code") not in (None, 200):
        print("[蛮荒-%s] 结算失败: %s" % (target_name, r2)); return
    print("[蛮荒-%s] 通关 dailyCount=%s 宝箱材料=%s"
          % (target_name, r2.get("dungeon", {}).get("dailyCount"),
             dict(chest_bag) or "无"))
    if chest_bag:
        with open(DROPS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()),
                                "drops": {"蛮荒-%s" % target_name: dict(chest_bag)}},
                               ensure_ascii=False) + "\n")
    time.sleep(SLEEP)


def _fls_unlock_week(flow, mid, name):
    my_rnd = random.randint(0, 9999)
    r1 = flow.request("scene.copyHandler.createSinglePlayerCopy",
                      {"mid": mid, "rnd": my_rnd})
    if not isinstance(r1, dict) or r1.get("error") or r1.get("code") not in (None, 200) or "rnd" not in r1:
        print("[福禄寿-%s] 普通入场失败: %s" % (name, r1)); return False
    r2 = flow.request("scene.copyHandler.finishSingleCopy",
                      {"win": 1, "rnd": r1["rnd"] ^ my_rnd, "star": 3,
                       "sceneBuffScore": 120, "maxCombo": 9, "killMonsterCnt": 66,
                       "useMagicWeaponCnt": 0, "useBossCardCnt": 0})
    if not isinstance(r2, dict) or r2.get("error") or r2.get("code") not in (None, 200):
        print("[福禄寿-%s] 普通结算失败: %s" % (name, r2)); return False
    print("[福禄寿-%s] 普通通关成功，120分" % name)
    time.sleep(SLEEP)
    return True


def run_flushou(flow, info):
    # 福禄寿每天免费次数: VIP3及以上2次, VIP0/1/2为1次(base dailyCountMax=1 + vipCountMax);
    # 超出每次扣 ticket(200), 且付费扫荡【不增加】dailyCount。用 dailyCount 严格计数, 绝不在免费次数外扫。
    if FLUSHOU_MODE not in ("all", "once"):
        raise ValueError("福禄寿执行模式无效")
    vip = int((info.get("vip") or {}).get("level") or 0)
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feature_config", "VIP.json")
    with open(config_path, encoding="utf-8-sig") as stream:
        vip_row = json.load(stream).get(str(vip)) or {}
    can_sweep = int(vip_row.get("flsSweep") or 0) > 0
    print("[福禄寿] VIP%d，执行方式：%s" % (vip, "免费扫荡" if can_sweep else "普通通关"))
    free_max = 2 if vip >= 3 else 1
    dun = info.setdefault("dungeon", {})
    for mid, name in FLUSHOU_MIDS:
        used = _dungeon_dcount(info, mid)
        if used >= free_max:
            print("[福禄寿-%s] 今日免费已用完(%d/%d), 跳过(不花点券)" % (name, used, free_max))
            continue
        target_used = free_max if FLUSHOU_MODE == "all" else min(free_max, used + 1)
        unlock_tried = False
        while used < target_used:
            if not can_sweep:
                if not _fls_unlock_week(flow, mid, name):
                    break
                used += 1
                dun.setdefault(str(mid), {"id": mid})["dailyCount"] = used
                continue
            rec = _dungeon_rec(info, mid) or {}
            r = flow.request("scene.copyHandler.sweepBuffCopy",
                             {"mid": mid, "passNum": int(rec.get("passNum") or 0)})
            err = (r.get("error") or ("异常返回：%s" % r if r.get("code") not in (None, 200) else None)) if isinstance(r, dict) else "无有效响应"
            if not err:
                used += 1
                rec = dun.setdefault(str(mid), {"id": mid, "dailyCount": 0})
                server_rec = r.get("dungeon")
                if isinstance(server_rec, dict) and server_rec.get("id") == mid:
                    # 连扫时沿用服务端最新 passNum，客户端 sweepBack 同样会回写该字段。
                    rec["passNum"] = int(server_rec.get("passNum") or rec.get("passNum") or 0)
                rec["dailyCount"] = used
                buffs = r.get("buffs")
                print("[福禄寿-%s] 免费扫荡成功(%d/%d) buff数=%s"
                      % (name, used, free_max, len(buffs) if buffs else 0))
                time.sleep(SLEEP)
                continue
            if "积分" in str(err) and not unlock_tried:
                # 本周未打满120分: 打1次解锁(占用今日1次免费场次), 再用剩余场次扫荡
                unlock_tried = True
                if _fls_unlock_week(flow, mid, name):
                    used += 1
                    rec = dun.setdefault(str(mid), {"id": mid, "dailyCount": 0})
                    rec["dailyCount"] = used
                    time.sleep(SLEEP)
                    continue
                break
            print("[福禄寿-%s] 今日跳过: %s" % (name, err))
            break
        if used >= target_used and target_used < free_max:
            print("[福禄寿-%s] 本次仅执行一次已完成，今日剩余免费%d次" % (name, free_max - used))
        if used >= free_max:
            print("[福禄寿-%s] 今日免费次数已用满(%d/%d), 停止(不花点券)" % (name, used, free_max))


def run_mid_autumn(flow, info):
    # 中秋博饼: 明确只发免费类型, 每日计数预检, 单次请求不重试。
    daily = info.get("everyDaySetting") if isinstance(info, dict) else None
    if not isinstance(daily, dict):
        print("[中秋博饼] 缺少每日状态，无法确认免费次数，跳过")
        return
    try:
        used = int(daily.get("boCakeCnt", 0) or 0)
    except (TypeError, ValueError):
        print("[中秋博饼] 免费次数格式异常，跳过")
        return
    if used >= 1:
        print("[中秋博饼] 今日免费次数已用完(%d/1)，跳过" % used)
        return
    try:
        r = flow.request("scene.activityHandler.midBoCake", {"type": 0})
    except Exception as e:
        print("[中秋博饼] 免费试掷异常(不重试): %s" % e)
        return
    err = r.get("error") if isinstance(r, dict) else "返回格式异常"
    if err:
        print("[中秋博饼] 免费试掷失败(不重试): %s" % err)
        return
    updated_daily = r.get("everyDaySetting")
    if isinstance(updated_daily, dict):
        daily.update(updated_daily)
    elif "boCakeCnt" in r:
        daily["boCakeCnt"] = r["boCakeCnt"]
    print("[中秋博饼] 免费试掷完成，饼档=%s 积分=%s 奖励=%s"
          % (r.get("bcId"), r.get("points"), r.get("give") or []))


JIN_QIU_ACTIVITY_ID = 2051
JIN_QIU_FREE_MAX = 1


def _jin_qiu_free_reward_id(info, activity_id):
    """Mirror RedPacketManager.getRecId: latest unclaimed recharge record, or empty string."""
    rows = info.get("rechargeActivity") or {}
    if isinstance(rows, dict):
        rows = rows.values()
    elif not isinstance(rows, (list, tuple)):
        return ""
    reward_id = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            matches_activity = int(row.get("activityId", -1)) == int(activity_id)
        except (TypeError, ValueError):
            matches_activity = False
        if matches_activity and str(row.get("status")) != "2":
            reward_id = str(row.get("id") or "")
    return reward_id


def run_jin_qiu(flow, info):
    """Claim only 金秋送福's one daily free 金秋蜜意 box; never use paid types."""
    if not isinstance(info, dict):
        print("[金秋送福] 缺少存档信息，无法确认免费状态，跳过")
        return False
    daily = info.get("everyDaySetting")
    red_packet = info.get("redPacket")
    if not isinstance(daily, dict) or not isinstance(red_packet, dict):
        print("[金秋送福] 服务器未返回红包/每日状态，跳过")
        return False
    try:
        activity_id = int(red_packet.get("id", -1))
    except (TypeError, ValueError):
        activity_id = -1
    if activity_id != JIN_QIU_ACTIVITY_ID:
        print("[金秋送福] 当前红包活动ID=%s，不是本期金秋送福(%d)，跳过"
              % (red_packet.get("id"), JIN_QIU_ACTIVITY_ID))
        return False
    # Flash EveryDaySetting initializes omitted counters to zero.
    try:
        used = int(daily.get("redPacketFreeGiftDayNum", 0) or 0)
    except (TypeError, ValueError):
        print("[金秋送福] 每日免费次数格式异常，跳过")
        return False
    if used >= JIN_QIU_FREE_MAX:
        print("[金秋送福] 今日免费开箱已用完(%d/%d)，跳过"
              % (used, JIN_QIU_FREE_MAX))
        return False

    # The client sends the current eligible recharge-record id; this is empty
    # when there is no recharge record, which is normal for the free type=0.
    reward_id = _jin_qiu_free_reward_id(info, activity_id)
    try:
        result = flow.request("scene.activityHandler.getRedPacketReward",
                              {"type": 0, "id": reward_id})
    except Exception as e:
        print("[金秋送福] 免费开箱请求异常(不重试): %s" % e)
        return False
    if not isinstance(result, dict):
        print("[金秋送福] 返回格式异常(不重试)，避免重复请求")
        return False
    error = result.get("error")
    if error:
        print("[金秋送福] 免费开箱失败(不重试): %s" % error)
        return False

    updated_daily = result.get("everyDaySetting")
    if isinstance(updated_daily, dict):
        daily.update(updated_daily)
    elif "redPacketFreeGiftDayNum" in result:
        daily["redPacketFreeGiftDayNum"] = result["redPacketFreeGiftDayNum"]
    used_after = daily.get("redPacketFreeGiftDayNum", used + 1)
    give = result.get("give") or result.get("drops") or []
    print("[金秋送福] 金秋蜜意免费开箱完成，今日次数=%s/%d，奖励=%s"
          % (used_after, JIN_QIU_FREE_MAX, give))
    return True


def run_cloud_ladder(flow, info):
    """使用当天免费机会，处理额外免费投掷，并领取已到达档位。"""
    thresholds = (6, 40, 80, 120)  # CloudLadderHelp: 奖励索引 0–3
    ladder = info.get("cloudLadder") or {}
    daily = info.get("everyDaySetting") or {}

    def claim_eligible(state):
        pos = int(state.get("pos") or 0)
        claimed = state.get("reward") or {}
        for index, threshold in enumerate(thresholds):
            if pos < threshold or str(index) in claimed or index in claimed:
                continue
            reward = flow.request("scene.activityHandler.getCloudLadderReward", {"i": index})
            if not isinstance(reward, dict) or reward.get("code") != 200 or reward.get("error") or reward.get("consume"):
                print("[云梯寻宝] 档位%s领奖失败: %s" % (index, reward))
                break
            print("[云梯寻宝] 领取达到%s格的奖励: %s" % (threshold, reward.get("give")))
            state = reward.get("cloudLadder") or state
            claimed = state.get("reward") or claimed
        return state

    ladder = claim_eligible(ladder)
    used = int(daily.get("cloudLadderCount") or 0)
    if used >= 1 and int(ladder.get("event") or 0) != 1:
        print("[云梯寻宝] 今日免费投掷已用完，跳过付费投掷")
        return
    # 格子事件1会给予额外免费投掷；次数上限防止异常响应导致循环。
    for roll_num in range(1, 13):
        if used >= 1 and int(ladder.get("event") or 0) != 1:
            break
        response = flow.request("scene.activityHandler.cloudLadder", {})
        if not isinstance(response, dict) or response.get("code") != 200 or response.get("error") or response.get("consume"):
            print("[云梯寻宝] 第%s次免费投掷停止: %s" % (roll_num, response))
            break
        operations = response.get("operate") or []
        ladder = response.get("cloudLadder") or ladder
        updated = response.get("everyDaySetting") or {}
        used = int(updated.get("cloudLadderCount", used))
        print("[云梯寻宝] 第%s次投掷，服务器点数=%s，当前位置=%s，格子奖励=%s" %
              (roll_num, [row.get("point") for row in operations],
               ladder.get("pos"), [row.get("give") for row in operations]))
        ladder = claim_eligible(ladder)
        if int(ladder.get("pos") or 0) >= 120:
            break
        time.sleep(SLEEP)
    info["cloudLadder"] = ladder
    daily["cloudLadderCount"] = used


def run_relic_treasure(flow):
    # 遗迹寻宝: 开始 -> 直接结束(win=1)
    r = flow.request("scene.activityHandler.beginRelicTreasure", {})
    err = r.get("error") if isinstance(r, dict) else None
    if err:
        print("[遗迹寻宝] 开始跳过: %s" % err); return
    print("[遗迹寻宝] 开始成功, 等待结束...")
    time.sleep(SLEEP * 2)
    end = flow.request("scene.activityHandler.endRelicTreasure", {"win": 1})
    if isinstance(end, dict) and not end.get("error"):
        give = end.get("give") or end.get("relicTreasure")
        print("[遗迹寻宝] 结束成功, 奖励=%s" % give)
    else:
        print("[遗迹寻宝] 结束跳过: %s" % (end or {}).get("error"))


def run_stove(flow, info=None):
    """普通聚灵池：只使用VIP免费聚灵次数，不消费聚灵石。"""
    def checked(reply, action):
        if not isinstance(reply, dict) or reply.get("code") != 200 or reply.get("error"):
            raise RuntimeError("[聚灵池] %s失败：%s" % (action, reply))
        return reply
    def refresh():
        return checked(flow.request("connector.entryHandler.entry", {
            "index": RECORD_INDEX, "userAgent": flow.user_agent}), "读取存档")["info"]
    def ticket():
        user = checked(flow.request("connector.roleHandler.getUserInfo", {}), "读取点券").get("user") or {}
        if user.get("ticket") is None:
            raise RuntimeError("[聚灵池] 无法确认点券余额")
        return int(user["ticket"])
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "feature_config", "PetElfLottery.json"), encoding="utf-8") as stream:
        row = json.load(stream)["1"]
    info = refresh()
    vip = int((info.get("vip") or {}).get("level") or 0)
    quotas = [int(x) for x in row["vipFreeNum"].split(";")]
    if not 0 <= vip < len(quotas):
        raise RuntimeError("[聚灵池] VIP等级不在配置范围")
    daily = info.get("everyDaySetting")
    if not isinstance(daily, dict):
        raise RuntimeError("[聚灵池] 缺少每日状态，停止")
    counts = daily.get("petElfLottery", {})
    if not isinstance(counts, dict):
        raise RuntimeError("[聚灵池] 每日次数格式异常，停止")
    used = int(counts.get("1", 0))
    if used < 0:
        raise RuntimeError("[聚灵池] 每日次数异常，停止")
    if quotas[vip] <= used:
        print("[聚灵池] VIP%s免费次数%s/%s，跳过（不消耗聚灵石或点券）" % (vip, used, quotas[vip]))
        return
    before_ticket = ticket()
    reply = checked(flow.request("scene.petHandler.petElfLottery", {"id": 1}), "免费聚灵")
    if reply.get("consume"):
        raise RuntimeError("[聚灵池] 免费聚灵出现非预期消耗：%s" % reply["consume"])
    after = refresh()
    after_used = int(((after.get("everyDaySetting") or {}).get("petElfLottery") or {}).get("1", 0))
    after_ticket = ticket()
    if after_used != used + 1 or after_ticket != before_ticket:
        raise RuntimeError("[聚灵池] 核对异常：次数%s→%s；点券%s→%s" % (used, after_used, before_ticket, after_ticket))
    print("[聚灵池] 免费聚灵成功；次数%s→%s；点券%s→%s；奖励%s" %
          (used, after_used, before_ticket, after_ticket, reply.get("give")))
    return reply


def buy_mystery_shop(flow):
    # 每成功购买一次，都重新查询并优先选择当前最高格位。
    bought = 0
    while bought < MYSTERY_BUY_TIMES:
        r = flow.request("scene.shopHandler.getMysteryShop", {})
        if not isinstance(r,dict) or r.get('code')!=200 or r.get('error'):
            raise RuntimeError('神秘商店状态未确认，停止购买')
        stall = (r.get("mysteryShop") or {}).get("stall") or {}
        if not stall:
            print("[神秘商店] 当前无在售商品，停止"); break
        sn = max(stall,key=lambda s:int(s))
        buy = flow.request("scene.shopHandler.buyMysteryShop", {"stallNum":int(sn)})
        if not isinstance(buy,dict) or buy.get('code')!=200 or buy.get('error'):
            reason=buy.get('error') if isinstance(buy,dict) else '结果未知'
            if '次数' in str(reason) and ('用完' in str(reason) or '上限' in str(reason) or '已购' in str(reason)):
                print('[神秘商店] 今日次数已用完（%s），正常停止' % reason); break
            raise RuntimeError('神秘商店购买未完成：%s；停止且不重发'%reason)
        bought += 1
        cost = (buy.get('consume') or [{}])[0].get('count')
        print('[神秘商店] 第%d次（格位%s 商品%s）花灵魂%s -> %s；下次重新查询格位' % (bought,sn,stall[sn],cost,buy.get('give')))
        time.sleep(SLEEP)
    print('[神秘商店] 共购买%d次（目标%d次）'%(bought,MYSTERY_BUY_TIMES))


def run_wanxiang(flow, info):
    """丹熏山免费次数来自共享宝箱，不使用历史 dailyCount 判断。"""
    mid = int(STAGE_OVERRIDE.get("wanxiang") or 300113)
    if mid != 300113:
        raise ValueError("万象古树目前只支持丹熏山(300113)")
    def checked(reply, action):
        if not isinstance(reply, dict) or reply.get("code") != 200 or reply.get("error"):
            raise RuntimeError("[万象古树] %s失败：%s" % (action, reply))
        return reply
    def points():
        user = checked(flow.request("connector.roleHandler.getUserInfo", {}), "读取点券").get("user") or {}
        if user.get("ticket") is None:
            raise RuntimeError("[万象古树] 无法读取点券余额")
        return int(user["ticket"])
    before_ticket = points()
    for number in range(1, min(MAX_TIMES, 2) + 1):
        info = checked(flow.request("connector.entryHandler.entry", {
            "index": RECORD_INDEX, "userAgent": flow.user_agent}), "读取存档").get("info") or {}
        record = (info.get("dungeonTreasure") or {}).get("1400600") or {}
        remain = int(record.get("remainCnt") or 0)
        if remain <= 0:
            print("[万象古树] 共享宝箱免费次数已用完，停止（不花点券）")
            break
        client_rnd = random.randint(0, 9999)
        created = checked(flow.request("scene.copyHandler.createSinglePlayerCopy", {
            "mid": mid, "rnd": client_rnd}), "创建副本")
        xor = int(created["rnd"]) ^ client_rnd
        finished = False
        bag = defaultdict(int)
        try:
            if created.get("consume"):
                raise RuntimeError("[万象古树] 免费创建出现非预期消耗：%s" % created["consume"])
            for ordinal, drop in enumerate(created.get("drops") or []):
                if drop.get("type") == "exp":
                    continue
                salt = random.randint(1, 10000)
                reply = checked(flow.request("scene.copyHandler.syncDropInfo", {
                    "index": (int(drop.get("dropIndex", ordinal)) + salt) ^ xor,
                    "key": salt ^ client_rnd}), "拾取掉落")
                _agg_drops(bag, reply.get("give"))
            chest = checked(flow.request("scene.copyHandler.getDungeonTreasureDrop", {}), "读取免费宝箱")
            if chest.get("consume") or not chest.get("drop"):
                raise RuntimeError("[万象古树] 未取得免费宝箱奖励，停止")
            for ordinal, drop in enumerate(chest["drop"]):
                if drop.get("type") == "coin" and drop.get("subType") == "exp":
                    continue
                reward = checked(flow.request("scene.copyHandler.getDungeonTreasureReward", {
                    "i": int(drop.get("dropIndex", ordinal))}), "领取宝箱奖励")
                if reward.get("consume"):
                    raise RuntimeError("[万象古树] 宝箱出现非预期消耗")
                _agg_drops(bag, reward.get("give"))
            if FIGHT_DELAY:
                time.sleep(25)
            checked(flow.request("scene.copyHandler.finishSingleCopy", {
                "win": 1, "rnd": xor, "star": 3}), "结算")
            finished = True
            after = checked(flow.request("connector.entryHandler.entry", {
                "index": RECORD_INDEX, "userAgent": flow.user_agent}), "核对存档").get("info") or {}
            after_remain = int(((after.get("dungeonTreasure") or {}).get("1400600") or {}).get("remainCnt") or 0)
            after_ticket = points()
            if after_ticket != before_ticket or after_remain != remain - 1:
                raise RuntimeError("[万象古树] 核对异常：点券%s→%s；次数%s→%s" %
                                   (before_ticket, after_ticket, remain, after_remain))
            print("[万象古树] 第%s次通关；免费次数%s→%s；点券%s；领取%s" %
                  (number, remain, after_remain, after_ticket, dict(bag)))
            with open(DROPS_LOG, "a", encoding="utf-8") as stream:
                stream.write(json.dumps({"ts": int(time.time()), "drops": {"万象古树": dict(bag)}}, ensure_ascii=False) + "\n")
        finally:
            if not finished:
                try:
                    flow.request("scene.copyHandler.finishSingleCopy", {"win": 0, "rnd": xor, "star": 0})
                except Exception:
                    pass


def run_nine_tower(flow, info):
    # 九宫玄塔全塔共享 NINE_TOWER_MAX=3 次/天; 自动选最高已解锁层, 把3次都打在这一层(预检防扣ticket)
    target = int(STAGE_OVERRIDE["nine"]) if STAGE_OVERRIDE.get("nine") \
        else pick_highest_cleared(info, _NINE_POOL)
    remain = quota_remain(info, _NINE_POOL, NINE_TOWER_MAX)
    print("[九宫玄塔] 选层=%s 今日免费剩余=%s" % (target, remain))
    _, drops = clear_dungeon(flow, info, target, "九宫玄塔·%s(最高层)" % target,
                             False, quota=(_NINE_POOL, NINE_TOWER_MAX))
    if drops:
        with open(DROPS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()),
                                "drops": {"九宫玄塔-%s" % target: drops}},
                               ensure_ascii=False) + "\n")


def run_xuanta_event(flow, info):
    """限时任务玄塔有灵：只使用一次免费九宫玄塔挑战。"""
    qid = 2014

    def task_state():
        response = flow.request("scene.questHandler.getQuestList", {})
        if not isinstance(response, dict) or response.get("code") != 200:
            print("[玄塔有灵] 读取任务失败: %s" % response)
            return None
        return next((q for q in response.get("quest", []) if q.get("id") == qid), {})

    quest = task_state()
    if quest is None:
        return False
    if not quest:
        accepted = flow.request("scene.questHandler.acceptQuest", {"qId": qid})
        if accepted.get("code") != 200 or accepted.get("error"):
            print("[玄塔有灵] 接取失败或活动未开放: %s" % (accepted.get("error") or accepted))
            return False
        quest = accepted.get("quest") or {}
        print("[玄塔有灵] 限时任务接取成功")
    if quest.get("status") == 3:
        print("[玄塔有灵] 任务奖励已领取")
        return False
    used_tower = False
    if quest.get("status") == 1:
        remain = quota_remain(info, _NINE_POOL, NINE_TOWER_MAX)
        if remain is not None and remain <= 0:
            print("[玄塔有灵] 九宫玄塔免费次数已用完，等待下次再完成")
            return False
        target = int(STAGE_OVERRIDE["nine"]) if STAGE_OVERRIDE.get("nine") \
            else pick_highest_cleared(info, _NINE_POOL)
        if target not in _NINE_POOL:
            print("[玄塔有灵] 所选九宫玄塔关卡不在任务范围内")
            return False
        count, _ = clear_dungeon(flow, info, target, "玄塔有灵·%s" % target,
                                 False, quota=(_NINE_POOL, NINE_TOWER_MAX), max_runs=1)
        used_tower = count == 1
        if not used_tower:
            print("[玄塔有灵] 未完成本次九宫玄塔挑战")
            return False
        quest = task_state()
        if quest is None:
            return used_tower
    if quest.get("status") == 2:
        reward = flow.request("scene.questHandler.commitQuest", {"qId": qid})
        if reward.get("code") == 200 and not reward.get("error"):
            verified = task_state()
            if verified and verified.get("status") == 3:
                print("[玄塔有灵] 奖励领取成功并已核对: %s" % (reward.get("give") or []))
            else:
                print("[玄塔有灵] 领奖返回成功，但任务状态未核对为已领")
        else:
            print("[玄塔有灵] 奖励领取失败: %s" % (reward.get("error") or reward))
    else:
        print("[玄塔有灵] 当前任务状态%s，暂不可领奖" % quest.get("status"))
    return used_tower


def select_demon_tower_layer(flow, info, chosen_layer):
    """按服务器要求逐组切换；返回实际选中的demonTower状态，失败则返回None。"""
    tower = info.get("demonTower") or {}
    cur = tower.get("cur") or {}
    layer = int(cur.get("layer") or 0)
    unlocked = int((tower.get("bestRecord") or {}).get("layer") or layer)
    target = unlocked if chosen_layer == 0 else int(chosen_layer)
    if not (1 <= target <= 16) or target > unlocked:
        print("[镇妖塔] 目标层段未解锁: %s（最高已解锁第%s组）" % (target, unlocked))
        return None
    for _ in range(36):
        index = int((cur.get("index") if cur.get("index") is not None else -1))
        if layer == target and index == -1:
            print("[镇妖塔] 已选 %s-%s 层" % ((layer - 1) * 10 + 1, (layer - 1) * 10 + 5))
            return tower
        next_layer = layer + (1 if target > layer else -1 if target < layer else 0)
        if not (1 <= next_layer <= 16):
            break
        reply = flow.request("scene.demonTowerHandler.switchToLayer", {"layer": next_layer})
        if reply.get("code") != 200:
            print("[镇妖塔] 切换到第%s组失败: %s" %
                  (next_layer, reply.get("error") or reply.get("code")))
            return None
        new_tower = reply.get("demonTower") or {}
        new_cur = new_tower.get("cur") or {}
        new_layer = int(new_cur.get("layer") or 0)
        if not (1 <= new_layer <= 16) or (new_layer == layer and new_cur.get("index") == cur.get("index")):
            print("[镇妖塔] 切层未推进，停止以免循环")
            return None
        print("[镇妖塔] 切层请求%s，服务器当前第%s组 index=%s" %
              (next_layer, new_layer, new_cur.get("index")))
        tower, cur, layer = new_tower, new_cur, new_layer
    print("[镇妖塔] 未能到达所选层段，停止挑战")
    return None


def run_demon_tower(flow, info):
    # 镇妖塔: info.demonTower.count = 今日【剩余挑战次数】(默认5, 不足需付费buyCount)。
    # 一次挑战最多连续5场，只消耗1次；结算掉落需再按dropIndex逐件领取。
    remain = (info.get("demonTower") or {}).get("count", 0)
    if remain is None or remain <= 0:
        print("[镇妖塔] 今日挑战次数为0, 跳过(不花点券)")
        return
    chosen = select_demon_tower_layer(flow, info, DEMON_TOWER_TARGET_LAYER)
    if chosen is None:
        return
    remain = chosen.get("count", remain)
    print("[镇妖塔] 今日剩余挑战次数=%s, 开始一次爬塔" % remain)
    before_bag = info.get("bag") or {}
    before_soul = int(((before_bag.get("item") or {}).get("101026006") or {}).get("count", 0))
    before_runes = len(before_bag.get("rune") or {})
    n = 0
    grand = {}
    for _ in range(MAX_TIMES):
        b = flow.request("scene.demonTowerHandler.beginChallenge", {"type": 0})
        if isinstance(b, dict) and b.get("error"):
            print("[镇妖塔] 停止: %s" % b.get("error")); break
        e = flow.request("scene.demonTowerHandler.endChallenge",
                         {"win": 1, "maxCombo": 9, "killMonsterCnt": 66,
                          "useMagicWeaponCnt": 0, "useBossCardCnt": 0})
        if isinstance(e, dict) and e.get("error"):
            print("[镇妖塔] 结算失败: %s" % e.get("error")); break
        bag = defaultdict(int)
        claim_failed = False
        for drop in e.get("give") or []:
            index = drop.get("dropIndex")
            if index is None:
                print("[镇妖塔] 掉落缺少拾取序号，停止:", drop)
                claim_failed = True
                break
            picked = flow.request("scene.demonTowerHandler.getReward", {"index": index})
            if picked.get("code") != 200:
                print("[镇妖塔] 拾取失败，序号%s: %s" %
                      (index, picked.get("error") or picked.get("code")))
                claim_failed = True
                break
            _agg_drops(bag, picked.get("give"))
        cur = (e.get("demonTower") or {}).get("cur", {})
        n += 1
        print("[镇妖塔] 第%d场过 layer=%s index=%s 已领取=%s"
              % (n, cur.get("layer"), cur.get("index"), dict(bag)))
        if bag:
            grand["镇妖塔-第%d场" % n] = dict(bag)
        if claim_failed:
            break
        time.sleep(SLEEP)
    fresh = flow.request("connector.entryHandler.entry",
                         {"index": RECORD_INDEX, "userAgent": flow.user_agent}).get("info") or {}
    new_remain = (fresh.get("demonTower") or {}).get("count")
    new_cur = (fresh.get("demonTower") or {}).get("cur") or {}
    after_bag = fresh.get("bag") or {}
    after_soul = int(((after_bag.get("item") or {}).get("101026006") or {}).get("count", 0))
    after_runes = len(after_bag.get("rune") or {})
    print("[镇妖塔] 本次共过 %d 场；挑战次数 %s→%s；进度 layer=%s index=%s"
          % (n, remain, new_remain, new_cur.get("layer"), new_cur.get("index")))
    print("[镇妖塔] 背包核对: 符魂 %s→%s，灵符 %s→%s"
          % (before_soul, after_soul, before_runes, after_runes))
    if grand:
        with open(DROPS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "drops": grand},
                               ensure_ascii=False) + "\n")


PET_FREE_RESET_MAX = 1   # 灵宠试炼每天免费重置次数(resetNumber=1); 再重置 resetTicket=400, 不做


def _pet_layer_stages(layer):
    # 每个"周天"6关: 周天L 的关卡id = 6*(L-1)+1 .. 6*L
    return list(range(6 * (layer - 1) + 1, 6 * layer + 1))


def _pet_clear_layer(flow, info, layer, tag=""):
    # 顺序通关当前周天内今日未打(dailyCnt=0)的关卡, 返回通关数
    pds = info.setdefault("petDungeonSetting", {})
    hist = pds.setdefault("dungeonHistory", {})
    n = 0
    for sid in _pet_layer_stages(layer):
        if (hist.get(str(sid)) or {}).get("dailyCnt", 0) > 0:
            continue
        b = flow.request("scene.petHandler.beginChallengeDungeon",
                         {"petDungeonId": sid})
        if isinstance(b, dict) and b.get("error"):
            print("[灵宠试炼%s] 第%d关停止: %s" % (tag, sid, b.get("error"))); break
        e = flow.request("scene.petHandler.endChallengeDugeon", {"win": 1})
        if isinstance(e, dict) and e.get("error"):
            print("[灵宠试炼%s] 第%d关结算失败: %s" % (tag, sid, e.get("error"))); break
        hist.setdefault(str(sid), {})["dailyCnt"] = 1
        n += 1
        print("[灵宠试炼%s] 周天%d 第%d关通关: %s"
              % (tag, layer, sid, e.get("give") or "ok"))
        time.sleep(SLEEP)
    return n


def run_pet_tower(flow, info):
    # 灵宠试炼: 每周天6关, 每天自然打一轮(dailyCnt); 还可【免费重置1次】再打一轮,
    # 超出免费重置要 resetTicket=400, 用 everyDaySetting.petDungeonResetCnt 预检, 绝不付费重置。
    pds = info.setdefault("petDungeonSetting", {})
    layer = int(pds.get("layerId") or 1)
    print("[灵宠试炼] 当前=第%d周天(关卡%s), 先打今日未通关卡"
          % (layer, _pet_layer_stages(layer)))
    total = _pet_clear_layer(flow, info, layer)

    eds = info.setdefault("everyDaySetting", {})
    reset_used = int(eds.get("petDungeonResetCnt", 0) or 0)
    if reset_used >= PET_FREE_RESET_MAX:
        print("[灵宠试炼] 今日免费重置已用(%d/%d), 不再重置(避免花ticket)"
              % (reset_used, PET_FREE_RESET_MAX))
    else:
        hist = pds.setdefault("dungeonHistory", {})
        frontier = next((s for s in _pet_layer_stages(layer)
                         if (hist.get(str(s)) or {}).get("dailyCnt", 0) == 0),
                        _pet_layer_stages(layer)[-1])
        r = flow.request("scene.petHandler.resetPetChallengeDungeon",
                         {"petDungeonId": frontier})
        err = r.get("error") if isinstance(r, dict) else None
        if err:
            print("[灵宠试炼] 免费重置失败(不重试, 避免付费): %s" % err)
        else:
            if isinstance(r, dict):
                if r.get("petDungeonSetting"):
                    info["petDungeonSetting"] = r["petDungeonSetting"]
                if r.get("everyDaySetting"):
                    eds.update(r["everyDaySetting"])
            print("[灵宠试炼] 免费重置成功(今日 %d/%d), 再打一轮"
                  % (int(eds.get("petDungeonResetCnt", reset_used + 1) or reset_used + 1),
                     PET_FREE_RESET_MAX))
            total += _pet_clear_layer(flow, info, layer, tag="-重置")
    print("[灵宠试炼] 第%d周天 本次共通关 %d 关" % (layer, total))


def claim_dragon_treasure_tasks(flow, info):
    """Claim only completed Dragon Treasure quests (TaskDataVo label 91 / status 2)."""
    if not isinstance(info, dict) or not isinstance(info.get("dragonTreasure"), dict):
        print("[龙宫寻宝] 当前存档没有活动数据，跳过")
        return 0
    active_id = info["dragonTreasure"].get("activeId")
    if not active_id:
        print("[龙宫寻宝] 当前没有开放中的活动，跳过")
        return 0
    quests = info.get("quest")
    if not isinstance(quests, list):
        print("[龙宫寻宝] 服务器未返回任务列表，跳过")
        return 0

    # The game groups these quests under label 91; status 2 is the claim button.
    ready = []
    for quest in quests:
        if not isinstance(quest, dict):
            continue
        try:
            qid = int(quest.get("id", 0))
            status = int(quest.get("status", 0))
        except (TypeError, ValueError):
            continue
        if str(qid).startswith("91") and status == 2:
            ready.append(qid)

    if not ready:
        print("[龙宫寻宝] 没有已完成待领取的任务")
        return 0

    claimed = 0
    for qid in ready:
        try:
            result = flow.request("scene.questHandler.commitQuest", {"qId": qid})
        except Exception as e:
            print("[龙宫寻宝] 任务%s领取异常(不重试): %s" % (qid, e))
            continue
        if not isinstance(result, dict):
            print("[龙宫寻宝] 任务%s返回格式异常(不重试)" % qid)
            continue
        error = result.get("error")
        if error:
            print("[龙宫寻宝] 任务%s领取失败: %s" % (qid, error))
            continue
        claimed += 1
        give = result.get("give") or result.get("drops") or []
        print("[龙宫寻宝] 任务%s奖励已领取: %s" % (qid, give))
        time.sleep(SLEEP)
    print("[龙宫寻宝] 已领取%d/%d个已完成任务" % (claimed, len(ready)))
    return claimed

def claim_liveness(flow):
    # 1. 先领每日活跃任务奖励（990001~990032），用 questHandler.commitQuest
    n_task = 0
    for qid in range(990001, 990033):
        r = flow.request("scene.questHandler.commitQuest", {"qId": qid})
        err = r.get("error") if isinstance(r, dict) else None
        if err:
            continue  # 没完成/已领，跳过
        give = r.get("give") or r.get("drops") or r
        print("[活跃任务] id%s 领取成功: %s" % (qid, give))
        n_task += 1
        time.sleep(SLEEP)
    print("[活跃任务] 共领 %d 个任务奖励" % n_task)

    # 2. 再领里程碑奖励（30/60/90/120/150点 + 每周450/900点）
    for rid in [1, 2, 3, 4, 5, 11, 12]:
        r = flow.request("scene.livenessHandler.getReward", {"rewardId": rid})
        err = r.get("error") if isinstance(r, dict) else None
        if err:
            print("[活跃里程碑] id%s 未到点: %s" % (rid, err)); continue
        print("[活跃里程碑] id%s 领取成功: %s" % (rid, r.get("give") or r.get("drops") or r))
        time.sleep(SLEEP)


def accept_daily_tasks(flow, info):
    """按 GUI 自选列表接取精英每日任务（taskClass=2）。"""
    selected = list(dict.fromkeys(int(qid) for qid in DAILY_TASK_SELECTED_IDS))
    if not selected:
        print("[日常任务] 未选择要接取的精英每日任务")
        return 0
    tasks = _elite_quest_map(flow)
    lookup = {task["id"]: (mid, task) for mid, entries in tasks.items() for task in entries}
    accepted = 0
    quota = quota_from_info(info)
    print("[日常任务] VIP%d 今日接取%d/%d次，剩余%d次" %
          (quota["vip"], quota["used"], quota["limit"], quota["remaining"]))
    for qid in selected:
        if qid not in lookup:
            print("[日常任务] 任务%s 没有对应精英关卡配置" % qid)
            continue
        mid, task = lookup[qid]
        if task.get("status") != 0:
            print("[日常任务] 精英关%s 任务%s 状态%s，跳过接取" % (mid, qid, task.get("status")))
            continue
        if quota["remaining"] <= 0:
            print("[日常任务] 今日接取机会已用完，停止接取")
            break
        result = flow.request("scene.questHandler.acceptQuest", {"qId": qid})
        if not isinstance(result, dict) or result.get("error") or result.get("code") != 200:
            print("[日常任务] 精英关%s 任务%s 接取失败: %s" % (mid, qid, result))
            continue
        quest = result.get("quest") or {}
        if quest.get("id") != qid or quest.get("taskClass") != 2 or quest.get("status") != 1:
            print("[日常任务] 精英关%s 任务%s 接取返回状态异常: %s" % (mid, qid, quest))
            continue
        accepted += 1
        quota["used"] += 1
        quota["remaining"] -= 1
        if isinstance(result.get("everyDaySetting"), dict):
            info["everyDaySetting"] = result["everyDaySetting"]
            quota = quota_from_info(info)
        print("[日常任务] 精英关%s 任务%s 接取成功" % (mid, qid))
        time.sleep(SLEEP)
    print("[日常任务] 本次接取%d项" % accepted)
    return accepted


def run_apprenticeship(flow, info, *, learn=True, teach=True):
    """Read current relationship and consume only the free daily actions."""
    result = flow.request("scene.apprenticeshipHandler.getApprenticeshipData", {})
    if not isinstance(result, dict) or result.get("error") or result.get("code", 200) != 200:
        print("[师徒] 读取状态失败: %s" % result)
        return
    daily = info.setdefault("everyDaySetting", {})
    if isinstance(result.get("everyDaySetting"), dict):
        daily.update(result["everyDaySetting"])

    students = result.get("my")
    teacher = result.get("master")
    if teach:
        pupil_count = len((students or {}).get("apprentice") or {}) if isinstance(students, dict) else 0
        if pupil_count and int(daily.get("giveLessonCnt") or 0) < 1:
            response = flow.request("scene.apprenticeshipHandler.giveLessons", {})
            if isinstance(response, dict) and not response.get("error") and response.get("code", 200) == 200:
                print("[师徒] 授课成功")
                daily.update(response.get("everyDaySetting") or {})
            else:
                print("[师徒] 授课失败: %s" % response)
        else:
            print("[师徒] 授课跳过：%s" % ("今日已授课" if pupil_count else "当前没有徒弟"))

    if learn:
        if not isinstance(teacher, dict):
            print("[师徒] 学艺跳过：当前没有师父")
        elif int(daily.get("personFreeLearnNum") or 0) >= 1:
            print("[师徒] 学艺跳过：今日免费次数已用完")
        else:
            pupils = teacher.get("apprentice") or {}
            liking = sum(int((entry or {}).get("liking") or 0) for entry in pupils.values()) if isinstance(pupils, dict) else 0
            tier = 1 if liking <= 499 else 2 if liking <= 1249 else 3
            response = flow.request("scene.apprenticeshipHandler.getBuffer", {"type": 0, "id": tier})
            if isinstance(response, dict) and not response.get("error") and response.get("code", 200) == 200:
                print("[师徒] 免费学艺成功（档位%d）" % tier)
                daily.update(response.get("everyDaySetting") or {})
            else:
                print("[师徒] 免费学艺失败: %s" % response)


def run_extension_daily(flow, module_name, action):
    try:
        import importlib
        module = importlib.import_module(module_name)
        fresh = flow.request('connector.entryHandler.entry',
                             {'index': RECORD_INDEX, 'userAgent': flow.user_agent})
        if fresh.get('code', 200) != 200 or fresh.get('error'):
            raise RuntimeError(str(fresh))
        current = fresh.get('info', fresh)
        kwargs = {'apply': True} if action in ('like_in_shanfa', 'do_reward') else {}
        ok, message, _ = getattr(module, action)(flow, current, **kwargs)
        print(('[OK] ' if ok else '[--] ') + message)
    except Exception as exc:
        print('[扩展日常] %s 执行失败：%s' % (module_name, exc))


def main():
    flow, info = login()
    if RUN_FLUSHOU:
        run_flushou(flow, info)
    if RUN_DEVOTE:
        do_devote(flow)
    if RUN_SHANFA_LIKE:
        run_extension_daily(flow, 'shanfa_run', 'like_in_shanfa')
    if RUN_APPRENTICE_LEARN or RUN_APPRENTICE_TEACH:
        try:
            run_apprenticeship(flow, info, learn=RUN_APPRENTICE_LEARN,
                               teach=RUN_APPRENTICE_TEACH)
        except Exception as exc:
            print("[师徒] 操作异常，继续其他任务: %s" % exc)
    if RUN_ARENA:
        try:
            battle_jjc(flow, info)
        except Exception as exc:
            print("[竞技场] 操作异常，继续其他任务: %s" % exc)
    if RUN_PET_ARENA:
        try:
            battle_pet_arena(flow, info)
        except Exception as exc:
            print("[斗宠大会] 操作异常，继续其他任务: %s" % exc)
    if RUN_MYSTERY_SHOP:
        buy_mystery_shop(flow)
    if RUN_CARD_CAVE:
        run_card_cave(flow, info)
    if RUN_HALO:
        run_halo(flow, info)
    if RUN_MANHUANG:
        run_manhuang(flow, info)
    if RUN_FOREST:
        run_forest(flow, info)
    if RUN_ELITE and RUN_ACCEPT_DAILY_TASKS:
        accept_daily_tasks(flow, info)
    if RUN_ELITE or RUN_SKY or RUN_TEN or MAIN_CUSTOM_MID:
        run_dungeons(flow, info)
    # 精英翻牌优先计入今日强化石，再读取服务器状态补齐；不叠加本地次数。
    if RUN_ELITE_STONE:
        try:
            from elite_stone_tool import run as run_elite_stone
            from teacher_trial import enter as refresh_stone_info
            os.environ['ZM5_STONE_SELL_PASSWORD'] = os.environ.get('ZM5_ELITE_SELL_PASSWORD', '')
            stone_result = run_elite_stone(flow, RECORD_INDEX)
            print('[万能强化石日常] %s；今日%s/4' %
                  (stone_result['status'], stone_result['after']['today']))
            stone_info = refresh_stone_info(flow, RECORD_INDEX)
            info.clear()
            info.update(stone_info)
        except Exception as exc:
            print('[万能强化石日常] 已停止本轮日常：%s' % exc)
            return
    # 万象古树/丹熏山(mid=300113, 独立副本, 每天免费2次)
    if RUN_WANXIANG:
        run_wanxiang(flow, info)
    if RUN_NIGHTMARE_SKY:
        try:
            from nightmare_sky import run as run_nightmare_sky
            run_nightmare_sky(flow, info, RECORD_INDEX)
        except Exception as exc:
            print('[噩梦天树王] 异常停止本项：%s' % exc)
    if RUN_ACTIVITY:
        run_activity(flow, info)
    xuanta_used_tower = run_xuanta_event(flow, info) if RUN_XUANTA_EVENT else False
    if RUN_NINE_TOWER and not xuanta_used_tower:
        run_nine_tower(flow, info)
    elif RUN_NINE_TOWER and xuanta_used_tower:
        print("[九宫玄塔] 玄塔有灵已挑战一次，本轮跳过普通九宫玄塔刷取")
    if RUN_DEMON_TOWER:
        run_nightmare(flow, info)
    if RUN_DEMON_TOWER2:
        run_demon_tower(flow, info)
    if RUN_PET_TOWER:
        run_pet_tower(flow, info)
    if RUN_STAR_MAZE:
        try:
            from star_maze import run_star_maze
            run_star_maze(flow, info, RECORD_INDEX)
        except Exception as _e:
            print('[星斗幻境] 异常跳过: %r' % (_e,))
    if RUN_MID_AUTUMN:
        run_mid_autumn(flow, info)
    if RUN_JIN_QIU:
        run_jin_qiu(flow, info)
    if RUN_CLOUD_LADDER:
        run_cloud_ladder(flow, info)
    if RUN_DOG_CARD:
        from union_boss_batch import run_dog
        run_dog({}, RECORD_INDEX, '双十一免费抽狗卡', flow=flow)
    if RUN_CLIMB_HIGH:
        try:
            from climb_high import run as run_climb_high
            run_climb_high(flow, info, RECORD_INDEX, CLIMB_HIGH_SCORE)
        except Exception as exc:
            print('[重阳采菊] 异常停止本项：%s' % exc)
    if RUN_MAGIC_CRYSTAL:
        try:
            from crystal_manual import run as run_magic_crystal
            from teacher_trial import enter as refresh_crystal_info
            result = run_magic_crystal(flow, RECORD_INDEX)
            print('[魔法水晶球] 本项结束：%s；今日%s个' %
                  (result['status'], result.get('after', {}).get('today', '?')))
            refreshed = refresh_crystal_info(flow, RECORD_INDEX)
            info.clear()
            info.update(refreshed)
        except Exception as exc:
            print('[魔法水晶球] 本项停止：%s' % exc)
    if RUN_MAGIC_RABBIT:
        from rabbit_activity import run as run_magic_rabbit
        run_magic_rabbit(flow, info, RECORD_INDEX)
    if RUN_RELIC_TREASURE:
        run_relic_treasure(flow)
    if RUN_STOVE:
        run_stove(flow, info)
    if RUN_FREE_MAZE:
        try:
            from free_maze_daily import run_free_maze
            run_free_maze(flow, FREE_MAZE_MODE, UID, FREE_MAZE_TARGET_CODE, FREE_MAZE_FINGERPRINT, wait=FREE_MAZE_WAIT)
        except Exception as _e:
            print("[迷宫活跃] 异常跳过: %s" % _e)
    if RUN_CELEBRATION or RUN_CELEBRATION_ONLINE:
        from celebration_daily import run as run_celebration_daily
        scope = 'all' if RUN_CELEBRATION and RUN_CELEBRATION_ONLINE else ('tasks' if RUN_CELEBRATION else 'online')
        run_celebration_daily(flow, info, RECORD_INDEX, scope=scope, allow_spirit_backup=CELEBRATION_SPIRIT_BACKUP, password=os.environ.get('ZM5_CELEBRATION_PASSWORD',''))
    if RUN_FAIRY_REWARD:
        from fairy_daily import run as run_fairy_daily
        run_fairy_daily(flow, RECORD_INDEX, FAIRY_DAILY_POSITIONS, apply=True, preferences=FAIRY_DAILY_PREFERENCES)
    if RUN_BLACK_MARKET_DAILY:
        try:
            from black_market_daily import run as run_black_market_daily
            run_black_market_daily(flow, RECORD_INDEX, account=_ACC)
        except Exception as exc:
            print('[黑市日常] 本项停止：%s；未自动重试' % exc, flush=True)
    if RUN_MY_DAILY_FUN:
        from fun_batch_runner import execute as run_my_daily_fun
        run_my_daily_fun(flow,{'uid':str(UID),'username':USERNAME},RECORD_INDEX,MY_DAILY_FUN_JOBS)
    # 完成任务在前，独立领奖在后；活跃积分与里程碑固定为最后一项。
    if RUN_WHITE_DRAGON:
        from new_player_daily import run as run_new_player_daily
        run_new_player_daily(flow, info, RECORD_INDEX,
                             os.environ.pop('ZM5_WHITE_DRAGON_PASSWORD', '') or '')
    if RUN_GROWTH_BUFF:
        claim_growth_buff(flow, info)
    if RUN_LANDING_NEW:
        claim_landing_reward(flow, info, legacy=False)
    if RUN_LANDING_LEGACY:
        claim_landing_reward(flow, info, legacy=True)
    if RUN_NOVICE_GIFT:
        claim_new_player_rewards(flow, info, claim=True)
    if RUN_NOVICE_CHECK:
        claim_new_player_rewards(flow, info, claim=False)
    if RUN_WEEKEND_BUFF:
        claim_weekend_online(flow, info, part='buff')
    if RUN_WEEKEND_ONLINE:
        claim_weekend_online(flow, info, part='rest')
    if RUN_GROWTH_BUY_VIP:
        buy_growth_vip(flow, info)
    if RUN_GROWTH_ACCEPTALL:
        accept_all_growth_quests(flow, info, None)
    if RUN_GROWTH_FREE:
        claim_growth_dungeon_tasks(flow, info, None)
        claim_growth_manhuang_tasks(flow, info, None)
    if RUN_GROWTH_ACCEPT:
        accept_all_growth_quests(flow, info)
    if RUN_GROWTH_DUNGEON:
        claim_growth_dungeon_tasks(flow, info)
    if RUN_GROWTH_MANHUANG:
        claim_growth_manhuang_tasks(flow, info)
    if RUN_GROWTH_HALO:
        claim_growth_halo_tasks(flow, info)
    if RUN_GROWTH_DAN:
        claim_growth_dan_tasks(flow, info)
    if RUN_GROWTH_POINT:
        claim_growth_point_rewards(flow, info)
    if RUN_GROWTH_CLAIM_ONLY:
        claim_growth_all_ready(flow, info)
    if RUN_VIP_GIFT:
        claim_vip_gift(flow, info)
    if RUN_ARENA_SIGNUP:
        signup_arena(flow, 'arena')
    if RUN_PET_ARENA_SIGNUP:
        signup_arena(flow, 'petArena')
    for enabled, module_name, action in [
        (RUN_ARENA_REWARD, 'arena_reward', 'do_claim'),
        (RUN_PET_ARENA_REWARD, 'pet_arena_reward', 'do_claim'),
        (RUN_MONTHCARD_REWARD, 'monthcard_run', 'do_claim'),
        (RUN_WISH_POOL_REWARD, 'wish_pool_run', 'claim_prev'),
        (RUN_WISH_POOL_RANDOM and WISH_POOL_MODE=='random', 'wish_pool_random', 'do_wish'),
    ]:
        if enabled:
            run_extension_daily(flow, module_name, action)
    if RUN_DRAGON_TREASURE_TASKS:
        claim_dragon_treasure_tasks(flow, info)
    if RUN_PERMANENT_FASHION:
        claim_fashion_rewards(flow, info)
    if RUN_FASHION_SIGNIN:
        claim_fashion_signin(flow, info)
    if RUN_FASHION_ONLINE:
        claim_fashion_online(flow, info)
    if RUN_FASHION_SHOP:
        _shop_qty = RUN_FASHION_SHOP_QTY if isinstance(RUN_FASHION_SHOP_QTY, dict) else {}
        buy_fashion_shop(flow, info,
                         {int(k): int(v) for k, v in _shop_qty.items() if int(v) > 0} or None)
    if RUN_LIVENESS:
        fresh = flow.request('connector.entryHandler.entry', {'index': RECORD_INDEX, 'userAgent': flow.user_agent})
        if fresh.get('code', 200) != 200 or fresh.get('error') or not isinstance(fresh.get('info'), dict):
            raise RuntimeError('最终活跃领奖前刷新存档失败，未发送领取')
        print('[每日活跃] 本批其它任务结束，最后领取任务积分和里程碑奖励')
        claim_liveness(flow)
    flow.disconnect()


if __name__ == "__main__":
    main()
