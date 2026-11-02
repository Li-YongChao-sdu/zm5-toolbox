# -*- coding: utf-8 -*-
"""许愿池 编排层：状态查询 / 许愿 / 领取上期奖励，全部带预检。
可被命令行直接运行（默认只读打印状态），也可被未来 GUI 复用。
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wish_pool_api as api
import wish_pool_data as wpd

TOOLBOX = HERE
sys.path.insert(0, TOOLBOX)
import daily_auto as da
from pypomelo.flow import GameLoginFlow
from pypomelo.login4399 import fetch_game_token


def connect():
    token = fetch_game_token(da.UID, da.USERNAME, da.COOKIES)
    for ip in da.GATE_IPS:
        flow = GameLoginFlow(uid=da.UID, token=token)
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
                     {"index": da.RECORD_INDEX, "userAgent": flow.user_agent})
    return r.get("info", r)


def _slim_cell(d):
    it = d["item"]
    return {
        "pos": d["pos"], "pool": d["pool"], "wishId": d["wishId"],
        "poscnt": d["poscnt"],
        "consumeCosts": it.get("consumeCosts", []),
        "reward": it.get("reward", {}),
        "base": it.get("base", {}),
    }


def get_status(flow, info):
    """只读状态：可见格子 + 本期已许愿次数/上限 + 上期可领判断与结果。"""
    camp, has_union, league = api.get_my_camp(info)
    stages = wpd.load_stages()
    idx = api.build_item_index(stages)
    w = api.get_pool_info(flow)
    my_record_id = info.get("_id")
    ews_wish = (info.get("everyWeekSetting") or {}).get("wish") or {}

    visible = [_slim_cell(d) for d in
               api.select_visible_cells(w["cur"], camp, idx)]
    cur_state = api.my_wish_state(ews_wish, w["curKey"])
    used = cur_state["slots"]          # 占用不同格子数（官方 wishCount）
    total_wishes = cur_state["total"]  # 实际许愿总次数
    wish_max = stages["wishMax"]
    # 每个池子各自的许愿次数（0-10 上限）
    pool_states = api.my_wish_state_by_pool(
        ews_wish, w["curKey"], stages,
        visible_pools=[c["pool"] for c in visible])
    can_claim = api.can_claim_prev(ews_wish, w["lastKey"])
    prev_result = api.my_prev_result(w["last"], ews_wish, w["lastKey"], my_record_id)

    return {
        "recordName": info.get("name"),
        "hasUnion": has_union, "camp": camp,
        "leagueName": league.get("leagueName", ""),
        "curKey": w["curKey"], "lastKey": w["lastKey"],
        "wishMax": wish_max, "usedThisPeriod": used,
        "totalWishes": total_wishes,
        "remainingThisPeriod": max(0, wish_max - used),
        "poolMax": pool_states["maxPerPool"],
        "poolStates": pool_states["byPool"],
        "visibleCells": visible,
        "canClaimPrev": can_claim,
        "prevResult": prev_result,
    }


def wish_one(flow, info, wish_id):
    """预检后在指定格子许愿一次。返回 (ok, message, raw)。

    两道闸：① 单个池子许愿次数不得超过 poolMax（0-10，本次需求）；
             ② 本期占用格子总数不得超过 wishMax（配置项）。
    """
    st = get_status(flow, info)
    cell = next((c for c in st["visibleCells"] if c["wishId"] == int(wish_id)), None)
    if cell is None:
        return False, "wishId=%s 不在当前可见/可许的格子中" % wish_id, None
    # ① 单池次数上限
    node = st["poolStates"].get(cell["pool"])
    if node is not None and node["remaining"] <= 0:
        return False, ("%s 许愿已达单池上限 %d 次（已许 %d 次），停止（不会消耗点券）"
                       % (cell["pool"], node["max"], node["used"])), None
    # ② 本期占用格子总数上限
    if st["remainingThisPeriod"] <= 0:
        return False, "本期许愿已达上限 %d，停止（不会消耗点券）" % st["wishMax"], None
    # 该格当前是第几次许愿 -> 对应消耗
    step = st["usedThisPeriod"]
    costs = cell["consumeCosts"]
    if step < len(costs):
        pass  # 消耗由服务器校验；此处仅展示
    try:
        raw = api.do_wish(flow, wish_id)
    except Exception as e:
        return False, str(e), None
    pool_used = st["poolStates"].get(cell["pool"], {}).get("used", 0)
    return True, ("许愿成功 pos%d %s（本池第%d次，本期第%d次）"
                  % (cell["pos"], cell["pool"], pool_used + 1, step + 1)), raw


def claim_prev(flow, info):
    """预检后领取上一期奖励。返回 (ok, message, raw)。"""
    st = get_status(flow, info)
    if not st["canClaimPrev"]:
        return False, "上一期没有可领取的许愿奖励（未参与或已领取）", None
    try:
        raw = api.claim_prev_reward(flow)
    except Exception as e:
        return False, str(e), None
    return True, "已领取上期许愿奖励", raw


def _print_status(st):
    print("存档: %s | 联盟=%s camp=%d %s" %
          (st["recordName"], st["hasUnion"], st["camp"], st["leagueName"]))
    print("本期 %s / 上期 %s" % (st["curKey"], st["lastKey"]))
    print("许愿: 占用格子 %d / 上限 %d（剩 %d），实际许愿 %d 次" %
          (st["usedThisPeriod"], st["wishMax"], st["remainingThisPeriod"],
           st["totalWishes"]))
    if st.get("poolStates"):
        print("单池次数上限 %d:" % st["poolMax"])
        for pool, node in st["poolStates"].items():
            print("  %-4s 已许 %d / %d（剩 %d）" %
                  (pool, node["used"], node["max"], node["remaining"]))
    print("可见格子:")
    import json
    from pathlib import Path
    props=json.loads((Path(HERE)/'feature_config/Prop.json').read_text(encoding='utf-8-sig'))
    for c in st["visibleCells"]:
        reward=c["reward"];base=c["base"]
        def label(row):
            key=str(row.get('subType',''))
            name=(props.get(key) or {}).get('name','未知物品')
            return '%s×%s（ID：%s）'%(name,row.get('count',0),key)
        used=(st.get('poolStates',{}).get(c['pool']) or {}).get('used',0)
        print('  %s｜我已许愿%s次｜参与%s｜pos%s，wishId=%s'%(c['pool'],used,c['poscnt'],c['pos'],c['wishId']))
        print('    中奖奖励：%s；保底奖励：%s'%(label(reward),label(base)))
        print('    第1～%s次灵魂消耗：%s'%(len(c['consumeCosts']),'、'.join(str(x) for x in c['consumeCosts'])))
    print("上期可领奖: %s" % st["canClaimPrev"])
    if st["prevResult"]:
        for pos, (where, wish_id) in sorted(st["prevResult"].items()):
            print("  pos%d -> %s (wishId=%d)" %
                  (pos, "中奖" if where == "reward" else "保底", wish_id))


if __name__ == "__main__":
    flow = connect()
    try:
        info = entry(flow)
        st = get_status(flow, info)
        _print_status(st)
    finally:
        flow.disconnect()
