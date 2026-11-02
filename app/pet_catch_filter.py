# -*- coding: utf-8 -*-
"""诸星封印抓宠 + 【资质/天赋/星级/性别 区间】筛选 + 自动放生。

== 已实测确认 ==
抓宠: scene.petHandler.capture {"itemId": <葫芦道具id>, "petId": <宠物id>}
      * itemId 是葫芦【道具id】(101017001 木灵) 不是技能id(9003)；填技能id 报"道具和宠物不匹配"
      * 回包 {code:200, success:0/1, consume, give:[{type:"pet",subType,data:{...}}]}
放生: scene.petHandler.free {"entityId": <宠物entityId>}

== 筛选字段（每项【上下限】均可设）==
资质:
  hp    hpQualification    生命资质
  atk   atkQualification   攻击资质
  def   defQualification   防御资质
  rehp  reHpQualification  回血资质
天赋（你说的"天赋词条"）:
  phy   physical           体质   } 配表天马/灵花均为 1;4
  bone  bone               根骨   }
  cap   capacity           潜力   }
其它:
  star  quality            星级   (1~6，Pet.quality；天马/灵花基础=1)
  sex   sex                性别   (1=公 2=母)

== 用法 ==
  python pet_catch_filter.py                       # 只读预演
  python pet_catch_filter.py --apply --total 20 --per-stage 10 \
      --hp 400 520 --atk 400 460 --def 400 480 --rehp 400 520 \
      --phy 2 4 --bone 2 4 --cap 2 4 --star 1 6 --sex 1 2
  # 只给下限（上限保持默认）： --star 2
  # 某性别只要一种：        --sex 2 2
"""
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TOOLBOX = HERE
sys.path.insert(0, TOOLBOX)

import feature_account as ta  # noqa: E402

OUT = os.path.join(HERE, "pet_catch_filter_out.txt")
lines = []

ROUTE_CAPTURE = "scene.petHandler.capture"
ROUTE_FREE = "scene.petHandler.free"

STAGES = [
    ("御马监", 10001, "天马", 170111101),
    ("御花园", 10002, "灵花", 170511101),
    ("阆风幽境", 10003, "白虎", 170611101),
    ("翠竹径", 10004, "熊猫", 171711101),
]
GOURD = 101017001
GOURD_NAME = "木灵葫芦"

SEX_NAME = {1: "公", 2: "母"}

# (键, 宠物字段, 中文名, 值格式化)
FIELDS = [
    ("hp", "hpQualification", "生命资质", None),
    ("atk", "atkQualification", "攻击资质", None),
    ("def", "defQualification", "防御资质", None),
    ("rehp", "reHpQualification", "回血资质", None),
    ("phy", "physical", "体质", None),
    ("bone", "bone", "根骨", None),
    ("cap", "capacity", "潜力", None),
    ("star", "quality", "星级", None),
    ("sex", "sex", "性别", lambda v: "%s(%s)" % (v, SEX_NAME.get(v, "?"))),
]

# 默认区间（都可在命令行覆盖）
RANGES = {
    "hp": (400, 560),
    "atk": (400, 470),
    "def": (400, 490),
    "rehp": (400, 540),
    "phy": (2, 4),
    "bone": (2, 4),
    "cap": (2, 4),
    "star": (1, 6),      # 全星级都收（含1星宝宝）
    "sex": (1, 2),       # 公母都要
}


def log(s=""):
    lines.append(str(s))
    print(s)


def icount(info, iid):
    items = ((info.get("bag") or {}).get("item")) or {}
    n = items.get(str(iid))
    return n.get("count", 0) if isinstance(n, dict) else 0


def pets(info):
    return ((info.get("bag") or {}).get("pet")) or {}


def pet_max(info):
    return ((info.get("bag") or {}).get("petMaxNum")) or 0


def pet_summary(p):
    s = {"entityId": p.get("entityId"), "name": p.get("name"),
         "fightPower": p.get("fightPower")}
    for key, field, _, _ in FIELDS:
        s[key] = p.get(field)
    s["passivity"] = list(((p.get("skill") or {}).get("passivity") or {}).keys())
    return s


def fv(key, v):
    for k, _, _, fmt in FIELDS:
        if k == key:
            return fmt(v) if fmt else v
    return v


def pass_filter(s, ranges):
    """逐项检查区间。返回 (ok, 越界原因列表)。"""
    fails = []
    for key, _, cname, fmt in FIELDS:
        lo, hi = ranges.get(key, (None, None))
        v = s.get(key)
        if v is None:
            fails.append("%s缺失" % cname)
            continue
        show = fmt(v) if fmt else v
        if lo is not None and v < lo:
            fails.append("%s%s<%s" % (cname, show, lo))
        if hi is not None and v > hi:
            fails.append("%s%s>%s" % (cname, show, hi))
    return (not fails), fails


def parse_range(argv, key):
    flag = "--" + key
    if flag not in argv:
        return RANGES[key]
    i = argv.index(flag)
    vals = []
    j = i + 1
    while j < len(argv) and not argv[j].startswith("--"):
        try:
            vals.append(float(argv[j]))
        except ValueError:
            break
        j += 1
    if not vals:
        return RANGES[key]
    lo = int(vals[0])
    if len(vals) >= 2:
        return (lo, int(vals[1]))
    return (lo, RANGES[key][1])


def release(flow, entity_id):
    r = flow.request(ROUTE_FREE, {"entityId": entity_id})
    ok = isinstance(r, dict) and r.get("code") == 200 and not r.get("error")
    return ok, r


def brief(s):
    return ("资%4s/%4s/%4s/%4s 天%s/%s/%s %s星%s 战力%s"
            % (s["hp"], s["atk"], s["def"], s["rehp"],
               s["phy"], s["bone"], s["cap"], s["star"],
               SEX_NAME.get(s["sex"], "?"), s["fightPower"]))


def main():
    global GOURD, GOURD_NAME
    argv = sys.argv[1:]
    stages = STAGES[:2]
    if '--stage' in argv:
        selected = int(argv[argv.index('--stage') + 1])
        stages = [s for s in STAGES if s[1] == selected]
        if not stages:
            raise ValueError('未知抓宠关卡')
    if '--gourd' in argv:
        gourds = {101017001:'木灵葫芦',101017002:'火灵葫芦',101017003:'紫金葫芦',101017004:'灵金葫芦',101017005:'青篁葫芦'}
        GOURD = int(argv[argv.index('--gourd') + 1])
        if GOURD not in gourds:
            raise ValueError('未知葫芦')
        GOURD_NAME = gourds[GOURD]
    apply_ = "--apply" in argv
    total = int(argv[argv.index("--total") + 1]) if "--total" in argv else 20
    max_attempts = int(argv[argv.index('--max-attempts')+1]) if '--max-attempts' in argv else None
    keep_total = int(argv[argv.index('--keep-total')+1]) if '--keep-total' in argv else None
    if total < 1 or (max_attempts is not None and max_attempts < 1) or (keep_total is not None and keep_total < 1):
        raise ValueError('抓宠数量和尝试上限必须为正整数')
    per_stage = (int(argv[argv.index("--per-stage") + 1])
                 if "--per-stage" in argv else max(1, total // len(stages)))
    include_existing = "--include-existing" in argv
    ranges = {k: parse_range(argv, k) for k, _, _, _ in FIELDS}

    flow = ta.connect(ta.ACCT)
    try:
        info = ta.entry(flow, ta.ACCT)
        cur = pets(info)
        existing_ids = set(cur)
        log("角色: %s" % info.get("name"))
        log("宠物背包: %d / %s       %s 库存 = %d"
            % (len(cur), pet_max(info), GOURD_NAME, icount(info, GOURD)))

        log("\n=== 筛选区间（区间内才保留）===")
        for key, _, cname, _ in FIELDS:
            lo, hi = ranges[key]
            log("  %-8s %-10s %s~%s" % (cname, "(%s)" % key,
                                        "-" if lo is None else lo,
                                        "-" if hi is None else hi))

        log("\n=== 现有宠物按此区间判定（仅展示）===")
        keep = drop = n = 0
        for eid, p in cur.items():
            if not isinstance(p, dict):
                continue
            n += 1
            s = pet_summary(p)
            ok, fails = pass_filter(s, ranges)
            keep, drop = (keep + 1, drop) if ok else (keep, drop + 1)
            if n <= 10:
                log("  %-20s %-5s %s -> %s %s"
                    % (eid, s["name"], brief(s), "保留" if ok else "放生",
                       "" if ok else "(" + "、".join(fails) + ")"))
        log("  ... 共 %d 只：区间内 %d，越界 %d" % (n, keep, drop))
        log("  %s" % ("已指定 --include-existing" if include_existing
                      else "未指定 --include-existing：现有宠物不会被放生"))

        if not apply_:
            log("\n【预演】加 --apply 会：逐关抓宠 -> 按区间判定 -> 越界立即放生")
            log("  目标共抓 %d 只（每关 %d 只），每抓 1 次扣 1 个 %s"
                % (total, per_stage, GOURD_NAME))
            if keep_total is not None:
                log('  保留目标 %d 只；最大尝试 %s 次' % (keep_total, max_attempts))
            return

        stats = {"caught": 0, "kept": 0, "released": 0, "attempts": 0,
                 "keptList": [], "releasedList": []}

        if include_existing:
            info = ta.entry(flow, ta.ACCT)
            for eid, p in list(pets(info).items()):
                if not isinstance(p, dict):
                    continue
                s = pet_summary(p)
                ok, fails = pass_filter(s, ranges)
                if not ok:
                    rok, _ = release(flow, eid)
                    if rok:
                        stats["released"] += 1
                        log("  放生现有 %s %s (%s)" % (eid, s["name"], "、".join(fails)))

        for sname, mid, pname, pid in stages:
            if stats["caught"] >= total:
                break
            need = min(per_stage, total - stats["caught"])
            log("\n" + "=" * 68)
            log("【%s】抓 %s，目标 %d 只" % (sname, pname, need))
            log("=" * 68)

            info = ta.entry(flow, ta.ACCT)
            mx = pet_max(info)
            if len(pets(info)) >= mx - 1:
                log("  背包将满(%d/%s)，仅检查允许清理的宠物..." % (len(pets(info)), mx))
                for eid, p in list(pets(info).items()):
                    if eid in existing_ids and not include_existing:
                        continue
                    if not isinstance(p, dict):
                        continue
                    s = pet_summary(p)
                    ok, fails = pass_filter(s, ranges)
                    if not ok:
                        rok, _ = release(flow, eid)
                        if rok:
                            stats["released"] += 1
                            log("    放生旧宠 %s %s (%s)"
                                % (eid, s["name"], "、".join(fails)))
                            info = ta.entry(flow, ta.ACCT)
                            if len(pets(info)) < mx - 3:
                                break
                log("  清理后 %d/%s"
                    % (len(pets(ta.entry(flow, ta.ACCT))), mx))

            info = ta.entry(flow, ta.ACCT)
            if len(pets(info)) >= pet_max(info) - 1:
                log('  背包空间不足，停止；不放生已有宠物。')
                break
            my_rnd = random.randint(0, 9999)
            r1 = flow.request("scene.copyHandler.createSinglePlayerCopy",
                              {"mid": mid, "rnd": my_rnd})
            if not isinstance(r1, dict) or r1.get("code") != 200 or r1.get("error"):
                log("  进入失败: %s" % str((r1 or {}).get("error"))[:120])
                continue
            log("  进入成功 ✅")

            here = 0
            guard = 0
            while here < need and guard < need * 8:
                if keep_total is not None and stats['kept'] >= keep_total:
                    log('  已达到目标保留数量，停止捕捉')
                    break
                if max_attempts is not None and stats['attempts'] >= max_attempts:
                    log('  已达到最大尝试次数，停止捕捉')
                    break
                guard += 1
                if icount(info, GOURD) <= 0:
                    log("  %s 用完，停止" % GOURD_NAME)
                    break
                c = flow.request(ROUTE_CAPTURE, {"itemId": GOURD, "petId": pid})
                stats["attempts"] += 1
                if (c or {}).get("code") != 200:
                    log("  抓宠失败: %s" % (c or {}).get("error"))
                    break
                if c.get("success") != 1:
                    time.sleep(0.35)
                    continue
                here += 1
                stats["caught"] += 1
                data = ((c.get("give") or [{}])[0]).get("data") or {}
                s = pet_summary(data)
                ok, fails = pass_filter(s, ranges)
                log("  抓到 #%d %s: %s -> %s%s"
                    % (stats["caught"], s["name"], brief(s),
                       "保留 ✅" if ok else "放生 ❌",
                       "" if ok else "  (" + "、".join(fails) + ")"))
                if ok:
                    stats["kept"] += 1
                    stats["keptList"].append(s)
                else:
                    eid = data.get("entityId")
                    rok, rr = release(flow, eid)
                    if rok:
                        stats["released"] += 1
                        stats["releasedList"].append((s, "、".join(fails)))
                        log("     已放生 %s" % eid)
                    else:
                        log("     ⚠️ 放生失败: %s" % str((rr or {}).get("error"))[:100])
                info = ta.entry(flow, ta.ACCT)
                time.sleep(0.45)

            fin = flow.request("scene.copyHandler.finishSingleCopy",
                               {"win": 1, "rnd": (r1.get("rnd") or 0) ^ my_rnd, "star": 3})
            log("  本关抓到 %d 只，结算 code=%s" % (here, (fin or {}).get("code")))
            time.sleep(1.2)

        log("\n" + "=" * 68)
        log("汇总")
        log("=" * 68)
        log("  尝试 %d 次，抓到 %d 只，保留 %d，放生 %d"
            % (stats["attempts"], stats["caught"], stats["kept"], stats["released"]))
        log("\n保留:")
        for s in stats["keptList"]:
            log("  %-20s %-5s %s" % (s["entityId"], s["name"], brief(s)))
        log("\n放生:")
        for s, why in stats["releasedList"]:
            log("  %-20s %-5s %s  (%s)" % (s["entityId"], s["name"], brief(s), why))
        info = ta.entry(flow, ta.ACCT)
        log("\n结束: 背包 %d/%s，%s %d"
            % (len(pets(info)), pet_max(info), GOURD_NAME, icount(info, GOURD)))
    finally:
        flow.disconnect()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\ndone ->", OUT)


if __name__ == "__main__":
    main()
