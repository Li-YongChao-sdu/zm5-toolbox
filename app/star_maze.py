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
  先领已有最高档周箱，周额度已满就跳过；否则续接地图，三层通关领奖后免费重置一次。

只用免费领奖及普通reset；不调用点券额外奖励、复活或购买体力。
重置仅用于确实无路/体力耗尽，或通关且领奖确认后的收尾；网络异常不当作重置理由。
"""
import json
import copy
import time
from collections import defaultdict

SLEEP = 1.0
MAX_STEPS = 120
MAZE_CHAPTERS = 3
MAX_RECOVERY_RESETS = 2     # 单次任务的故障换图总上限，进入/重回第一层不清零
RESET_CD = 180              # reset 冷却秒数(MazeDeploy.resetTime)
# 每大层周奖励箱 rewardId(MazeDeploy.mazeReward), 仅用 getFinishRewardFree 免费领
MAZE_REWARD_IDS = [5270]   # 用户指定只领最高档（翡翠），不回退到5094/5137
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
    return isinstance(r, dict) and r.get("code") == 200 and not r.get("error")


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
        "weekly_left": max(0, int(reward_max) - claimed_count),
        "rewardStock": weekly.get("mazeReward") or {},
    }


def _get_map(flow):
    r = flow.request("scene.mazeHandler.getMapData", {})
    if isinstance(r, dict) and r.get("code") == 200 and isinstance(r.get("data"), dict):
        data = copy.deepcopy(r['data'])
        for key in ('createTime', 'serverTime'):
            if key not in data and key in r:
                data[key] = r[key]
        return data
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
    log("[星斗幻境] 地图冷却约剩%d秒，等待后继续（期间不重复请求）" % seconds)
    while True:
        now = time.monotonic()
        remaining = wait_until - now
        if remaining <= 0:
            log("[星斗幻境] 冷却等待结束")
            return
        if now >= next_report:
            log("[星斗幻境] 层间冷却中，约剩%d秒" % int(remaining + 0.999))
            next_report = now + 30
        time.sleep(min(15, remaining, max(0.1, next_report - now)))


def _progress(data):
    return tuple(copy.deepcopy(data.get(k)) for k in ('createTime', 'chapter', 'pos', 'chapterPassed'))


def _cooldown_error(reply):
    error = str((reply or {}).get('error') or '').lower()
    return ('cd' in error or '冷却' in error or
            ('重置' in error and any(w in error for w in ('分钟', '秒', '间隔'))))


def _wait_map(flow, data, log):
    remaining = _reset_cd_remaining(data)
    if remaining is None:
        raise RuntimeError('无法读取服务器地图冷却时间，保留当前进度')
    if remaining:
        _wait_cooldown(remaining, log)
        fresh = _get_map(flow)
        if not fresh or _progress(fresh) != _progress(data):
            raise RuntimeError('等待期间地图进度变化，停止，不覆盖当前地图')
        return fresh
    return data


def _reset_run(flow, data, log, reason):
    """已明确需要重置时才调用；未知写结果不重发，成功后回读入口。"""
    log('[星斗幻境] %s，准备免费重置' % reason)
    for attempt in range(2):
        data = _wait_map(flow, data, log)
        reply = flow.request('scene.mazeHandler.reset', {})
        if _ok(reply):
            if reply.get('consume'):
                raise RuntimeError('重置返回额外消耗，停止')
            fresh = _get_map(flow)
            if not fresh or _has_partial_run(fresh):
                raise RuntimeError('重置回包成功但未确认回到全新第一层，停止')
            log('[星斗幻境] 已确认回到全新第一层入口')
            return
        if attempt == 0 and isinstance(reply, dict) and _cooldown_error(reply):
            fresh = _get_map(flow)
            if not fresh or _progress(fresh) != _progress(data):
                raise RuntimeError('重置拒绝后地图状态不一致，停止')
            if _reset_cd_remaining(fresh) == 0:
                time.sleep(2)
            data = fresh
            continue
        raise RuntimeError('免费重置未成功，停止且不切换付费接口：%s' % (reply or {}).get('error'))


def _weekly_info(flow, record_index, expected):
    if record_index is None:
        raise RuntimeError('缺少出战槽位，不能确认周宝箱状态')
    reply = flow.request('connector.entryHandler.entry',
                         {'index': int(record_index), 'userAgent': flow.user_agent})
    if not _ok(reply) or not isinstance(reply.get('info'), dict):
        raise RuntimeError('读取周宝箱状态失败，保留地图')
    info = copy.deepcopy(reply['info'])
    if not info.get('uid') or not info.get('_id'):
        raise RuntimeError('周宝箱存档身份字段缺失，停止')
    for key in ('uid', '_id'):
        if expected.get(key) is not None and str(info.get(key)) != str(expected[key]):
            raise RuntimeError('存档身份变化，停止星斗任务')
    before_reset = (expected.get('everyWeekSetting') or {}).get('resetTime')
    if before_reset is not None and (info.get('everyWeekSetting') or {}).get('resetTime') != before_reset:
        raise RuntimeError('周计数期次已变化，停止星斗任务')
    quota = _remaining_weekly_maze_rewards(info)
    weekly = info.get('everyWeekSetting') or {}
    # 完整entry在新周未玩过星斗时可省略全部三个零值字段；原版初值为0/0/{}。
    # 仅接受完整周时间及三个字段同时缺省，不把部分缺字段或有库存的状态猜成0。
    if quota is None and not any(k in weekly for k in ('mazeCnt', 'rewardMazeCnt', 'mazeReward')):
        reset_ms, server_ms = weekly.get('resetTime'), info.get('serverTime')
        if (type(reset_ms) in (int, float) and type(server_ms) in (int, float)
                and 0 < reset_ms <= server_ms):
            weekly.update(mazeCnt=0, rewardMazeCnt=0, mazeReward={})
            quota = _remaining_weekly_maze_rewards(info)
    if quota is None:
        raise RuntimeError('服务器周计数缺失，不能判断是否需挑战，保留地图')
    return info, quota


def _item_count(info, item_id):
    return sum(int(v.get('count') or 0) for k, v in
               (((info.get('bag') or {}).get('item') or {}).items())
               if isinstance(v, dict) and str(v.get('id', k)) == str(item_id))


def _claim_emerald(flow, record_index, expected, bag, log):
    """每次只领5270；回读计数、库存和give入包后才允许下一笔。"""
    info, quota = _weekly_info(flow, record_index, expected)
    claimed = 0
    while quota['remaining'] > 0:
        stock = quota['rewardStock'].get('5270', 0)
        if type(stock) is not int or stock < 0:
            raise RuntimeError('翡翠周箱库存格式未知，停止，不尝试低级宝箱')
        if stock == 0:
            break
        reply = flow.request('scene.mazeHandler.getFinishRewardFree', {'type': 0, 'rewardId': 5270})
        if not _ok(reply) or reply.get('consume'):
            raise RuntimeError('翡翠周箱领取未确认，保留地图且不重复请求')
        fresh, after = _weekly_info(flow, record_index, info)
        if (after['rewardMazeCnt'] != quota['rewardMazeCnt'] + 1 or
                after['mazeCnt'] != quota['mazeCnt'] or
                after['rewardStock'].get('5270', 0) != stock - 1):
            raise RuntimeError('周箱领取后计数/库存不符，停止，不重置地图')
        give = reply.get('give') or []
        if not give:
            raise RuntimeError('周箱回包没有奖励明细，停止核查')
        totals = defaultdict(int)
        for item in give:
            if item.get('type') != 'item' or int(item.get('count') or 0) <= 0:
                raise RuntimeError('周箱奖励类型未知，停止核查')
            totals[str(item['subType'])] += int(item['count'])
        for item_id, count in totals.items():
            if _item_count(fresh, item_id) - _item_count(info, item_id) != count:
                raise RuntimeError('周箱奖励入包与回包不符，停止核查')
            bag[item_id] += count
        log('[星斗幻境] 翡翠周箱领取并核对成功，本周已领%d/%d' %
            (after['rewardMazeCnt'], MAZE_REWARD_MAX))
        claimed += 1
        info, quota = fresh, after
    return info, quota, claimed


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


def _find_path(mp, ev, pos, excluded=()):
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
            if 0 <= nci < len(mp[r + 1]) and (r + 1, nci) not in excluded:
                out.append((r + 1, nci))
        return out

    def is_boss(rc):
        r, c = rc
        return ev[r][c] and int(ev[r][c][0]) == 203

    if pos and pos.get("x") is not None:
        starts = [(int(pos["x"]), int(pos["y"]))]
    else:
        starts = [(0, c) for c in range(len(mp[0])) if ev[0][c] and int(ev[0][c][0]) != 0 and (0, c) not in excluded]

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
    if not _ok(rl):
        return "fail", rl
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
    if not _ok(cr):
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
        if not _ok(en):
            return "fail", en
        fin = flow.request("scene.mazeHandler.finishDungeon", {"win": 1, "time": 1})  # 结算按30秒内 -> 战斗只扣5体力(每多30秒额外+10)
        if _is_money_err(fin):
            return "money_err", fin
        if not _ok(fin):
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
        if not _ok(r):
            return 'fail', r
        log("    事件选择 index=1 -> %s" % (r.get("give") if isinstance(r, dict) else r))
        return "ok", r

    if event_type == 301:  # 商店: 花星币(迷宫币100, 战斗掉落/本局清零)买馒头补体力
        return _shop_buy_bread(flow, bag, log)

    if event_type in BOX_EVENTS:  # 宝箱: 取列表, 优先馒头, 否则选第1个
        return _claim_pass_reward(flow, bag, log)

    # 401 温泉 / 0 空节点 / 其它: goto 已自动结算
    return "ok", None


def _next_chapter(flow, data, log):
    chapter = int(data['chapter'])
    for attempt in range(2):
        data = _wait_map(flow, data, log)
        reply = flow.request('scene.mazeHandler.nextChapter', {})
        if _ok(reply):
            fresh = _get_map(flow)
            if not fresh or int(fresh.get('chapter') or 1) != chapter + 1:
                raise RuntimeError('下一层回包成功但进度未确认，停止，不重复推进')
            log('[星斗幻境] 已确认进入第%d大层' % (chapter + 1))
            return
        if attempt == 0 and isinstance(reply, dict) and _cooldown_error(reply):
            fresh = _get_map(flow)
            if not fresh or _progress(fresh) != _progress(data):
                raise RuntimeError('下一层被拒后地图变化，停止')
            if _reset_cd_remaining(fresh) == 0:
                time.sleep(2)
            data = fresh
            continue
        raise RuntimeError('进入下一层失败，保留地图：%s' %
                           (reply.get('error') if isinstance(reply, dict) else reply))


def _blocked_node(reply):
    error = str((reply or {}).get('error') or '')
    return any(word in error for word in ('体力不足', '数量不足', '道具不足', '物品不足',
                                         '星币不足', '缺少道具', '无法通行', '不可通行', '机关'))


def run_star_maze(flow, info=None, record_index=None):
    print('[星斗幻境] 先领翡翠周箱；未领满则续接进度，通关领奖后重置一次')
    bag = defaultdict(int)
    log = print
    chapters_done = 0
    reset_used = 0
    excluded = set()
    map_key = None

    def finish():
        log('[星斗幻境] 结束，当前已通大层=%d，收获=%s' % (chapters_done, dict(bag)))
        if bag:
            with open('drops_log.jsonl', 'a', encoding='utf-8') as stream:
                stream.write(json.dumps({'ts': int(time.time()), 'drops': {'星斗幻境': dict(bag)}},
                                        ensure_ascii=False) + '\n')
        return chapters_done, dict(bag)

    def recover(data, reason):
        nonlocal reset_used, chapters_done
        if reset_used >= MAX_RECOVERY_RESETS:
            raise RuntimeError('本次换图已达%d次上限，保留当前进度' % MAX_RECOVERY_RESETS)
        _reset_run(flow, data, log, reason)
        reset_used += 1
        chapters_done = 0
        excluded.clear()

    try:
        anchor, quota, initially_claimed = _claim_emerald(flow, record_index, info or {}, bag, log)
        if quota['weekly_left'] == 0:
            if initially_claimed:
                completed_map = _get_map(flow)
                if not completed_map:
                    raise RuntimeError('补领后无法确认地图，保留现状')
                if (int(completed_map.get('chapter') or 1) == MAZE_CHAPTERS
                        and completed_map.get('chapterPassed')):
                    _reset_run(flow, completed_map, log, '已通关地图的翡翠补领完成，收尾')
                    chapters_done = MAZE_CHAPTERS
            log('[星斗幻境] 本周已领满，%s' %
                ('收尾完成，不再挑战' if chapters_done else '跳过挑战和重置'))
            return finish()
        log('[星斗幻境] 本周尚余%d次周领奖额度；只补本次三大层通关' % quota['weekly_left'])

        first_map = True
        for _ in range(MAX_STEPS):
            data = _get_map(flow)
            if not data:
                raise RuntimeError('拉取地图失败，保留当前进度')
            chapter = int(data.get('chapter') or 1)
            if chapter not in (1, 2, 3):
                raise RuntimeError('未知地图层级，停止')
            key = (data.get('createTime'), chapter)
            if key != map_key:
                excluded.clear()
                map_key = key
            passed = bool(data.get('chapterPassed'))
            if first_map:
                first_map = False
                if passed and chapter == MAZE_CHAPTERS and initially_claimed == 0:
                    # 旧图已经结束、也没有翡翠可领；确实没有下一步可续走。
                    recover(data, '旧地图已经通关且无翡翠可领，本周未满，需要补一轮通关')
                    continue
            chapters_done = max(chapters_done, chapter if passed else chapter - 1)
            log('[星斗幻境] 续接第%d大层，已通关=%s，位置=%s，体力=%d' %
                (chapter, passed, data.get('pos'), _strength(data)))

            if passed:
                if chapter < MAZE_CHAPTERS:
                    _next_chapter(flow, data, log)
                    time.sleep(SLEEP)
                    continue
                # 必须先确认当前周箱状态；任何领奖异常都保留通关地图。
                _, final_quota, _ = _claim_emerald(flow, record_index, anchor, bag, log)
                if '5270' not in final_quota['rewardStock']:
                    raise RuntimeError('通关后翡翠库存未返回，保留地图，不做收尾重置')
                if final_quota['remaining'] > 0 and final_quota['rewardStock']['5270'] > 0:
                    raise RuntimeError('翡翠周箱仍可领取但尚未确认，保留地图')
                fresh = _get_map(flow)
                if not fresh or _progress(fresh) != _progress(data):
                    raise RuntimeError('领奖后地图变化，停止，不覆盖其它操作的进度')
                _reset_run(flow, fresh, log, '三大层已完成，周箱状态已核对，收尾')
                log('[星斗幻境] 本次通关收尾完成，不在重置后再次开跑')
                return finish()

            if _strength(data) < 5:
                recover(data, '当前体力不足以走下一格')
                continue
            mp, ev, pos = data['map'], data['event'], data.get('pos')
            path = _find_path(mp, ev, pos, excluded)
            if path is None:
                recover(data, '已找不到通往妖王的可行路径')
                continue
            if not path:
                # 断线等情况可能停在妖王格但尚未完成；只处理这一个当前节点。
                status, _ = _handle_node(flow, 203, bag, log)
                if status != 'ok':
                    raise RuntimeError('当前妖王节点处理失败，保留地图')
                fresh = _get_map(flow)
                if not fresh or not fresh.get('chapterPassed'):
                    raise RuntimeError('妖王结算未确认，不重复提交')
                continue

            row, col = path[0]
            reply = flow.request('scene.mazeHandler.goto', {'x': row, 'y': col})
            if not _ok(reply):
                if not isinstance(reply, dict) or not _blocked_node(reply):
                    raise RuntimeError('走格未成功且不是明确道路阻塞，保留地图：%s' %
                                       (reply.get('error') if isinstance(reply, dict) else reply))
                fresh = _get_map(flow)
                if not fresh or _progress(fresh) != _progress(data):
                    raise RuntimeError('走格拒绝后进度不一致，不重置地图')
                if _strength(fresh) >= 5:
                    excluded.add((row, col))
                    alternate = _find_path(fresh['map'], fresh['event'], fresh.get('pos'), excluded)
                    if alternate:
                        log('[星斗幻境] 当前道路受阻，改走其它可行路径，不重置')
                        continue
                recover(fresh, '道路受阻且没有其它可行路线')
                continue

            for item in reply.get('give') or []:
                bag[str(item.get('subType'))] += int(item.get('count') or 0)
            event = int(reply.get('event')) if reply.get('event') is not None else int(ev[row][col][0])
            status, response = _handle_node(flow, event, bag, log)
            if status != 'ok':
                raise RuntimeError('节点处理未成功，保留地图，不因业务/网络错误自动重置：%s' %
                                   (response.get('error') if isinstance(response, dict) else response))
            time.sleep(SLEEP)
        raise RuntimeError('达到步数上限，保留当前进度，不做收尾重置')
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        log('[星斗幻境] 已停止：%s' % exc)
        return finish()
