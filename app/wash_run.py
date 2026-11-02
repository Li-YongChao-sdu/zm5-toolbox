# -*- coding: utf-8 -*-
"""洗练 编排层（五系统免费洗练，绝不消耗点券）。

用法（默认只读，真正洗练必须显式加 --apply）：
  （无参）                          只读：各系统今日免费额度 + 可洗对象 + 材料
  --list                            同上（显式）
  --system feather                  只看某系统
  --system feather --apply          对该系统第一个可洗对象执行一次免费洗练
  --system jingpo --target 312 --apply  指定对象（pos 或 entityId 前几位/名字）
  --all-free --apply                把所有系统的免费次数都用掉（各一次）
  --password 123456                 二级密码（洗练必需）

点券保护：只走免费档（灵符 type=2 / 阵眼精魄 index=2），材料不足直接拒绝，
          永不调用 fastBuy / 购买路由。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import wash_api as api    # noqa: E402
import wash_data as wd    # noqa: E402

TOOLBOX = HERE
sys.path.insert(0, TOOLBOX)
import daily_auto as da  # noqa: E402
from pypomelo.flow import GameLoginFlow  # noqa: E402
from pypomelo.login4399 import fetch_game_token  # noqa: E402

# 可选：用 --account <名> 指定本目录下的 account_<名>.local.json，
# 不改动工具箱的 account.local.json。
_ACCT = {
    "uid": da.UID,
    "username": da.USERNAME,
    "record_index": int(da._ACC.get("record_index", 0)),
    "cookies": da.COOKIES,
}


def use_account(name):
    """加载本目录下的 account_<name>.local.json 覆盖默认账号。"""
    path = os.path.join(HERE, "account_%s.local.json" % name)
    if not os.path.exists(path):
        raise RuntimeError("找不到账号文件 %s" % path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _ACCT.update({
        "uid": data["uid"],
        "username": data["username"],
        "record_index": int(data.get("record_index", 0)),
        "cookies": data["cookies"],
    })
    return _ACCT


def use_slot(slot):
    """覆盖存档槽位。"""
    if not 0 <= int(slot) <= 7:
        raise ValueError("存档槽位须为0～7")
    _ACCT["record_index"] = int(slot)
    return _ACCT


def connect():
    token = fetch_game_token(_ACCT["uid"], _ACCT["username"], _ACCT["cookies"])
    for ip in da.GATE_IPS:
        flow = GameLoginFlow(uid=_ACCT["uid"], token=token)
        try:
            host, port = flow.query_entry(ip, da.PORT)
            auth = flow.auth(host, port)
            if isinstance(auth, dict) and auth.get("code") == 200:
                return flow
            flow.disconnect()
        except Exception:
            flow.disconnect()
    raise RuntimeError("connect fail")


def entry(flow):
    r = flow.request("connector.entryHandler.entry",
                     {"index": _ACCT["record_index"],
                      "userAgent": flow.user_agent})
    return r.get("info", r)


def candidates(info, system, config_dir=wd.DEFAULT_CONFIG_DIR):
    """某系统的可洗对象列表。"""
    if system == "magic":
        return wd.list_amulets(info)
    if system == "rune":
        return wd.list_runes(info)
    if system == "feather":
        return wd.list_feathers(info)
    if system in ("jingpo", "zhenyan"):
        return wd.list_formation_items(info, config_dir)[system]
    return []


def get_status(info, config_dir=wd.DEFAULT_CONFIG_DIR):
    vip_table = wd.load_vip(config_dir)
    quota = wd.wash_quota(info, vip_table, config_dir)
    mats = wd.materials(info, config_dir)
    return {
        "name": info.get("name"),
        "vip": wd.vip_level(info),
        "quota": quota,
        "materials": mats,
        "candidates": {k: candidates(info, k, config_dir) for k in wd.SYSTEMS},
    }


def _print_status(st, only=None):
    print("存档: %s  VIP%s" % (st["name"], st["vip"]))
    print("\n=== 今日免费洗练额度 ===")
    print("  %-10s %-8s %-8s %-8s %s" % ("系统", "总额", "已用", "可用", "路由"))
    for key, label in wd.SYSTEMS.items():
        if only and key != only:
            continue
        q = st["quota"][key]
        print("  %-10s %-8s %-8s %-8s %s"
              % (label, q["freeTotal"], q["freeUsed"], q["freeLeft"], q["route"]))

    if not only:
        print("\n=== 洗练材料 ===")
        for key, m in sorted(st["materials"].items()):
            print("  %-12s %-16s = %s" % (key, m["name"], m["count"]))

    print("\n=== 可洗对象 ===")
    for key, label in wd.SYSTEMS.items():
        if only and key != only:
            continue
        rows = st["candidates"][key]
        print("  %s: %d 个" % (label, len(rows)))
        for r in rows[:10]:
            extra = ""
            if r.get("material"):
                extra = " 材料=%s×%s" % (r["material"]["name"], r["material"]["count"])
            print("     %-8s %-16s %s%s"
                  % (r.get("pos", ""), r.get("name", ""), r["entityId"], extra))
        if len(rows) > 10:
            print("     ... 还有 %d 个" % (len(rows) - 10))


def pick_target(info, system, target=None, config_dir=wd.DEFAULT_CONFIG_DIR):
    """挑一个目标对象。target 可以是位置码/entityId 片段/名字片段。"""
    rows = candidates(info, system, config_dir)
    if not rows:
        return None, "没有可洗对象"
    if not target:
        return rows[0], ""
    t = str(target)
    exact = next((r for r in rows if str(r.get("entityId")) == t), None)
    if exact is not None:return exact, ""
    for r in rows:
        if t == str(r.get("pos")) or t in str(r.get("entityId")) or t in str(r.get("name")):
            return r, ""
    return None, "找不到匹配 %r 的可洗对象（共 %d 个）" % (target, len(rows))


def do_free(flow, info, system, target=None, password=None, lock=None,
            replace=True, config_dir=wd.DEFAULT_CONFIG_DIR, review=False):
    """对一个系统执行一次免费洗练 + 保存/替换确认。

    lock:    要锁定的词条名列表（锁住的词条不重洗、保持原值）
    replace: True=保存新词条；False=保留旧词条（回退）
    返回 (ok, message, raw)
    """
    # 未设置二级密码的账号发送空字符串，由服务器判断是否需要密码。
    password = password or ""
    # 先校验"锁定"能力，再查额度，这样能给出更准确的报错
    if lock and not wd.can_lock(system):
        return False, ("%s 不能锁定词条：%s，请去掉 --lock"
                       % (wd.SYSTEMS.get(system, system),
                          wd.no_lock_reason(system))), None
    vip_table = wd.load_vip(config_dir)
    quota = wd.wash_quota(info, vip_table, config_dir)
    q = quota.get(system) or {}
    if q.get("freeTotal", 0) <= 0:
        return False, "%s 当前VIP%d未开放免费额度，跳过" % (wd.SYSTEMS[system], wd.vip_level(info)), None
    if q.get("freeLeft", 0) <= 0:
        return False, ("%s 今日免费次数已用完（%d/%d），不执行"
                       % (q.get("name", system), q.get("freeUsed", 0),
                          q.get("freeTotal", 0))), None
    row, err = pick_target(info, system, target, config_dir)
    if row is None:
        return False, err, None

    # 1) 洗练
    ok, msg, raw = api.free_wash(flow, system, row["entityId"], password,
                                 quota, lock=lock)
    if not ok:
        return False, msg, raw
    new_node = api.new_item(raw)
    display_node = ({key: new_node[key] for key in ("fiveElements", "growthRate") if key in new_node}
                    if system == "magic" and isinstance(new_node, dict) else new_node)
    detail = api.attr_text(display_node) if display_node else ""
    head = "%s：%s %s" % (q.get("name", system), row.get("name", ""),
                          row["entityId"])
    lines = [head]
    if lock:
        lines.append("  锁定词条: %s" % "/".join(lock))
    if detail:
        lines.append("  洗出: %s" % detail)

    if review:
        if system == 'rune':
            decision = review_rune_result(row, new_node, raw)
            if decision is None:
                return False, '\n'.join(lines + ['未确认洗练结果；未发送保存或保留请求，请回游戏检查待确认结果。']), raw
            replace = decision
        elif system == 'magic':
            review_magic_result(row, new_node, raw)
        elif system == 'feather':
            # VIP8 免费洗练可选择保留原属性（回退）；低 VIP 直接替换，只展示结果
            can_keep = wd.vip_level(info) >= 8
            if can_keep:
                decision = review_feather_result(row, new_node, raw, confirm=True)
                if decision is None:
                    return False, '\n'.join(lines + ['未确认洗练结果；未发送保存或保留请求，请回游戏检查待确认结果。']), raw
                replace = decision
            else:
                review_feather_result(row, new_node, raw, confirm=False)
        elif system in ('jingpo', 'zhenyan'):
            # 精魄/阵眼 ForSureWashMediator 无 VIP 判断，所有 VIP 都可选择保存/保留
            decision = review_formation_result(row, new_node, raw, system)
            if decision is None:
                return False, '\n'.join(lines + ['未确认洗练结果；未发送保存或保留请求，请回游戏检查待确认结果。']), raw
            replace = decision

    # 2) 保存 / 替换
    cok, cmsg, craw = api.confirm_wash(flow, system, row["entityId"],
                                       password, replace=replace)
    lines.append("  %s" % cmsg)
    if not cok:
        return False, "\n".join(lines), raw
    return True, "\n".join(lines), raw


def review_rune_result(old_row, new_node, raw=None):
    """等待界面明确选择；取消、断开或超时均不自动确认。"""
    import uuid, threading
    POWER_KEYS = ('hpMax','mpMax','atk','phyDef','hit','dodge','critical','toughness','lucky','guardian','reHP','reMP')
    if not isinstance(new_node, dict) or not any(k in new_node for k in POWER_KEYS):
        # 新对象不在预期位置，把回包结构打出来便于排查字段名对不上的问题。
        try:
            if isinstance(raw, dict):
                keys = [k for k in raw if isinstance(raw[k], dict)]
                dump = "回包顶层 dict 字段: %s" % ", ".join(keys)
            else:
                dump = "回包: %r" % (raw,)
        except Exception:
            dump = "(回包解析失败)"
        raise RuntimeError('未读到灵符新属性，未自动确认，请回游戏检查。%s' % dump)
    candidate = dict(new_node)
    candidate['entityId'] = old_row['entityId']
    new_row = wd.list_runes({'bag':{'rune':{'result':candidate}}})[0]
    token = uuid.uuid4().hex
    payload = {'token':token,'slot':_ACCT['record_index'],'entityId':old_row['entityId'],'name':old_row.get('name',''),'old':old_row,'new':new_row}
    print('__WASH_REVIEW__'+json.dumps(payload,ensure_ascii=False),flush=True)
    answer = [];ready = threading.Event()
    def read():
        try:answer.append(sys.stdin.readline())
        finally:ready.set()
    threading.Thread(target=read,daemon=True).start()
    if not ready.wait(600):return None
    try:result=json.loads(answer[0])
    except (ValueError,IndexError,TypeError):return None
    if result.get('token')!=token or result.get('entityId')!=old_row['entityId'] or result.get('slot')!=_ACCT['record_index']:return None
    return {'replace':True,'keep':False}.get(result.get('action'))


def review_magic_result(row, new_node, raw=None):
    """法宝洗练结果展示（免费档直接替换，只展示不确认）。

    法宝免费档 tryResetAttrFreeVIP 洗练后服务端直接落袋，无保存/回退选项，
    所以这里只把洗出的新属性通过弹窗展示给用户，等用户点"我知道了"再继续。
    """
    import uuid, threading
    if not isinstance(new_node, dict):
        try:
            if isinstance(raw, dict):
                keys = [k for k in raw if isinstance(raw[k], dict)]
                dump = "回包顶层 dict 字段: %s" % ", ".join(keys)
            else:
                dump = "回包: %r" % (raw,)
        except Exception:
            dump = "(回包解析失败)"
        raise RuntimeError('未读到法宝新属性。%s' % dump)
    candidate = dict(new_node)
    candidate.setdefault('entityId', row['entityId'])
    token = uuid.uuid4().hex
    payload = {'token': token, 'slot': _ACCT['record_index'],
               'entityId': row['entityId'], 'name': row.get('name', ''),
               'mode': 'info', 'system': 'magic',
               'old': row, 'new': candidate}
    print('__WASH_REVIEW__' + json.dumps(payload, ensure_ascii=False), flush=True)
    answer = []
    ready = threading.Event()
    def read():
        try:
            answer.append(sys.stdin.readline())
        finally:
            ready.set()
    threading.Thread(target=read, daemon=True).start()
    if not ready.wait(600):
        return
    try:
        result = json.loads(answer[0])
    except (ValueError, IndexError, TypeError):
        return
    if result.get('token') != token or result.get('entityId') != row['entityId'] \
            or result.get('slot') != _ACCT['record_index']:
        return


def review_feather_result(row, new_node, raw=None, confirm=True):
    """羽毛洗练结果展示。

    confirm=True （VIP8）：弹确认框，用户选保存/保留/取消，返回 True/False/None。
    confirm=False（低 VIP）：只展示，"我知道了"关闭，服务端直接替换。
    """
    import uuid, threading
    if not isinstance(new_node, dict):
        try:
            if isinstance(raw, dict):
                keys = [k for k in raw if isinstance(raw[k], dict)]
                dump = "回包顶层 dict 字段: %s" % ", ".join(keys)
            else:
                dump = "回包: %r" % (raw,)
        except Exception:
            dump = "(回包解析失败)"
        raise RuntimeError('未读到羽毛新属性。%s' % dump)
    candidate = dict(new_node)
    candidate.setdefault('entityId', row['entityId'])
    # 洗练回包的 feather 不带属性范围配置，从 old row 继承（同一只羽毛范围不变）
    if row.get('attrRanges'):
        candidate['attrRanges'] = row['attrRanges']
    token = uuid.uuid4().hex
    payload = {'token': token, 'slot': _ACCT['record_index'],
               'entityId': row['entityId'], 'name': row.get('name', ''),
               'mode': 'confirm' if confirm else 'info', 'system': 'feather',
               'old': row, 'new': candidate}
    print('__WASH_REVIEW__' + json.dumps(payload, ensure_ascii=False), flush=True)
    answer = []
    ready = threading.Event()
    def read():
        try:
            answer.append(sys.stdin.readline())
        finally:
            ready.set()
    threading.Thread(target=read, daemon=True).start()
    if not ready.wait(600):
        return None if confirm else None
    try:
        result = json.loads(answer[0])
    except (ValueError, IndexError, TypeError):
        return None
    if result.get('token') != token or result.get('entityId') != row['entityId'] \
            or result.get('slot') != _ACCT['record_index']:
        return None
    if confirm:
        return {'replace': True, 'keep': False}.get(result.get('action'))
    return None


def review_formation_result(row, new_node, raw, system):
    """精魄/阵眼洗练结果确认。

    ForSureWashMediator 无 VIP 判断，所有 VIP 都可选择保存新属性或保留旧属性，
    所以这里始终走 confirm 模式（不像羽毛低 VIP 直接替换）。
    返回 True=保存新词条 / False=保留旧词条 / None=取消或超时。
    """
    import uuid, threading
    if not isinstance(new_node, dict):
        try:
            if isinstance(raw, dict):
                keys = [k for k in raw if isinstance(raw[k], dict)]
                dump = "回包顶层 dict 字段: %s" % ", ".join(keys)
            else:
                dump = "回包: %r" % (raw,)
        except Exception:
            dump = "(回包解析失败)"
        raise RuntimeError('未读到精魄/阵眼新属性。%s' % dump)
    candidate = dict(new_node)
    candidate.setdefault('entityId', row['entityId'])
    # 洗练回包的 newFlag 不带属性范围和属性名列表，从 old row 继承（同一对象范围不变）
    if row.get('attrRanges'):
        candidate['attrRanges'] = row['attrRanges']
    if row.get('lockable'):
        candidate['lockable'] = row['lockable']
    token = uuid.uuid4().hex
    payload = {'token': token, 'slot': _ACCT['record_index'],
               'entityId': row['entityId'], 'name': row.get('name', ''),
               'mode': 'confirm', 'system': system,
               'old': row, 'new': candidate}
    print('__WASH_REVIEW__' + json.dumps(payload, ensure_ascii=False), flush=True)
    answer = []
    ready = threading.Event()
    def read():
        try:
            answer.append(sys.stdin.readline())
        finally:
            ready.set()
    threading.Thread(target=read, daemon=True).start()
    if not ready.wait(600):
        return None
    try:
        result = json.loads(answer[0])
    except (ValueError, IndexError, TypeError):
        return None
    if result.get('token') != token or result.get('entityId') != row['entityId'] \
            or result.get('slot') != _ACCT['record_index']:
        return None
    return {'replace': True, 'keep': False}.get(result.get('action'))


def plan(flow, info, system, target=None, lock=None, replace=True,
         config_dir=wd.DEFAULT_CONFIG_DIR):
    """只读：打印该系统这次会发哪些请求（不发），便于核对锁定与保存逻辑。"""
    row, err = pick_target(info, system, target, config_dir)
    if row is None:
        return err
    route, args = wd.free_call(system, row["entityId"], lock=lock)
    c_route, c_args = wd.confirm_call(system, row["entityId"], replace)
    lines = ["%s 目标: %s %s" % (wd.SYSTEMS.get(system, system),
                                row.get("name", ""), row["entityId"])]
    lockable = row.get("lockable") or row.get("attributes")
    if lockable:
        lines.append("  可锁词条: %s" % "/".join(lockable))
    lines.append("  ① 洗练 %s" % route)
    lines.append("     参数 %s  (+password)" % json.dumps(args, ensure_ascii=False))
    if not wd.can_lock(system):
        lines.append("     注意：该系统不能锁定词条 —— %s" % wd.no_lock_reason(system))
    elif lock:
        lines.append("     锁定 %s（消耗按 %d 倍计）" % ("/".join(lock), 1 + len(lock)))
    if wd.auto_replace(system):
        lines.append("  ② 免费档直接替换，无保存/回退选项")
    elif c_route:
        lines.append("  ② %s %s" % ("保存新词条" if replace else "保留旧词条", c_route))
        lines.append("     参数 %s  (+password)" % json.dumps(c_args, ensure_ascii=False))
    else:
        lines.append("  ② 无需确认（服务端洗练时已直接落袋）")
    return "\n".join(lines)


def _get_arg(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


if __name__ == "__main__":
    argv = sys.argv[1:]
    apply_ = "--apply" in argv
    password = _get_arg(argv, "--password")
    only = _get_arg(argv, "--system")
    target = _get_arg(argv, "--target")
    account = _get_arg(argv, "--account")
    slot = _get_arg(argv, "--slot")
    lock_arg = _get_arg(argv, "--lock")
    keep = "--keep" in argv            # 保留旧词条（回退），默认保存新词条
    lock = [x.strip() for x in lock_arg.split(",")] if lock_arg else None
    if account:
        use_account(account)
    if slot is not None:
        use_slot(slot)

    print("[免费洗练] 使用存档槽 %d" % _ACCT["record_index"], flush=True)
    flow = connect()
    try:
        info = entry(flow)
        if not apply_:
            st = get_status(info)
            print("__WASH_FREE_STATE__"+json.dumps({"slot":_ACCT["record_index"],"status":st},ensure_ascii=False),flush=True)
            _print_status(st, only)
            if only and "--list" not in argv:
                print("\n=== 这次会发的请求（只读预演，不会执行）===")
                print(plan(flow, info, only, target, lock=lock, replace=not keep))
            print("\n（只读模式；确认后加 --apply，并带 --password <二级密码>）")
            print("提示：绝不会消耗点券 —— 只走免费档，材料不足直接拒绝。")
            print("      锁定词条用 --lock 属性名1,属性名2（会按锁定条数倍增消耗）")
            print("      保存新词条=默认；保留旧词条加 --keep")
        else:
            systems = [only] if only else list(wd.SYSTEMS)
            if only and only not in wd.SYSTEMS:
                print("未知系统 %s，可选: %s" % (only, list(wd.SYSTEMS)))
            else:
                for sys_key in systems:
                    if only is None and "--all-free" not in argv:
                        break
                    if "--exact-target" in argv and not any(str(row["entityId"]) == str(target) for row in candidates(info, sys_key)):
                        raise ValueError("目标不属于当前存档，请重新刷新并选择")
                    ok, msg, raw = do_free(flow, info, sys_key, target,
                                           password, lock=lock,
                                           replace=not keep, review="--review-result" in argv)
                    print(("[OK] " if ok else "[--] ") + msg)
                    info = entry(flow)
                    print("__WASH_FREE_STATE__"+json.dumps({"slot":_ACCT["record_index"],"status":get_status(info)},ensure_ascii=False),flush=True)
    finally:
        flow.disconnect()
