# -*- coding: utf-8 -*-
"""实测：诸星封印 8 关能否进入 + 打死怪物 + 拾取掉落。

链路（复用 daily_auto.clear_dungeon 已验证的公式）：
  createSinglePlayerCopy{mid,rnd} -> r1(drops, rnd)
  syncDropInfo{index,key} per drop   index=(i+rand)^(serverRnd^myRnd), key=rand^myRnd
  finishSingleCopy{win:1, rnd:serverRnd^myRnd, star:3}

用法: python starseal_test.py [只跑某关的dungeonId] [--apply]
默认只预演（不实际进副本）；--apply 才真跑。
"""
import json
import os
import random
import sys
import time
from collections import defaultdict
from io import StringIO

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TOOLBOX = HERE
sys.path.insert(0, TOOLBOX)

import feature_account as ta  # noqa: E402

CFG = os.path.join(HERE, "feature_config")
OUT = os.path.join(HERE, "starseal_test_out.txt")
lines = []

# (activityId, 名称, dungeonId, 需要星数)
STAGES = [
    (101, "御马监", 10001, 18),
    (102, "御花园", 10002, 90),
    (103, "阆风幽境", 10003, 126),
    (104, "天马苑", 10011, 170),
    (105, "灵花圃", 10012, 187),
    (106, "清风廊", 10013, 216),
    (107, "翠竹径", 10004, 321),
    (108, "幽竹谷", 10014, 390),
]


def log(s=""):
    lines.append(str(s))
    print(s)


def run_one(flow, mid):
    """跑一次副本，返回结果字典。"""
    res = {"mid": mid, "entryOk": False, "dropCount": 0, "picked": 0,
           "got": {}, "finishOk": False, "error": None,
           "monsters": [], "dropsRaw": 0}
    my_rnd = random.randint(0, 9999)
    r1 = flow.request("scene.copyHandler.createSinglePlayerCopy",
                      {"mid": mid, "rnd": my_rnd})
    if not isinstance(r1, dict) or r1.get("error") or r1.get("code") != 200:
        res["error"] = str((r1 or {}).get("error") or r1)[:160]
        return res
    res["entryOk"] = True
    res["serverRnd"] = r1.get("rnd")

    # 本关怪物（服务器回包里的怪物列表 / 或从配表）
    for key in ("monsters", "monsterIds", "monster"):
        if isinstance(r1.get(key), list):
            res["monsters"] = [m.get("id") if isinstance(m, dict) else m
                               for m in r1[key]][:12]
            break
    if not res["monsters"]:
        sel = r1.get("selectMonster") or r1.get("monsterId")
        if sel:
            res["monsters"] = [sel]

    drops = r1.get("drops") or []
    res["dropsRaw"] = len(drops)
    server_rand = r1.get("rnd") or 0
    xor = server_rand ^ my_rnd
    bag = defaultdict(int)
    for i, d in enumerate(drops):
        rand = random.randint(1, 10000)
        idx = (i + rand) ^ xor
        key = rand ^ my_rnd
        try:
            sr = flow.request("scene.copyHandler.syncDropInfo",
                              {"index": idx, "key": key})
        except Exception as e:
            res["error"] = "syncDropInfo 异常: %s" % e
            continue
        if isinstance(sr, dict) and sr.get("code") == 200:
            res["picked"] += 1
            for g in (sr.get("give") or []):
                k = g.get("subType") or g.get("type")
                bag[k] += g.get("count", 0)
        # 失败不抛出，累积到 error 里
    res["got"] = dict(bag)
    time.sleep(1)
    r2 = flow.request("scene.copyHandler.finishSingleCopy",
                      {"win": 1, "rnd": xor, "star": 3})
    res["finishOk"] = (isinstance(r2, dict) and r2.get("code") == 200
                       and not r2.get("error"))
    if not res["finishOk"]:
        res["error"] = ("finish: %s"
                        % str((r2 or {}).get("error") or r2)[:160])
    return res


def main():
    apply_ = "--apply" in sys.argv
    only = None
    for a in sys.argv[1:]:
        if a.isdigit():
            only = int(a)

    dun = json.load(open(os.path.join(CFG, "Dungeon.json"), encoding="utf-8"))
    props = json.load(open(os.path.join(CFG, "Prop.json"), encoding="utf-8"))

    stages = [s for s in STAGES if only is None or s[2] == only]
    flow = ta.connect(ta.ACCT)
    try:
        info = ta.entry(flow, ta.ACCT)
        log("角色: %s  累计星数=%d" % (
            info.get("name"),
            sum(int(r.get("star") or 0) for r in (info.get("dungeon") or {}).values()
                if isinstance(r, dict))))
        bag_item = ((info.get("bag") or {}).get("item")) or {}
        ticket = bag_item.get("101041001") or {}
        log("诸星挑战券(101041001) = %s" % (ticket.get("count") if isinstance(ticket, dict) else 0))

        if not apply_:
            log("\n【预演】将逐关尝试，每关跑 1 次：")
            for aid, name, did, star in stages:
                node = dun.get(str(did)) or {}
                log("  %-6s dungeonId=%-6s 每日次数=%-4s 需道具=%s×%s 怪物=%s"
                    % (name, did, node.get("dailyCountMax"),
                       node.get("consume_subType"), node.get("consume_count"),
                       str(node.get("monsterID"))[:40]))
            log("\n加 --apply 实际执行。")
            return

        results = []
        for aid, name, did, star in stages:
            log("\n" + "=" * 60)
            log("【%s】dungeonId=%s" % (name, did))
            log("=" * 60)
            try:
                r = run_one(flow, did)
            except Exception as e:
                r = {"mid": did, "entryOk": False, "error": "异常: %s" % e,
                     "picked": 0, "got": {}}
            r["name"] = name
            results.append(r)
            if not r["entryOk"]:
                log("  进入失败: %s" % r["error"])
                continue
            log("  进入成功 ✅  (服务器下发掉落条目 %d)" % r["dropsRaw"])
            log("  怪物: %s" % (r.get("monsters") or "回包未带"))
            log("  拾取成功 %d/%d 条" % (r["picked"], r["dropsRaw"]))
            if r["got"]:
                log("  获得: %s" % "、".join(
                    "%s×%s" % ((props.get(str(k)) or {}).get("name", k), v)
                    for k, v in r["got"].items()))
            else:
                log("  获得: 无")
            log("  结算: %s%s" % ("成功 ✅" if r["finishOk"] else "失败 ❌ ",
                                 "" if r["finishOk"] else str(r.get("error"))[:120]))

        log("\n" + "=" * 60)
        log("汇总")
        log("=" * 60)
        log("%-6s %-7s %-8s %-8s %-10s %s"
            % ("关卡", "dungeon", "能进入", "拾取条数", "结算", "获得"))
        for r in results:
            log("%-6s %-7s %-8s %-8s %-10s %s"
                % (r["name"], r["mid"],
                   "是" if r["entryOk"] else "否",
                   "%d/%d" % (r.get("picked", 0), r.get("dropsRaw", 0)),
                   "成功" if r.get("finishOk") else "失败",
                   "、".join("%s×%s" % (k, v) for k, v in (r.get("got") or {}).items())
                   or "-"))
        log("\n失败原因:")
        for r in results:
            if not r["entryOk"] or not r.get("finishOk"):
                log("  %-6s %s" % (r["name"], r.get("error")))
    finally:
        flow.disconnect()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\ndone ->", OUT)


if __name__ == "__main__":
    main()
