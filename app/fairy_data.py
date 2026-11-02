# -*- coding: utf-8 -*-
"""幻兽试炼（= 幻兽派遣模块 fairySend）数据整理模块（独立，不改动工具箱已有文件）。

玩法（客户端 modules/fairySend + CreateGmCmd 映射确认："幻兽试炼" 即 fairySend 模块）：
  面板有 3 个档位（stallNum=3），每个档位是一条派遣任务。
  任务分 4 个等级：
    level 4 (S) 240分钟 -> rewardId 8001
    level 3 (A) 120分钟 -> 8002/8003
    level 2 (B)  60分钟 -> 8004/8005
    level 1 (C)  30分钟 -> 8006~8009
  每档位可"刷新"成别的任务：每日免费 2 次，之后用点券(refreshTicket=15)。
  派遣需要 2 只幻兽：1 只满足 condition_1（指定种类+品阶），另 1 只满足 condition_2（任意家品阶）。
  任务到期后可"领取"奖励；未到期可用点券(sendTicket=100)提前召回。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_CONFIG_DIR = os.path.join(HERE, "feature_config")

# 兜底值（配置缺失时用）
FALLBACK_STALL_NUM = 3
FALLBACK_REFRESH_FREE = 2
FALLBACK_REFRESH_TICKET = 15
FALLBACK_SEND_TICKET = 100
FALLBACK_COMPLETE_TICKET = 10
FALLBACK_SEND_DAY = 2

# 档位等级 -> 评级（用于显示）
LEVEL_GRADE = {4: "S", 3: "A", 2: "B", 1: "C"}


def _load(config_dir, name):
    with open(os.path.join(config_dir, name), encoding="utf-8") as f:
        return json.load(f)


def load_help(config_dir=DEFAULT_CONFIG_DIR):
    """读 FairySendHelp.json：槽位数、免费刷新次数、各种点券消耗。"""
    out = {
        "stallNum": FALLBACK_STALL_NUM,
        "refreshDayNum": FALLBACK_REFRESH_FREE,
        "refreshTicket": FALLBACK_REFRESH_TICKET,
        "refreshTicketMaxNum": 50,
        "sendTicket": FALLBACK_SEND_TICKET,
        "completeTicket": FALLBACK_COMPLETE_TICKET,
        "sendDayNum": FALLBACK_SEND_DAY,
    }
    try:
        table = _load(config_dir, "FairySendHelp.json")
        node = None
        for _, v in (table or {}).items():
            if isinstance(v, dict):
                node = v
                break
        if node:
            for k in list(out.keys()):
                if node.get(k) is not None:
                    try:
                        out[k] = int(node[k])
                    except (TypeError, ValueError):
                        pass
            # 档位等级概率
            levels = str(node.get("level", "") or "").split(";")
            probs = str(node.get("probability", "") or "").split(";")
            out["levelProbability"] = []
            for i, lv in enumerate(levels):
                lv = lv.strip()
                if not lv:
                    continue
                try:
                    lv_i = int(lv)
                except ValueError:
                    continue
                pr = 0.0
                if i < len(probs):
                    try:
                        pr = float(probs[i])
                    except ValueError:
                        pr = 0.0
                out["levelProbability"].append((lv_i, pr))
    except Exception:
        pass
    return out


def load_tasks(config_dir=DEFAULT_CONFIG_DIR):
    """读 FairySend.json：id -> 任务定义（含等级、耗时、奖励、幻兽要求）。"""
    try:
        table = _load(config_dir, "FairySend.json")
    except Exception:
        return {}
    out = {}
    for key, v in (table or {}).items():
        if not isinstance(v, dict):
            continue
        try:
            task_id = int(v.get("id", key))
        except (TypeError, ValueError):
            continue
        try:
            level = int(v.get("level", 0))
        except (TypeError, ValueError):
            level = 0
        try:
            cd = int(v.get("cd", 0))
        except (TypeError, ValueError):
            cd = 0
        try:
            cond2 = int(v.get("condition_2", 0))
        except (TypeError, ValueError):
            cond2 = 0
        cond1 = []
        for part in str(v.get("condition_1", "") or "").split(";"):
            part = part.strip()
            if not part:
                continue
            bits = part.split("_")
            if len(bits) < 2:
                continue
            try:
                cond1.append((int(bits[0]), int(bits[1])))
            except ValueError:
                continue
        reward_ids = []
        for part in str(v.get("rewardId", "") or "").split(";"):
            part = part.strip()
            if part:
                reward_ids.append(int(part))
        out[task_id] = {
            "id": task_id,
            "name": v.get("name", ""),
            "boss": v.get("miaoshu", ""),
            "level": level,
            "grade": LEVEL_GRADE.get(level, "?"),
            "cd": cd,
            "cdText": _cd_text(cd),
            "describe": v.get("describe", ""),
            "condition1": cond1,
            "condition2": cond2,
            "rewardIds": reward_ids,
            "numScale": v.get("numScale"),
            "activityId": v.get("activityId"),
        }
    return out


def _cd_text(cd_minutes):
    try:
        cd_minutes = int(cd_minutes)
    except (TypeError, ValueError):
        return "?"
    if cd_minutes >= 60:
        h = cd_minutes // 60
        m = cd_minutes % 60
        return ("%d小时" % h) if not m else ("%d小时%d分" % (h, m))
    return "%d分钟" % cd_minutes


def fairy_class_name(class_id, config_dir=DEFAULT_CONFIG_DIR):
    """幻兽种类 id -> 名字（FairyId.json）。"""
    try:
        table = _load(config_dir, "FairyId.json")
    except Exception:
        return "?"
    node = (table or {}).get(str(class_id))
    if isinstance(node, dict):
        return node.get("name", "?")
    return "?"


def item_names(item_ids, config_dir=DEFAULT_CONFIG_DIR):
    """道具 id -> 名字（Prop.json）。"""
    try:
        props = _load(config_dir, "Prop.json")
    except Exception:
        return {}
    out = {}
    for item_id in item_ids:
        node = (props or {}).get(str(item_id))
        if isinstance(node, dict):
            out[int(item_id)] = node.get("name", "")
    return out


def load_rewards(reward_ids, config_dir=DEFAULT_CONFIG_DIR):
    """Reward.json -> {rewardId: [{subType,count,name}]}。"""
    try:
        table = _load(config_dir, "Reward.json")
    except Exception:
        return {}
    all_item_ids = set()
    parsed = {}
    for rid in reward_ids:
        node = (table or {}).get(str(rid))
        if not isinstance(node, dict):
            continue
        subs = str(node.get("subType", "") or "").split(",")
        counts = str(node.get("count", "") or "").split(",")
        rows = []
        for i, sub in enumerate(subs):
            sub = sub.strip()
            if not sub:
                continue
            try:
                sub_id = int(sub)
            except ValueError:
                continue
            cnt = 1
            if i < len(counts):
                try:
                    cnt = int(counts[i])
                except ValueError:
                    cnt = 1
            rows.append({"subType": sub_id, "count": cnt})
            all_item_ids.add(sub_id)
        parsed[int(rid)] = {
            "id": int(rid),
            "describe": node.get("describe", ""),
            "describe1": node.get("describe1", ""),
            "items": rows,
        }
    names = item_names(all_item_ids, config_dir)
    for node in parsed.values():
        for row in node["items"]:
            row["name"] = names.get(row["subType"], "item%s" % row["subType"])
    return parsed


# ---------- 幻兽背包 ----------

def parse_entity_id(entity_id):
    """幻兽 entityId -> (classId, 尾巴上的数字)。

    形如 "570714954_r0_190090001_0f"：uid_r{存档}_{种类id}_{数字}f
    ⚠ 尾巴那个数字【不是】品阶（实测 _0f 的道具 step=1、另一个 _0f 是 step=2）。
    真正的品阶在服务器下发的 step 字段里，见 list_fairies()。
    """
    try:
        parts = str(entity_id).split("_")
        if len(parts) < 4:
            return None, None
        class_id = int(parts[-2])
        tail = int(str(parts[-1]).rstrip("fF"))
        return class_id, tail
    except (TypeError, ValueError):
        return None, None


def list_fairies(info, config_dir=DEFAULT_CONFIG_DIR):
    """背包幻兽 + 身上出战幻兽(p1/p2.equipments.fairy)。

    品阶以服务器的 step 字段为准（客户端 FairyManager 也是这么建的）。
    返回 [{"entityId","classId","step","name","source","role"}]，按品阶降序。
    role: None=背包, 0=主角色身上, 1=副角色身上。
    """
    bag = ((info or {}).get("bag") or {}).get("fairy")
    candidates = []
    if isinstance(bag, dict):
        candidates = [(node, "背包", None) for node in bag.values()]
    elif isinstance(bag, list):
        candidates = [(node, "背包", None) for node in bag]
    for role, key in enumerate(("p1", "p2")):
        body = (((info or {}).get(key) or {}).get("equipments") or {}).get("fairy")
        if isinstance(body, dict):
            candidates.append((body, "主角色身上" if role == 0 else "副角色身上", role))
    rows, seen = [], set()
    for node, source, role in candidates:
        if not isinstance(node, dict):
            continue
        entity_id = node.get("entityId")
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        class_id, _tail = parse_entity_id(entity_id)
        if class_id is None:
            try:
                class_id = int(node.get("id"))
            except (TypeError, ValueError):
                continue
        step = node.get("step")
        if step is None:
            # 兜底：没有 step 字段时才退回到 entityId 尾巴
            _cls, step = parse_entity_id(entity_id)
        try:
            step = int(step)
        except (TypeError, ValueError):
            continue
        rows.append({
            "entityId": entity_id,
            "classId": class_id,
            "step": step,
            "name": node.get("name") or node.get("nickName") or
                    fairy_class_name(class_id, config_dir),
            "source": source,
            "role": role,
        })
    rows.sort(key=lambda r: (-r["step"], r["classId"]))
    return rows


def fairy_by_entity(entity_id, fairies):
    """按 entityId 在幻兽列表里找那条记录（拿准确的品阶/名字）。"""
    for f in fairies or []:
        if f["entityId"] == entity_id:
            return f
    return None


def primary_fairy_classes(config_dir=DEFAULT_CONFIG_DIR):
    """从全部派遣任务的主位条件推导需保留的幻兽种类，不硬编码进阶名称。"""
    tasks = load_tasks(config_dir)
    classes = frozenset(class_id for task in tasks.values()
                        for class_id, _ in task['condition1'])
    if not classes:
        raise ValueError('派遣主幻兽配置缺失，无法安全自动配对')
    return classes


def pick_fairies(task, fairies, config_dir=DEFAULT_CONFIG_DIR):
    """副位优先非主位种类，再选满足条件的低阶组合；不改变任务条件。"""
    if not task:
        return {'ok': False, 'reason': '无任务', 'first': None, 'second': None}
    main_classes = primary_fairy_classes(config_dir) | {c for c, _ in task['condition1']}
    candidates = []
    for first in fairies:
        conditions = [(c, step) for c, step in task['condition1']
                      if first['classId'] == c and first['step'] >= step]
        if conditions:
            candidates.append((first, min(conditions, key=lambda x: x[1])))
    if not candidates:
        want = '、'.join('%s(>=%d阶)' % (fairy_class_name(c, config_dir), s)
                        for c, s in task['condition1'])
        return {'ok': False, 'reason': '没有满足条件的幻兽：需要 ' + (want or '?'),
                'first': None, 'second': None, 'condition1': None}
    pairs = []
    for first, condition in candidates:
        for second in fairies:
            if second['entityId'] == first['entityId'] or second['step'] < task['condition2']:
                continue
            score = (second['classId'] in main_classes, second['step'], first['step'],
                     str(first['entityId']), str(second['entityId']))
            pairs.append((score, first, second, condition))
    if not pairs:
        first, condition = min(candidates, key=lambda x: (x[0]['step'], str(x[0]['entityId'])))
        return {'ok': False,
                'reason': '没有满足条件的第二只幻兽：需要 %d 阶及以上（且不能与第一只重复）' % task['condition2'],
                'first': first, 'second': None, 'condition1': condition}
    _, first, second, condition = min(pairs, key=lambda x: x[0])
    return {'ok': True, 'reason': '', 'first': first, 'second': second,
            'condition1': condition, 'secondary_is_primary': second['classId'] in main_classes}


def describe_task(task, rewards, config_dir=DEFAULT_CONFIG_DIR):
    """把任务整理成可读一行（含奖励内容）。"""
    if not task:
        return "（空）"
    names = {c: fairy_class_name(c, config_dir) for c, _ in task["condition1"]}
    cond = task["condition1"][0] if task["condition1"] else (0, 0)
    rewards = rewards or {}
    reward_texts = []
    for rid in task["rewardIds"]:
        node = rewards.get(rid)
        if not node:
            continue
        body = "、".join("%s×%s" % (r["name"], r["count"]) for r in node["items"])
        reward_texts.append(body)
    return "[%s] %s·%s %s 需要%s>=%d阶 + 任意%d阶" % (
        task["grade"], task["name"], task["boss"], task["cdText"],
        names.get(cond[0], cond[0]), cond[1], task["condition2"]), reward_texts


if __name__ == "__main__":
    help_ = load_help()
    print("槽位数 stallNum =", help_["stallNum"])
    print("免费刷新 refreshDayNum =", help_["refreshDayNum"],
          "| 点券刷新 refreshTicket =", help_["refreshTicket"],
          "| 点券刷新上限 =", help_["refreshTicketMaxNum"])
    print("派遣次数/天 sendDayNum =", help_["sendDayNum"],
          "| 提前召回 sendTicket =", help_["sendTicket"],
          "| 立即完成 completeTicket =", help_["completeTicket"])
    print("档位概率:", ", ".join("level%d=%.0f%%" % (l, p * 100)
                                 for l, p in help_.get("levelProbability", [])))
    tasks = load_tasks()
    rewards = load_rewards(sorted({r for t in tasks.values() for r in t["rewardIds"]}))
    print("\n任务等级分布:")
    for lv in (4, 3, 2, 1):
        ids = [t["id"] for t in tasks.values() if t["level"] == lv]
        print("  level %d (%s): %d 个 (id %s)"
              % (lv, LEVEL_GRADE[lv], len(ids), ids))
    print("\n各等级奖励内容:")
    for lv in (4, 3, 2, 1):
        rids = sorted({r for t in tasks.values() if t["level"] == lv
                       for r in t["rewardIds"]})
        for rid in rids:
            node = rewards.get(rid)
            if node:
                body = "、".join("%s×%s" % (r["name"], r["count"]) for r in node["items"])
                print("  level %d reward %s: %s  (%s)"
                      % (lv, rid, body, node["describe"]))
