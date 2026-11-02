# -*- coding: utf-8 -*-
"""
星斗幻境(星斗/迷宫 mazeHandler) 纯协议自动通关 —— 一次打通三大层。

协议链(逆向自 AS: xingdou.MazeDungeonManager / MazeDungeonGoToNodeCmd):
  getMapData  -> 拉取本章有向地图(map[row][col]=下一行可达列, event[row][col]=[类型,参数])
  goto{x,y}   -> 走到相邻节点, 按返回 event 处理:
                   201/202/203 小怪/精英/妖王: enterDungeon{} -> finishDungeon{win:1,time}
                   101 不明事件: selectOption{index:1}
                   301 商店:     getShopData{} (只看不买, 不花点券)
                   401 温泉:     自动结算(无需额外请求)
                   500/501 宝箱: getRewardList{} -> chooseReward{index:0}
  妖王通关后 chapterPassed=true -> nextChapter{} 进入下一大层, 共 3 大层
  第3层通关后 getFinishRewardFree 免费领周奖励(只走免费接口, 绝不调 WithTicket/reset/buy/resurrect)

铁律: 本玩法走格/战斗不扣货币; 唯一付费点是【额外周奖励(rewardTicket=400)】、【复活】、【重置】、
【买体力】, 本文件一律不调用; 任何返回含 点券/ticket/票/不足/元宝 立即中止。
"""
import json
import time
from collections import defaultdict

SLEEP = 1.0
MAX_STEPS = 120
MAZE_CHAPTERS = 3
MAX_RESET_PER_CHAPTER = 2   # 被道具门/宝箱卡住时, 每层最多免费重置次数(服务器冷却兜底, 绝不付费)
RESET_CD = 180              # reset 冷却秒数(MazeDeploy.resetTime)
# 每大层周奖励箱 rewardId(MazeDeploy.mazeReward), 仅用 getFinishRewardFree 免费领
MAZE_REWARD_IDS = [5270]   # 周奖励三档: 白银5094/黄金5137/灵玉5270, 共享每周额度, 只领最高档灵玉
MAZE_REWARD_MAX = 3       # MazeDeploy.RewardMax；领奖前还要核对服务器周计数

BATTLE_EVENTS = {201, 202, 203}
BOX_EVENTS = {500, 501}
MONEY_HINTS = ("点券", "ticket", "票", "不足", "元宝", "支付", "扣费")


def _is_money_err(r):
    if not isinstance(r, dict):
        return False
    e = str(r.get("error") or "")
    return any(h in e for h in MONEY_HINTS)


def _ok(r):
    return isinstance(r, dict) and (r.get("code") == 200 or r.get("error") is None)


def _remaining_weekly_maze_rewards(info, reward_max=MAZE_REWARD_MAX):
    """按客户端公式计算剩余免费周宝箱次数；缺字段时返回 None 并停止领奖。"""
    weekly = (info or {}).get("everyWeekSetting")
    if not isinstance(weekly, dict):
        return None
    try:
        maze_count = int(weekly["mazeCnt"])
        # 客户端 EveryWeekSetting.rewardMazeCnt 默认0；服务器可能省略零值。
        # 仅在 mazeCnt 和奖励档库存均已返回时采用该默认值。
        if 'rewardMazeCnt' not in weekly and not isinstance(weekly.get('mazeReward'), dict):
            return None
        claimed_count = int(weekly.get("rewardMazeCnt", 0))
    except (KeyError, TypeError, ValueError):
        return None
    if maze_count < 0 or claimed_count < 0:
        return None
    return {
        "mazeCnt": maze_count,
        "rewardMazeCnt": claimed_count,
        "remaining": max(0, min(int(reward_max), maze_count) - claimed_count),
        "rewardStock": weekly.get("mazeReward") or {},
    }


def _get_map(flow):
    r = flow.request("scene.mazeHandler.getMapData", {})
    if isinstance(r, dict) and r.get("code") == 200 and isinstance(r.get("data"), dict):
        return r["data"]
    return None


def _reset_cd_remaining(data):
    """按客户端 MazeDungeonManager.resetTime 公式计算服务器剩余冷却秒数。

    客户端使用 MazeDeploy.resetTime * 1000 + createTime - serverTime；
    两个时间戳均为毫秒。字段缺失或不合理时返回 None，让调用方走路由重试兜底。
    """
    try:
        create_ms = int(float(data.get("createTime")))
        server_ms = int(float(data.get("serverTime")))
    except (TypeError, ValueError, OverflowError, AttributeError):
        return None
    if create_ms <= 0 or server_ms <= 0 or server_ms < create_ms:
        return None
    remaining_ms = RESET_CD * 1000 + create_ms - server_ms
    return max(0, (remaining_ms + 999) // 1000)


def _has_partial_run(data):
    """判断是否已有进行中的地图；空入口不重置，非入口/已通关状态开跑前清理。"""
    try:
        if int(data.get("chapter") or 1) > 1 or bool(data.get("chapterPassed")):
            return True
    except (TypeError, ValueError, AttributeError):
        return False
    pos = data.get("pos") if isinstance(data, dict) else None
    return isinstance(pos, dict) and (pos.get("x") is not None or pos.get("y") is not None)


def _wait_cooldown(seconds, log):
    """等待已知冷却，不在冷却期间反复调用 nextChapter。分段休眠便于 Ctrl+C 中断。"""
    now = time.monotonic()
    wait_until = now + max(0, seconds) + 2  # 给服务端秒级计时留少量缓冲
    next_report = now + 30
    log("[星斗幻境] 下一大层有强制冷却，约等待%d秒（期间不重复请求）" % seconds)
    while True:
        now = time.monotonic()
        remaining = wait_until - now
        if remaining <= 0:
            log("[星斗幻境] 层间冷却结束，准备进入下一大层")
            return
        if now >= next_report:
            log("[星斗幻境] 层间冷却中，约剩%d秒" % int(remaining + 0.999))
            next_report = now + 30
        time.sleep(min(15, remaining, max(0.1, next_report - now)))


def _reset_partial_run(flow, data, log):
    """免费清理未完成的旧地图；只调 reset，不调用任何点券重置接口。"""
    if not _has_partial_run(data):
        return True

    def reset_confirmed(r, success_message):
        if not (isinstance(r, dict) and r.get("code") == 200):
            return False
        fresh = _get_map(flow)
        if not fresh or _has_partial_run(fresh):
            log("[星斗幻境] reset 返回成功，但新地图状态未确认；停止以免在旧进度上继续")
            return False
        log(success_message)
        return True

    chapter = int(data.get("chapter") or 1)
    pos = data.get("pos") or "入口"
    log("[星斗幻境] 检测到未完成进度(第%d大层，位置=%s)，开跑前先重置" % (chapter, pos))
    remaining = _reset_cd_remaining(data)
    if remaining is not None and remaining > 0:
        _wait_cooldown(remaining, log)

    r = flow.request("scene.mazeHandler.reset", {})
    if _is_money_err(r):
        log("[星斗幻境] 免费重置返回需消耗货币，停止且不购买: %s" % r.get("error"))
        return False
    if reset_confirmed(r, "[星斗幻境] 旧进度已免费重置，并确认回到全新地图"):
        return True

    err = r.get("error") if isinstance(r, dict) else r
    if err and ("CD" in str(err) or "冷却" in str(err) or "重置" in str(err)):
        fresh = _get_map(flow) or data
        remaining = _reset_cd_remaining(fresh)
        if remaining is None:
            log("[星斗幻境] 重置冷却无法从服务器时间确认，停止本次运行: %s" % err)
            return False
        if remaining > 0:
            _wait_cooldown(remaining, log)
        else:
            time.sleep(2)
        r = flow.request("scene.mazeHandler.reset", {})
        if reset_confirmed(r, "[星斗幻境] 等待冷却后旧进度已免费重置，并确认回到全新地图"):
            return True
        err = r.get("error") if isinstance(r, dict) else r
    log("[星斗幻境] 无法免费重置旧进度，停止本次运行: %s" % err)
    return False


def _node_weight(ev, rc):
    # 500战斗奖励/501宝箱都是【免费开了选奖励】(getRewardList->chooseReward), 不要钥匙。
    # 走格每格-5体力, 走最短路; 温泉(401)回体力设0鼓励经过; 商店(301)可买馒头略绕;
    # type0带参=服务器随机事件点, 可能因道具/星币不足"数量不足"卡死, 权重10略绕。
    t = int(ev[rc[0]][rc[1]][0])
    if t == 401:
        return 0      # 温泉: 回体力, 优先走
    if t in (201, 202, 203, 500, 501, 101):
        return 1
    if t == 301:
        return 2
    if t == 0 and int(ev[rc[0]][rc[1]][1]) != 0:
        return 10
    return 10


def _strength(data):
    """当前迷宫体力(101), 走一格耗5; 馒头(type5)服务器自动转体力。"""
    try:
        return int((data.get("mazeItem") or {}).get("101", {}).get("count") or 0)
    except Exception:
        return 0


def _find_path(mp, ev, pos):
    """安全加权 Dijkstra: 从当前位置(或第0行入口)到妖王(203), 优先普通节点、绕开道具门。
    返回下一步起的节点序列 [(row,col),...]; 若唯一通路含道具门也照走(由上层卡住时免费reset)。"""
    import heapq
    rows = len(mp)

    def neighbors(r, c):
        if r + 1 >= rows:
            return []
        out = []
        for nc in mp[r][c]:
            try:
                nci = int(nc)
            except Exception:
                continue
            if 0 <= nci < len(mp[r + 1]):
                out.append((r + 1, nci))
        return out

    def is_boss(rc):
        r, c = rc
        return ev[r][c] and int(ev[r][c][0]) == 203

    if pos and pos.get("x") is not None:
        starts = [(int(pos["x"]), int(pos["y"]))]
    else:
        starts = [(0, c) for c in range(len(mp[0])) if ev[0][c] and int(ev[0][c][0]) != 0]

    best = None
    for src in starts:
        if is_boss(src):
            return []
        dist = {src: 0}
        parent = {src: None}
        pq = [(0, src)]
        found = None
        while pq:
            du, u = heapq.heappop(pq)
            if du > dist[u]:
                continue
            if is_boss(u):
                found = u
                break
            for nb in neighbors(*u):
                nd = du + _node_weight(ev, nb)
                if nd < dist.get(nb, 1 << 30):
                    dist[nb] = nd
                    parent[nb] = u
                    heapq.heappush(pq, (nd, nb))
        if found is not None and (best is None or dist[found] < best[0]):
            chain = []
            n = found
            while n is not None:
                chain.append(n)
                n = parent[n]
            chain.reverse()
            path = chain[1:] if (pos and pos.get("x") is not None) else chain
            best = (dist[found], path)
    return best[1] if best else None


BREAD_IDS = ("5001", "5002", "5003")  # 馒头/两个馒头/一堆馒头 -> 买到自动转体力(+10/+30/+50)


def _shop_buy_bread(flow, bag, log):
    """商店节点: getShopData 拉商品, 遇到馒头(5001/5002/5003)就花星币买下(每种限购1, 服务器兜底)。
    星币不足/已限购服务器会报错且不扣点券; 买到的馒头(type5,dataType101)服务器自动转成体力。"""
    sd = flow.request("scene.mazeHandler.getShopData", {})
    if _is_money_err(sd):
        return "money_err", sd
    if not isinstance(sd, dict):
        return "ok", sd
    shop = sd.get("shop") or []
    bought = 0
    for i, item in enumerate(shop):
        gid = str(item.get("id"))
        if gid not in BREAD_IDS:
            continue
        br = flow.request("scene.mazeHandler.buy", {"index": i})
        if _is_money_err(br):
            return "money_err", br
        if isinstance(br, dict) and br.get("code") == 200:
            for it in (br.get("give") or []):
                bag["%s" % it.get("subType")] += int(it.get("count") or 0)
            log("    商店买馒头 id=%s -> %s" % (gid, br.get("give")))
            bought += 1
        else:
            log("    商店馒头 id=%s 未买(星币不足/限购): %s"
                % (gid, br.get("error") if isinstance(br, dict) else br))
        time.sleep(SLEEP)
    if bought == 0:
        log("    商店本柜无馒头或星币不足, 跳过")
    return "ok", sd


def _claim_pass_reward(flow, bag, log):
    """过关奖励: 每个战斗/宝箱节点完成后 getRewardList 拉列表, chooseReward 选一个领。
    优先选馒头(体力 5001/5002/5003, 刷到能多走格), 没有就选第1个。全程免费。"""
    rl = flow.request("scene.mazeHandler.getRewardList", {})
    if _is_money_err(rl):
        return "money_err", rl
    if not isinstance(rl, dict):
        return "ok", rl
    items = rl.get("rewardList") or rl.get("rewardItems") or []
    if not items:
        log("    过关奖励列表为空, 跳过")
        return "ok", rl
    idx, chosen = 0, items[0]
    for i, it in enumerate(items):
        st = str(it.get("subType") or "")
        if st in ("5001", "5002", "5003"):
            idx, chosen = i, it
            break
    cr = flow.request("scene.mazeHandler.chooseReward", {"index": idx})
    if _is_money_err(cr):
        return "money_err", cr
    if isinstance(cr, dict) and cr.get("error"):
        return "fail", cr
    for it in (cr.get("give") or []):
        bag["%s" % it.get("subType")] += int(it.get("count") or 0)
    log("    过关奖励 选 index=%d (%s) -> %s"
        % (idx, chosen.get("subType"), cr.get("give") if isinstance(cr, dict) else cr))
    return "ok", cr


def _handle_node(flow, event_type, bag, log):
    """走到节点后按类型处理, 返回 ('money_err'|'fail'|'ok', resp)。"""
    if event_type in BATTLE_EVENTS:
        en = flow.request("scene.mazeHandler.enterDungeon", {})
        if _is_money_err(en):
            return "money_err", en
        if isinstance(en, dict) and en.get("code") not in (None, 200) and en.get("error"):
            return "fail", en
        fin = flow.request("scene.mazeHandler.finishDungeon", {"win": 1, "time": 1})  # 结算按30秒内 -> 战斗只扣5体力(每多30秒额外+10)
        if _is_money_err(fin):
            return "money_err", fin
        if isinstance(fin, dict) and fin.get("error"):
            return "fail", fin
        for it in (fin.get("give") or []):
            bag["%s" % it.get("subType")] += int(it.get("count") or 0)
        log("    战斗胜利 event=%s 掉落=%s" % (event_type, fin.get("give") or "无"))
        # 过关奖励: 每战打完后 getRewardList -> chooseReward 选一个(优先馒头=体力)
        return _claim_pass_reward(flow, bag, log)

    if event_type == 101:  # 不明事件: 选第1项
        r = flow.request("scene.mazeHandler.selectOption", {"index": 1})
        if _is_money_err(r):
            return "money_err", r
        log("    事件选择 index=1 -> %s" % (r.get("give") if isinstance(r, dict) else r))
        return "ok", r

    if event_type == 301:  # 商店: 花星币(迷宫币100, 战斗掉落/本局清零)买馒头补体力
        return _shop_buy_bread(flow, bag, log)

    if event_type in BOX_EVENTS:  # 宝箱: 取列表, 优先馒头, 否则选第1个
        return _claim_pass_reward(flow, bag, log)

    # 401 温泉 / 0 空节点 / 其它: goto 已自动结算
    return "ok", None


def run_star_maze(flow, info=None, record_index=None):
    print("[星斗幻境] 开始, 目标一次通关 %d 大层(只走免费, 不花点券/ticket)" % MAZE_CHAPTERS)
    bag = defaultdict(int)
    logs = []

    def log(s):
        print(s)
        logs.append(s)

    chapters_done = 0
    aborted = False
    reset_used = 0
    reset_waited = 0
    cur_chapter = -1
    startup_checked = False
    for _ in range(MAX_STEPS):
        data = _get_map(flow)
        if not data:
            log("[星斗幻境] 拉取地图失败, 中止")
            aborted = True
            break
        if not startup_checked:
            startup_checked = True
            if _has_partial_run(data):
                if not _reset_partial_run(flow, data, log):
                    aborted = True
                    break
                time.sleep(SLEEP)
                continue
        mp, ev, pos = data["map"], data["event"], data.get("pos")
        chapter = int(data.get("chapter") or 1)
        if chapter != cur_chapter:
            cur_chapter = chapter
            reset_used = 0
            reset_waited = 0
        passed = bool(data.get("chapterPassed"))
        log("[星斗幻境] 第%d大层 chapterPassed=%s pos=%s 体力=%d 星币=%s" % (
            chapter, passed,
            ((pos.get("x"), pos.get("y")) if pos else "入口"),
            _strength(data),
            ((data.get("mazeItem") or {}).get("100", {}).get("count") if data.get("mazeItem") else 0)))

        if passed:
            if chapter < MAZE_CHAPTERS:
                # 客户端 resetTime = resetTime*1000 + createTime - serverTime。
                # 先按服务端时间等完第1->2层的强制间隔，避免在CD内反复请求；
                # 字段缺失/服务端仍返回CD时保留有限重试兜底。
                remaining = _reset_cd_remaining(data)
                if remaining is not None and remaining > 0:
                    _wait_cooldown(remaining, log)
                elif remaining == 0:
                    log("[星斗幻境] 服务端计时显示冷却已结束，尝试进入下一大层")
                r = None
                for attempt in range(16):  # 每15秒一次, 最多约4分钟
                    r = flow.request("scene.mazeHandler.nextChapter", {})
                    if _is_money_err(r):
                        log("[星斗幻境] 进下一层触发付费, 中止: %s" % r.get("error"))
                        aborted = True
                        break
                    if isinstance(r, dict) and r.get("code") == 200:
                        chapters_done += 1
                        log("[星斗幻境] 进入第%d大层" % (chapter + 1))
                        time.sleep(SLEEP)
                        break
                    err = r.get("error") if isinstance(r, dict) else r
                    if err and ("CD" in str(err) or "冷却" in str(err) or "重置" in str(err)):
                        log("[星斗幻境] 进下一层冷却中, 等15秒重试(%d/16)" % (attempt + 1))
                        time.sleep(15)
                        continue
                    log("[星斗幻境] nextChapter 异常: %s" % err)
                    aborted = True
                    break
                else:
                    log("[星斗幻境] 进下一层冷却等待超时, 中止(不付费)")
                    aborted = True
                if aborted:
                    break
                if isinstance(r, dict) and r.get("code") == 200:
                    continue
                aborted = True
                break
            else:
                chapters_done += 1
                log("[星斗幻境] 第%d大层(最终)妖王已通关" % chapter)
                break

        path = _find_path(mp, ev, pos)
        if path is None:
            log("[星斗幻境] 找不到通往妖王的路径, 中止本章")
            aborted = True
            break
        if not path:
            # 当前就在 boss 且已处理, 等下一轮 chapterPassed
            time.sleep(SLEEP)
            continue

        r, c = path[0]
        etype = int(ev[r][c][0])
        log("  走格 ->(%d,%d) 类型=%s 参数=%s" % (r, c, etype, ev[r][c][1]))
        g = flow.request("scene.mazeHandler.goto", {"x": r, "y": c})
        g_err = g.get("error") if isinstance(g, dict) else None
        # 真正的付费拦截 -> 立即停
        if g_err and any(h in str(g_err) for h in ("点券", "ticket", "票", "元宝", "支付", "扣费")):
            log("[星斗幻境] 走格触发付费, 立即中止: %s" % g_err)
            aborted = True
            break
        if (isinstance(g, dict) and g.get("code") not in (None, 200) and g_err) or _is_money_err(g):
            # 重拉地图判体力: 走格每格-5, 体力<5 任何格走不了。
            # 实测 reset 会整局重开并恢复体力100/星币100(回到第1章) -> 体力不足也免费reset;
            # 若体力够, 则是随机事件/机关缺道具, 同样免费重置换图(受180s冷却, CD中则等一次)
            fresh = _get_map(flow) or data
            reason = "体力不足" if _strength(fresh) < 5 else "节点被阻(%s)" % g_err
            if reset_used < MAX_RESET_PER_CHAPTER:
                rr = flow.request("scene.mazeHandler.reset", {})
                rr_err = rr.get("error") if isinstance(rr, dict) else None
                if isinstance(rr, dict) and rr.get("code") == 200:
                    reset_used += 1
                    chapters_done = 0  # 整局重开, 已通关层数归零
                    log("[星斗幻境] %s, 免费重置重开(%d/%d)" % (reason, reset_used, MAX_RESET_PER_CHAPTER))
                    time.sleep(SLEEP)
                    continue
                if rr_err and ("CD" in str(rr_err) or "冷却" in str(rr_err)) and reset_waited < 1:
                    wait_s = RESET_CD - int((data.get("serverTime", 0) - data.get("createTime", 0)) / 1000)
                    wait_s = max(10, min(wait_s, RESET_CD))
                    log("[星斗幻境] 重置CD中, 等待%d秒后重试(不付费)" % wait_s)
                    time.sleep(wait_s + 2)
                    reset_waited += 1
                    continue
                log("[星斗幻境] 节点被阻且重置不可用(不付费), 中止: %s" % rr_err)
                aborted = True
                break
            log("[星斗幻境] 走格被阻(%s)且本层重置已达上限, 中止(不购买)" % g_err)
            aborted = True
            break
        # 收集 goto 直接给的奖励(温泉401回体力/事件道具等); 馒头(type5)服务器会自动转体力
        if isinstance(g, dict):
            for it in (g.get("give") or []):
                bag["%s" % it.get("subType")] += int(it.get("count") or 0)
        # 以 goto 返回的 event 为准(通常等于地图类型)
        node_event = int(g.get("event")) if isinstance(g, dict) and g.get("event") is not None else etype
        status, resp = _handle_node(flow, node_event, bag, log)
        if status == "money_err":
            log("[星斗幻境] 节点处理触发付费, 立即中止: %s" % (resp.get("error") if isinstance(resp, dict) else resp))
            aborted = True
            break
        if status == "fail":
            log("[星斗幻境] 节点处理失败, 中止: %s" % (resp.get("error") if isinstance(resp, dict) else resp))
            aborted = True
            break
        time.sleep(SLEEP)
    else:
        log("[星斗幻境] 达到步数上限 %d, 停止(防卡死)" % MAX_STEPS)
        aborted = True

    # 只有三大层完整通关后才刷新服务器周计数，并使用免费接口领取。
    # 客户端公式: min(RewardMax, mazeCnt) - rewardMazeCnt；计数缺失时安全跳过。
    if chapters_done == MAZE_CHAPTERS and not aborted:
        refreshed_info = None
        if record_index is not None:
            refresh = flow.request("connector.entryHandler.entry",
                                   {"index": int(record_index), "userAgent": flow.user_agent})
            if isinstance(refresh, dict):
                refreshed_info = refresh.get("info")
        quota = _remaining_weekly_maze_rewards(refreshed_info)
        if quota is None:
            log("[星斗幻境] 无法读取服务器周领奖计数(mazeCnt/rewardMazeCnt)，为避免误领已跳过宝箱")
        else:
            remaining = quota["remaining"]
            log("[星斗幻境] 周宝箱次数核对: mazeCnt=%d rewardMazeCnt=%d 上限=%d 剩余=%d"
                % (quota["mazeCnt"], quota["rewardMazeCnt"], MAZE_REWARD_MAX, remaining))
            if remaining <= 0:
                log("[星斗幻境] 本周免费宝箱次数已用完，跳过领奖")
        # 周额度在各奖励档共享；只领最高档 5270，并且严格不超过刷新到的剩余次数。
        for rid in MAZE_REWARD_IDS if quota and quota["remaining"] > 0 else []:
            stock = quota["rewardStock"].get(str(rid))
            limit = min(quota["remaining"], max(0, int(stock))) if stock is not None else quota["remaining"]
            for i in range(limit):
                r = flow.request("scene.mazeHandler.getFinishRewardFree",
                                 {"type": 0, "rewardId": rid})
                if _is_money_err(r):
                    log("[星斗幻境] 免费领奖响应提示付费，立即停止，不切换点券接口: %s"
                        % (r.get("error") if isinstance(r, dict) else r))
                    break
                if isinstance(r, dict) and r.get("error"):
                    log("[星斗幻境] 周奖励 %s 第%d次不可领: %s" % (rid, i + 1, r.get("error")))
                    break
                log("[星斗幻境] 周奖励 %s 第%d次免费领取成功: %s"
                    % (rid, i + 1, r.get("give") if isinstance(r, dict) else r))
                if isinstance(r, dict):
                    for it in (r.get("give") or []):
                        bag["%s" % it.get("subType")] += int(it.get("count") or 0)
                time.sleep(SLEEP)

    log("[星斗幻境] 结束, 通关大层=%d, 收获=%s" % (chapters_done, dict(bag)))
    if bag:
        with open("drops_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), "drops": {"星斗幻境": dict(bag)}},
                               ensure_ascii=False) + "\n")
    return chapters_done, dict(bag)
