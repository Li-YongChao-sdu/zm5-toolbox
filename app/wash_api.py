# -*- coding: utf-8 -*-
"""洗练 协议层 API（独立，不改动工具箱已有文件）。

【点券硬保护】本模块的取值原则：
  1. 只调用 FREE_CALLS 里登记的免费路由 + 免费参数（index=2 / type=2）；
  2. index=0（阵眼/灵符面板的点券档）永不使用；
  3. 绝不调用任何 fastBuy / buy 路由，材料不足一律直接拒绝，不做任何购买；
  4. 每次动手前后都核对 everyDaySetting 计数器，确认走的是免费额度。

服务端要求请求体里带 password（二级密码），否则返回 code=502 二级密码错误。
该字段由 RequestProxy 对【每个请求】注入，所以这里对每次调用都带上。
"""
import wash_data as wd

ROUTE_MAGIC_FREE = "scene.magicWeaponHandler.tryResetAttrFree"
ROUTE_RUNE = "scene.magicWeaponHandler.tryResetRuneAttr"
ROUTE_FEATHER_VIP = "scene.wingHandler.featherVIPRest"
ROUTE_FORMATION = "scene.formationHandler.formationFlagRest"

# 明确列为"点券档"，本模块永不触碰
TICKET_ONLY = {
    ROUTE_MAGIC_FREE: (),            # 本身是免费档（但仍可能受材料限制）
    ROUTE_RUNE: (0, 1),              # 0=点券, 1=材料
    ROUTE_FEATHER_VIP: (),
    ROUTE_FORMATION: (0, 1),         # 0=点券, 1=魄心材料
}


def _ok(result):
    return isinstance(result, dict) and not result.get("error") \
        and result.get("code", 200) == 200


def _err(result):
    if isinstance(result, dict):
        return result.get("error") or result.get("msg") or result
    return result


def sent_args(route, args, password):
    """拼出最终请求参数，并断言没有踩到点券档 / 没有购买类字段。

    这是最后一道闸：即使上层传错，这里也会抛错而不是真花点券。
    """
    args = dict(args or {})
    if route in TICKET_ONLY:
        bad = TICKET_ONLY[route]
        if "index" in args and int(args["index"]) in bad:
            raise ValueError("拒绝：%s 的 index=%s 是点券档" % (route, args["index"]))
        if "type" in args and int(args["type"]) in bad:
            raise ValueError("拒绝：%s 的 type=%s 不是免费档" % (route, args["type"]))
    for forbidden in ("fastBuy", "buy", "costGem", "ticket"):
        if forbidden in args:
            raise ValueError("拒绝：参数里出现购买字段 %s" % forbidden)
    args["password"] = password
    return args


def free_wash(flow, key, entity_id, password, quota=None, lock=None):
    """执行一次免费洗练（点券保护开启）。返回 (ok, message, raw)。

    lock: 要锁定的词条名列表 —— 锁住的词条不参与重洗、保持原值；
          实测锁定会让消耗按 (1+锁的条数) 倍增加。
    注意：这里只发"洗练"请求；是否需要"保存/替换"确认见 confirm_wash()。
    """
    route, args = wd.free_call(key, entity_id, lock=lock)
    if route is None:
        return False, "未知系统 %s" % key, None
    if quota is not None:
        node = quota.get(key) or {}
        if node.get("freeLeft", 0) <= 0:
            return False, ("%s 今日免费次数已用完（%d/%d），不执行"
                           % (node.get("name", key), node.get("freeUsed", 0),
                              node.get("freeTotal", 0))), None
    try:
        payload = sent_args(route, args, password)
    except ValueError as e:
        return False, str(e), None
    try:
        raw = flow.request(route, payload)
    except Exception as e:
        return False, "请求异常: %s" % e, None
    if not _ok(raw):
        return False, "%s 失败：%s（未消耗点券）" % (wd.SYSTEMS.get(key, key),
                                                   _err(raw)), raw
    msg = "%s 洗练成功（免费档%s）" % (
        wd.SYSTEMS.get(key, key),
        "，锁定 %s" % "/".join(lock) if lock else "")
    return True, msg, raw


def confirm_wash(flow, key, entity_id, password, replace=True):
    """对洗练结果做"保存/替换"确认。

    replace=True  保存新词条（替换）
    replace=False 保留旧词条（回退）

    返回 (ok, message, raw)。若该系统不需要确认（服务端已落袋），返回 (True, 说明, None)。
    """
    route, args = wd.confirm_call(key, entity_id, replace)
    if route is None:
        return True, "%s：服务端已直接落袋，无需确认" % wd.SYSTEMS.get(key, key), None
    try:
        payload = sent_args(route, args, password)
    except ValueError as e:
        return False, str(e), None
    try:
        raw = flow.request(route, payload)
    except Exception as e:
        return False, "确认请求异常: %s" % e, None
    if not _ok(raw):
        return False, "%s 确认失败：%s（未消耗点券）" % (
            wd.SYSTEMS.get(key, key), _err(raw)), raw
    return True, "%s 已%s" % (wd.SYSTEMS.get(key, key),
                              "保存新词条" if replace else "保留旧词条"), raw


# ---------- 回包解析 ----------

def new_item(raw):
    """从回包里取洗出的新对象（各系统字段名不同）。

    实测各系统"洗练请求"回包的新对象字段：
      法宝   -> newMagicWeapon
      灵符   -> newAttr（RuneSureWashMediator 用 param1.newAttr 弹确认框）
      羽毛   -> feather
      精魄/阵眼 -> newFlag / formationFlag
    """
    for field in ("newAttr", "newMagicWeapon", "magicWeapon", "newRune", "rune",
                  "feather", "formationFlag", "newFlag"):
        node = (raw or {}).get(field)
        if isinstance(node, dict):
            return node
    return None


def consumes(raw):
    """回包里的消耗（免费档应为空）。"""
    rows = (raw or {}).get("consume")
    if isinstance(rows, list):
        return rows
    return []


def gave(raw):
    rows = (raw or {}).get("give")
    if isinstance(rows, list):
        return rows
    return []


def quota_from_reply(raw, info, vip_table=None):
    """用回包里的 everyDaySetting 刷新配额。"""
    eds = (raw or {}).get("everyDaySetting")
    if not isinstance(eds, dict):
        return None
    merged = dict(info or {})
    merged["everyDaySetting"] = eds
    return wd.wash_quota(merged, vip_table)


def attr_text(node):
    """把洗出的属性整理成可读文本。

    法宝洗练的核心结果（成长率 growthRate、五行 fiveElements、洗练值 srValue）
    必须包含 —— 之前误把它们排除了，属 bug。
    """
    if not isinstance(node, dict):
        return ""
    skip = {"entityId", "id", "index", "type", "name", "part", "lock",
            "createTime", "updateTime", "isConsume", "quality", "classType",
            "resourceId", "showFace", "wingFacade", "hole", "inlay",
            "power", "skills",
            "atkAdd", "hpMaxAdd", "mpMaxAdd", "phyDefAdd", "hitAdd",
            "dodgeAdd", "criticalAdd", "luckyAdd", "guardianAdd", "toughnessAdd"}
    parts = []
    for k, v in node.items():
        if k in skip:
            continue
        if k == "fiveElements":
            txt = wd.five_elements_text(v)
            if txt:
                parts.append("五行=%s" % txt)
            continue
        if isinstance(v, (dict, list)):
            continue
        parts.append("%s=%s" % (k, v))
    return " ".join(sorted(parts))
