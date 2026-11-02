# -*- coding: utf-8 -*-
"""善法堂点赞 编排层：进善法堂 -> 查今日配额 -> 给榜首赠送爱心 -> 拿道具。

设计原则（与许愿池模块一致）：默认【只读预演】，确认无误后再 apply=True 真正点赞。
因为每天只能赠送一次爱心，误点无法撤回，所以默认不写。

用法：
  python shanfa_run.py            # 预演：只查状态和将要点的目标，不点赞
  python shanfa_run.py --apply    # 真正点赞（消耗当天唯一一次）
  python shanfa_run.py --apply --type 3
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import shanfa_api as api   # noqa: E402
import shanfa_data as sd   # noqa: E402

TOOLBOX = HERE
sys.path.insert(0, TOOLBOX)
import daily_auto as da  # noqa: E402
from pypomelo.flow import GameLoginFlow  # noqa: E402
from pypomelo.login4399 import fetch_game_token  # noqa: E402


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


def get_status(flow, info, type_no=None, config_dir=sd.DEFAULT_CONFIG_DIR):
    """只读状态：今日配额 + 榜首目标 + 可能的回礼。

    不调用点赞路由。但在场景外 getAllTop1 会报离线，所以需要时先进场景。
    """
    common = sd.load_common(config_dir)
    state = api.like_state(info, common["freeNum"])

    scene_before = api.current_scene(info)
    scene_ids = sd.shanfa_scene_ids(config_dir)
    entered = False
    if scene_before not in scene_ids:
        entered, scene_id, _ = api.enter_shanfa(flow, config_dir)
        if not entered:
            raise RuntimeError("进入善法堂失败")
        info = entry(flow)
    scene_now = api.current_scene(info)

    top1 = api.get_top1(flow)
    target = api.pick_target(top1, type_no)
    drop = sd.load_drop(common["dropId"], config_dir)
    names = sd.item_names([i for i, _ in drop["items"]], config_dir)

    return {
        "recordName": info.get("name"),
        "sceneBefore": scene_before, "sceneNow": scene_now,
        "movedToShanfa": entered,
        "likeState": state,
        "targets": api.parse_top1(top1),
        "target": target,
        "drop": drop, "itemNames": names,
    }


def _print_status(st):
    s = st["likeState"]
    print("存档: %s" % st["recordName"])
    if st["movedToShanfa"]:
        print("场景: %s -> %s（已进善法堂）" % (st["sceneBefore"], st["sceneNow"]))
    else:
        print("场景: %s（本就在善法堂）" % st["sceneNow"])
    print("今日赠送爱心: 已用 %d / %d（剩 %d）%s"
          % (s["used"], s["free"], s["remaining"],
             "" if s["canLike"] else "  <- 今天已点过，无法再点"))
    print("\n各职业战力第一（可点赞目标）:")
    for t in st["targets"]:
        print("  type_%-2d uid=%-12s %-14s 战力%-9s 联盟%s"
              % (t["type"], t["uid"], t["name"], t["score"], t["leagueName"]))
    tgt = st["target"]
    if tgt:
        print("\n本次目标: type_%d uid=%s %s（战力 %s）"
              % (tgt["type"], tgt["uid"], tgt["name"], tgt["score"]))
    drop = st["drop"]
    print("回礼来源: 掉落表 %s（%s），单次最多 %d 件，共 %d 种可能"
          % (drop["dropId"], drop["describe"], drop["itemMaxNum"], len(drop["items"])))


def like_in_shanfa(flow, info, type_no=None, apply=False,
                   config_dir=sd.DEFAULT_CONFIG_DIR):
    """进善法堂并赠送爱心。返回 (ok, message, detail)。

    apply=False 时只预演（会进场景并查数据，但不点赞）。
    """
    st = get_status(flow, info, type_no, config_dir)
    tgt = st["target"]
    if tgt is None:
        return False, "没有拿到可点赞的榜首目标（getAllTop1 为空）", st
    if not st["likeState"]["canLike"]:
        return False, ("今日赠送爱心次数已用完（%d/%d），不点赞"
                       % (st["likeState"]["used"], st["likeState"]["free"])), st
    if not apply:
        return False, ("预演：将给 type_%d uid=%s %s 赠送爱心（未实际点赞，"
                       "加 --apply 执行）"
                       % (tgt["type"], tgt["uid"], tgt["name"])), st

    raw = api.like_top1(flow, tgt["uid"], tgt["type"])
    names = st["itemNames"]
    got = api.format_give(raw, names)
    return True, ("已给 type_%d %s 赠送爱心，获得：%s"
                  % (tgt["type"], tgt["name"], got)), {"status": st, "raw": raw}


if __name__ == "__main__":
    argv = sys.argv[1:]
    do_apply = "--apply" in argv
    type_no = None
    if "--type" in argv:
        type_no = int(argv[argv.index("--type") + 1])

    flow = connect()
    try:
        info = entry(flow)
        if do_apply:
            ok, msg, detail = like_in_shanfa(flow, info, type_no, apply=True)
            print(msg)
            if ok and isinstance(detail, dict):
                raw = detail.get("raw") or {}
                eds = api.state_after(raw)
                if eds:
                    print("今日已赠送: %s / %s"
                          % (eds.get("criticiseTop1"),
                             sd.load_common()["freeNum"]))
        else:
            st = get_status(flow, info, type_no)
            _print_status(st)
            print("\n（预演模式，未点赞；确认后加 --apply）")
    finally:
        flow.disconnect()
