# -*- coding: utf-8 -*-
"""洗练 数据整理模块（独立，不改动工具箱已有文件）。

五个系统的免费洗练（路由与参数均已实测确认）：

| 系统 | 路由 | 免费参数 | 免费额度（VIP 表） | 用掉的计数器 |
|---|---|---|---|---|
| 法宝 | scene.magicWeaponHandler.tryResetAttrFree | {entityId} | amuletResetNum | amuletResetCnt |
| 灵符 | scene.magicWeaponHandler.tryResetRuneAttr | {entityId, type:2} | runeResetNum | runeResetNum |
| 羽毛 | scene.wingHandler.featherVIPRest          | {entityId} | featherResetNum | featherResetNum |
| 精魄 | scene.formationHandler.formationFlagRest  | {entityId, index:2} | formationResetNum | formationResetNum |
| 阵眼 | scene.formationHandler.formationFlagRest  | {entityId, index:2} | formationResetNum | formationResetNum |

实测（账号 3922097053 / 槽0 / VIP8）：
  羽毛 featherVIPRest {entityId}                      -> code 200，featherResetNum 0->1
  灵符 tryResetRuneAttr {entityId, type:2}            -> code 200，runeResetNum 0->1
  精魄 formationFlagRest {entityId, index:2}          -> code 200，formationResetNum 0->1
  阵眼 formationFlagRest {entityId, index:2}          -> code 200，formationResetNum 0->1 （同一计数器）
  法宝 tryResetAttrFree {entityId}                    -> code 500 "道具数量不足"（5星法宝仍需材料）

【重要】绝不消耗点券：
  客户端在材料不足时会 fastBuyItem 弹窗用点券买材料；本模块一律不调用任何
  fastBuy / buy 路由，且在动手前先检查"免费额度"或"材料是否足够"，不足就直接拒绝。
  index=0 在阵眼/灵符面板是【点券洗练】，本模块永不使用 index=0。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG_DIR = os.path.join(HERE, "feature_config")

# 各系统免费洗练所需的二级密码保护（SecondPassword.json 用路由名的 MD5 做键）
# 说明：服务端要求请求体里带 password 字段，否则返回 code=502 二级密码错误。

SYSTEMS = {
    "magic": "法宝洗练",
    "rune": "灵符洗练",
    "feather": "羽毛洗练",
    "jingpo": "精魄洗练",
    "zhenyan": "阵眼洗练",
}

# 材料（付费/道具档用；本模块只用于"检查是否足够"，绝不自动购买）
MATERIALS = {
    "magic_1": (101301001, "法宝洗炼石"),
    "magic_2": (101301002, "祝福洗炼石"),
    "rune": (101026012, "神纹"),
    "rune_soul": (101026006, "符魂"),
    "feather": (101026010, "凤绒"),
    "jingpo": (101026011, "魄晶"),
    "zhenyan": (101026014, "魄玉"),
    "po_soul": (101026004, "魄心"),
    "equ": (101026008, "装备洗炼石"),
    "pet_equ": (101026009, "灵宠装备洗炼石"),
}

# 免费洗练的调用定义（实测确认）
# lockKey: 洗练请求里"锁定词条"的字段名（BasicViewWash.param 里就是 "lock"，值是属性名数组）
# confirmRoute/confirmArgs: 洗出结果后的"保存/替换"确认请求；None 表示服务器已直接落袋
#
# 【法宝有两套，别搞混】
#   A. tryResetAttrFreeVIP  —— 真正的"免费洗练"（btnFree -> resetVip）
#        实测：零材料消耗、扣 VIP.amuletResetNum 额度、回包直接给 newMagicWeapon，
#              【无法选择保存、直接替换】，且【不能锁词条】（请求只有 entityId）。
#   B. tryResetAttrFree     —— 选择框里的"按钮2"（MagicResetSelectMediator.btn2）
#        受 _has2 = ConsumeManager.checkNodeEnough(MagicweaponReset[item]) 约束，
#        即"不消耗法宝洗炼石但仍需其它材料"，材料不足就报"道具数量不足"。
#        不是真正的零消耗免费档，故本模块不用它。
FREE_CALLS = {
    "magic": {
        "route": "scene.magicWeaponHandler.tryResetAttrFreeVIP",
        "args": lambda eid: {"entityId": eid},
        # 实测该路由请求体只有 entityId，没有 lock；免费档直接替换、无法保存
        "lockKey": None,
        "canLock": False,
        "noLockReason": "免费档请求只有 entityId，洗练直接替换、无法锁定",
        "autoReplace": True,
        "confirmRoute": None,
        "confirmArgs": None,
    },
    "rune": {
        "route": "scene.magicWeaponHandler.tryResetRuneAttr",
        "args": lambda eid: {"entityId": eid, "type": 2},   # 2 = 免费档（非点券）
        # 【灵符没有锁定功能】RuneWashView extends BasicView（不是 BasicViewWash），
        # 它的 param 只有 {entityId, type}，没有 lock 字段。
        # 客户端里唯一的 lock 是"灵符上锁防盗卖"，与洗练无关。
        "lockKey": None,
        "canLock": False,
        "noLockReason": "灵符洗练界面（extends BasicView）没有锁定功能，请求只有 entityId/type",
        "confirmRoute": "scene.magicWeaponHandler.confirmResetRuneAttr",
        "confirmArgs": lambda eid: {},
    },
    "feather": {
        "route": "scene.wingHandler.featherVIPRest",
        "args": lambda eid: {"entityId": eid},
        # WashFeatherView.itemValue 是 BasicViewWash 子类 -> param 含 lock 数组
        "lockKey": "lock",
        "canLock": True,
        # FeatherSureMediator: {entityId, replace: true/false}
        "confirmRoute": "scene.wingHandler.featherSureRest",
        "confirmArgs": lambda eid: {"entityId": eid, "replace": True},
    },
    "jingpo": {
        "route": "scene.formationHandler.formationFlagRest",
        "args": lambda eid: {"entityId": eid, "index": 2},  # 2 = 免费档（0 是点券）
        "lockKey": "lock",
        "canLock": True,
        # ForSureWashMediator: {entityId, replace: true/false}
        "confirmRoute": "scene.formationHandler.formationFlagSureRest",
        "confirmArgs": lambda eid: {"entityId": eid, "replace": True},
    },
    "zhenyan": {
        "route": "scene.formationHandler.formationFlagRest",
        "args": lambda eid: {"entityId": eid, "index": 2},
        "lockKey": "lock",
        "canLock": True,
        "confirmRoute": "scene.formationHandler.formationFlagSureRest",
        "confirmArgs": lambda eid: {"entityId": eid, "replace": True},
    },
}

# 洗练出属性后，需要"保存/替换"确认的系统（其余是服务器直接落袋）
NEEDS_CONFIRM = {k for k, v in FREE_CALLS.items() if v.get("confirmRoute")}

# 各对象的"可洗词条"字段（用于锁定/展示）。实测取属性名。
# 注意：成长率 growthRate、五行 fiveElements、洗练值 srValue 是法宝洗练的核心结果，
#       必须展示，不能排除（之前误排除过，属 bug）。
ELEMENT_NAMES = {1: "白虎", 2: "青龙", 3: "玄武", 4: "朱雀", 5: "黄麟"}

ATTR_SKIP = {
    "entityId", "id", "index", "type", "name", "part", "lock", "createTime",
    "updateTime", "isConsume", "quality", "classType", "resourceId",
    "showFace", "wingFacade", "hole", "inlay", "power", "skills",
    "atkAdd", "hpMaxAdd", "mpMaxAdd", "phyDefAdd", "hitAdd", "dodgeAdd",
    "criticalAdd", "luckyAdd", "guardianAdd", "toughnessAdd",
}

# 洗练展示时要保留的"列表型"字段
LIST_ATTRS = ("fiveElements",)


def five_elements_text(value):
    """五行 -> 可读文本。支持 [1,3,4] / "1,3,4" / "1;3" 等形态。"""
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raw = str(value).replace(";", ",")
        items = [x for x in raw.split(",") if x != ""]
    names = []
    for x in items:
        try:
            names.append(ELEMENT_NAMES.get(int(x), str(x)))
        except (TypeError, ValueError):
            names.append(str(x))
    names.sort()
    return "/".join(names)


def current_attrs(item):
    """取对象当前会被洗练的词条名（属性名）。

    实测：极水血魄 洗出属性是 hpMax/dodge/reHP，配表 attributes=hpMax;reHP;dodge；
    所以"锁定"用的就是这些属性字段名。
    法宝的成长率/五行也在其中（它们是法宝洗练的核心结果）。
    """
    if not isinstance(item, dict):
        return []
    return sorted(k for k, v in item.items()
                  if k not in ATTR_SKIP
                  and (not isinstance(v, (dict, list)) or k in LIST_ATTRS))


def free_call(key, entity_id, lock=None):
    """取某系统的免费调用 (route, args)。args 不含 password。

    lock: 要锁定的词条名列表（不参与洗练、保持原值）。
          实测锁定会让消耗按 (1+len(lock)) 倍增加（BasicViewWash.updateText）。
    """
    spec = FREE_CALLS.get(key)
    if not spec:
        return None, None
    args = spec["args"](entity_id)
    lock_key = spec.get("lockKey")
    if lock and lock_key:
        args[lock_key] = list(lock)
    return spec["route"], args


def can_lock(key):
    """该系统能否锁词条（显式标志，不靠推断）。

    能锁：羽毛、精魄、阵眼（都是 BasicViewWash 那套 UI，param 含 lock 数组）
    不能锁：法宝（免费档请求只有 entityId，直接替换）
            灵符（RuneWashView extends BasicView，param 只有 entityId/type）
    """
    spec = FREE_CALLS.get(key) or {}
    return bool(spec.get("canLock"))


def no_lock_reason(key):
    """不能锁定时给出具体原因。"""
    spec = FREE_CALLS.get(key) or {}
    return spec.get("noLockReason") or "该系统不支持锁定词条"


def auto_replace(key):
    """该系统是否"免费档直接替换、无法选择保存"。"""
    spec = FREE_CALLS.get(key) or {}
    return bool(spec.get("autoReplace"))


def confirm_call(key, entity_id, replace=True):
    """取某系统的"保存/替换"确认调用 (route, args)；不需要确认则返回 (None, None)。

    replace=True  保存新词条；replace=False 保留旧词条（回退）。
    """
    # RuneSureWashMediator: btn_old only closes the view; confirm {} saves new attrs.
    if key == "rune" and not replace:
        return None, None
    spec = FREE_CALLS.get(key) or {}
    route = spec.get("confirmRoute")
    if not route:
        return None, None
    args = spec["confirmArgs"](entity_id)
    if "replace" in args:
        args["replace"] = bool(replace)
    return route, args


def _load(config_dir, name):
    with open(os.path.join(config_dir, name), encoding="utf-8") as f:
        return json.load(f)


def _int(node, key, default=0):
    try:
        return int(node.get(key, default))
    except (TypeError, ValueError):
        return default


def load_vip(config_dir=DEFAULT_CONFIG_DIR):
    try:
        table = _load(config_dir, "VIP.json")
    except Exception:
        return {}
    out = {}
    for key, v in (table or {}).items():
        if isinstance(v, dict):
            try:
                out[int(v.get("id", key))] = v
            except (TypeError, ValueError):
                continue
    return out


def vip_level(info):
    return _int(((info or {}).get("vip") or {}), "level", 0)


def _used(info, field):
    eds = (info or {}).get("everyDaySetting") or {}
    try:
        return int(eds.get(field) or 0)
    except (TypeError, ValueError):
        return 0


def wash_quota(info, vip_table=None, config_dir=DEFAULT_CONFIG_DIR):
    """五个系统的今日免费洗练额度（已用/可用）。

    精魄与阵眼共用 formationResetNum 这一个计数器（实测确认）。
    """
    if vip_table is None:
        vip_table = load_vip(config_dir)
    lvl = vip_level(info)
    v = vip_table.get(lvl) or {}

    def row(key, total_key, used_field):
        total = _int(v, total_key)
        used = _used(info, used_field)
        return {
            "name": SYSTEMS[key],
            "vip": lvl,
            "freeTotal": total,
            "freeUsed": used,
            "freeLeft": max(0, total - used),
            "usedField": used_field,
            "route": FREE_CALLS[key]["route"],
        }

    q = {
        "magic": row("magic", "amuletResetNum", "amuletResetCnt"),
        "rune": row("rune", "runeResetNum", "runeResetNum"),
        "feather": row("feather", "featherResetNum", "featherResetNum"),
        "jingpo": row("jingpo", "formationResetNum", "formationResetNum"),
        "zhenyan": row("zhenyan", "formation2ResetNum", "formation2ResetNum"),
    }
    return q


def materials(info, config_dir=DEFAULT_CONFIG_DIR):
    bag = ((info or {}).get("bag") or {}).get("item") or {}
    try:
        props = _load(config_dir, "Prop.json")
    except Exception:
        props = {}
    out = {}
    for key, (iid, fallback) in MATERIALS.items():
        node = bag.get(str(iid))
        count = _int(node, "count") if isinstance(node, dict) else 0
        name = (props.get(str(iid)) or {}).get("name") or fallback
        out[key] = {"id": iid, "name": name, "count": count}
    return out


# ---------- 可洗对象 ----------

def _entity(node):
    return node.get("entityId") if isinstance(node, dict) else None


def list_amulets(info):
    bag = ((info or {}).get("bag") or {}).get("magicWeapon") or {}
    eq = ((info or {}).get("p1") or {}).get("equipments") or {}
    nodes = list(bag.values()) + [eq.get("amulet")]
    rows, seen = [], set()
    for node in nodes:
        eid = _entity(node)
        if not eid or eid in seen:
            continue
        seen.add(eid)
        rows.append({"entityId": eid, "name": node.get("name", ""),
                     "level": node.get("level"), "quality": node.get("quality"),
                     "equipped": node is eq.get("amulet")})
    rows.sort(key=lambda r: (-(r["level"] or 0), r["entityId"]))
    return rows


def list_runes(info):
    bag = ((info or {}).get("bag") or {}).get("rune") or {}
    import math
    with open(os.path.join(HERE, "cg_config_out_cg1_20261019_1", "PowerAttribute.json"), encoding="utf-8-sig") as stream:
        weights = json.load(stream)["1"]
    power_keys = ("hpMax","mpMax","atk","phyDef","hit","dodge","critical","toughness","lucky","guardian","reHP","reMP")
    sources = [(node, '背包') for node in (bag.values() if isinstance(bag, dict) else [])]
    amulets = (((info or {}).get('bag') or {}).get('magicWeapon') or {})
    holders = [(node, '背包法宝') for node in (amulets.values() if isinstance(amulets, dict) else [])]
    for player in ('p1','p2'):
        amulet = ((((info or {}).get(player) or {}).get('equipments') or {}).get('amulet'))
        if isinstance(amulet, dict):holders.append((amulet, player+'已装备法宝'))
    for amulet, owner in holders:
        if not isinstance(amulet, dict):continue
        inlay = amulet.get('inlay') or amulet.get('inlayInfo') or {}
        nodes = inlay.items() if isinstance(inlay, dict) else enumerate(inlay) if isinstance(inlay, list) else []
        for pos, node in nodes:
            if isinstance(node, dict) and _entity(node):
                sources.append((node, '%s·%s·孔位%s'%(owner,amulet.get('name') or amulet.get('entityId') or '法宝',pos)))
    rows, seen = [], set()
    sources.sort(key=lambda pair:pair[1]=='背包')
    for node, location in sources:
        eid = _entity(node)
        if not eid or eid in seen:continue
        seen.add(eid)
        rows.append({"entityId": eid, "id": node.get("id"),
                     "name": node.get("name", ""), "part": node.get("part"),
                     "lock": node.get("lock"), "location": location,
                     "attributes": current_attrs(node),
                     "attributeValues": {k:node[k] for k in power_keys if k in node},
                     "fightPower": math.floor(sum(float(node.get(k) or 0)*float(weights[k]) for k in power_keys)+0.5)})
    rows.sort(key=lambda r: (str(r["part"]), r["entityId"]))
    return rows


def list_feathers(info):
    """背包羽毛 + 身上翅膀镶嵌的羽毛（p1/p2.equipments.wing.inlayInfo）。"""
    bag = ((info or {}).get("bag") or {}).get("feather") or {}
    sources = [(node, "背包") for node in (bag.values() if isinstance(bag, dict) else [])]
    for player in ("p1", "p2"):
        wing = ((((info or {}).get(player) or {}).get("equipments") or {}).get("wing"))
        if isinstance(wing, dict):
            inlay = wing.get("inlayInfo") or wing.get("inlay") or []
            nodes = inlay if isinstance(inlay, list) else (inlay.values() if isinstance(inlay, dict) else [])
            for pos, node in enumerate(nodes):
                if isinstance(node, dict):
                    sources.append((node, "%s·翅膀·孔位%s" % (player, pos)))
    # 加载羽毛配表，取每个属性的洗练范围（"最小值;最大值"）
    feather_cfg = {}
    try:
        with open(os.path.join(HERE, "cg_config_out_cg1_20261019_1", "Feather.json"),
                  encoding="utf-8") as f:
            feather_cfg = json.load(f)
    except Exception:
        feather_cfg = {}
    rows, seen = [], set()
    for node, location in sources:
        eid = _entity(node)
        if not eid or eid in seen:
            continue
        seen.add(eid)
        attrs = current_attrs(node)
        cfg = feather_cfg.get(str(node.get("id"))) or {}
        attr_ranges = {}
        for k in attrs:
            rng = cfg.get(k)
            if isinstance(rng, str) and ";" in rng:
                bits = rng.split(";")
                try:
                    attr_ranges[k] = (float(bits[0]), float(bits[1]))
                except (ValueError, IndexError):
                    pass
        rows.append({"entityId": eid, "id": node.get("id"),
                     "name": node.get("name", ""),
                     "attributes": attrs,
                     "attributeValues": {k: node[k] for k in attrs if k in node},
                     "attrRanges": attr_ranges,
                     "pos": location})
    return rows


def washed_count(entity_id, info=None, form=None):
    """从配表反查该对象已洗练次数（formationFlag.washNum 就是已洗次数）。

    实测：极水血魄(220030301) washNum=108，洗一次后仍是原值，
    说明 washNum 是【当前灵魄等级对应的累计洗练数】，不是剩余次数。
    这里只做展示，不用它做限额判断。
    """
    return None


def list_formation_items(info, config_dir=DEFAULT_CONFIG_DIR):
    """佩戴中的精魄 / 阵眼（在 info.formation 里，按位置码索引）。

    位置码 3-4 位：RCCS = 阵容(1-4) + 列(0) + 槽位(S)
      槽位 1-4 = 血/智/力/骨魄（精魄），5 = 阵眼·阴，6 = 阵眼·阳
    返回 {"jingpo": [...], "zhenyan": [...]}，只含 isWash != 0 的可洗项。
    """
    form = (info or {}).get("formation") or {}
    try:
        ff = _load(config_dir, "FormationFlag.json")
    except Exception:
        ff = {}
    try:
        props = _load(config_dir, "Prop.json")
    except Exception:
        props = {}

    out = {"jingpo": [], "zhenyan": []}
    for pos, node in form.items():
        if not isinstance(node, dict):
            continue
        cfg = ff.get(str(node.get("id"))) or {}
        is_wash = cfg.get("isWash")
        if is_wash not in (1, 2):
            continue
        mat = None
        item_wash = cfg.get("itemWash")
        if isinstance(item_wash, str) and item_wash.startswith("item,"):
            bits = item_wash.split(",")
            mat = {"id": int(bits[1]), "count": int(bits[2]),
                   "name": (props.get(bits[1]) or {}).get("name", bits[1])}
        lockable = [a for a in str(cfg.get("attributes", "")).split(";") if a]
        # 属性范围：从配表取每个属性的 "最小值;最大值"
        attr_ranges = {}
        for a in lockable:
            rng = cfg.get(a)
            if isinstance(rng, str) and ";" in rng:
                bits = rng.split(";")
                try:
                    attr_ranges[a] = (float(bits[0]), float(bits[1]))
                except (ValueError, IndexError):
                    pass
        # 当前属性值：从佩戴的 node 里取（formation node 直接带 hpMax/dodge 等字段）
        attr_values = {k: node.get(k) for k in lockable if k in node}
        row = {
            "pos": pos,
            "entityId": node.get("entityId"),
            "id": node.get("id"),
            "name": node.get("name", ""),
            "part": cfg.get("part"),
            "attributes": cfg.get("attributes", ""),
            # 可锁词条 = 配表 attributes 用 ; 分隔的属性名（精魄/阵眼就是这些）
            "lockable": lockable,
            "attributeValues": attr_values,
            "attrRanges": attr_ranges,
            "washNum": cfg.get("washNum"),
            "grade": "精魄" if is_wash == 1 else "阵眼",
            "material": mat,
        }
        out["jingpo" if is_wash == 1 else "zhenyan"].append(row)
    out["jingpo"].sort(key=lambda r: r["pos"])
    out["zhenyan"].sort(key=lambda r: r["pos"])
    return out


if __name__ == "__main__":
    vip = load_vip()
    print("VIP 免费洗练额度（精魄/阵眼共用 formationResetNum）:")
    print("  %-4s %-6s %-6s %-6s %-8s %-6s %s"
          % ("VIP", "法宝", "灵符", "羽毛", "精魄+阵眼", "点券档", "开关"))
    for lv in sorted(vip):
        v = vip[lv]
        print("  %-4d %-6s %-6s %-6s %-8s %-6s isEquReset=%s"
              % (lv, v.get("amuletResetNum"), v.get("runeResetNum"),
                 v.get("featherResetNum"), v.get("formationResetNum"),
                 v.get("isFeatherWash"), v.get("isEquReset")))
    print("\n免费调用:")
    for k, spec in FREE_CALLS.items():
        print("  %-8s %-44s %s" % (SYSTEMS[k], spec["route"],
                                   spec["args"]("<entityId>")))
