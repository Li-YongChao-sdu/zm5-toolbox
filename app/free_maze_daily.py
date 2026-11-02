"""Complete the free-maze daily activity using a ranked public maze."""

import time


TASK_ID = 990020
TARGET_RUNS = 3
MIN_ATTEMPTS = 100
HIGH_RATE = 0.95
LOW_RATE = 0.10
RANK_SOURCES = ((100, 20), (110, 1), (90, 20))
# Known public examples are checked against live server statistics before use.
FALLBACKS = {"high": (2346158809, 0), "low": (421532421, 0)}


def _checked(flow, route, data):
    response = flow.request(route, data)
    if not isinstance(response, dict) or response.get("code") != 200 or response.get("error"):
        raise RuntimeError("%s: %s" % (route, response.get("error") if isinstance(response, dict) else response))
    return response


def _task(flow):
    listed = _checked(flow, "scene.questHandler.getQuestList", {})
    return next((q for q in listed.get("quest") or []
                 if int(q.get("id") or 0) == TASK_ID), None)


def _progress(task):
    return int(((task or {}).get("progress") or {}).get("0") or 0)


def _candidate(row, mode, own_uid):
    try:
        uid = int(row.get("uid") or str(row.get("_id")).split("_", 1)[0])
        pos = int(str(row.get("_id")).split("_", 1)[1])
        attempts = int(row.get("inCnt") or 0)
        clears = int(row.get("outCnt") or 0)
    except (TypeError, ValueError, IndexError):
        return None
    if uid == own_uid or attempts < MIN_ATTEMPTS or not 0 <= clears <= attempts:
        return None
    rate = clears / attempts
    if mode == "high" and rate <= HIGH_RATE:
        return None
    if mode == "low" and rate >= LOW_RATE:
        return None
    return {"uid": uid, "pos": pos, "attempts": attempts,
            "clears": clears, "rate": rate}


def _maze_data(flow, uid, pos):
    response = _checked(flow, "scene.userMazeHandler.getMazeData", {"uid": uid, "pos": pos})
    data = response.get("data") or {}
    if str(data.get("_id")) != "%s_%s" % (uid, pos):
        raise RuntimeError("迷宫资料与目标不符")
    return data


def select_mazes(flow, mode, own_uid, count=1):
    if mode not in ("high", "low"):
        raise ValueError("迷宫模式须为 high 或 low")
    candidates = {}
    for rank_type, max_pages in RANK_SOURCES:
        for page in range(1, max_pages + 1):
            response = _checked(flow, "scene.userMazeHandler.getRank",
                                {"type": rank_type, "page": page})
            rows = response.get("rows") or []
            for row in rows:
                found = _candidate(row, mode, own_uid)
                if found:
                    candidates[(found["uid"], found["pos"])] = found
            if not rows or len(candidates) >= count * 3:
                break
        if len(candidates) >= count * 3:
            break
    if not candidates:
        uid, pos = FALLBACKS[mode]
        candidates[(uid, pos)] = {"uid": uid, "pos": pos}
    # Higher sample size makes the displayed pass rate more meaningful.
    selected = []
    for choice in sorted(candidates.values(), key=lambda x: x.get("attempts", 0), reverse=True):
        try:
            data = _maze_data(flow, choice["uid"], choice["pos"])
            verified = _candidate(data, mode, own_uid)
            if verified:
                selected.append(verified)
                if len(selected) >= count:
                    return selected
        except RuntimeError:
            continue
    raise RuntimeError("只找到%d/%d个符合筛选条件的迷宫" % (len(selected), count))


def run_free_maze(flow, mode="high", own_uid=0, target_code="", fingerprint="", wait=30):
    from maze_target import wait_seconds
    wait=wait_seconds(wait)
    if mode not in ("high", "low", "specified"):raise ValueError("迷宫挑战方式无效")
    task = _task(flow)
    if task is None:
        print("[迷宫活跃] 当前存档没有迷宫挑战任务，跳过")
        return 0
    if int(task.get("status") or 0) == 3:
        print("[迷宫活跃] 今日任务已领取，跳过")
        return 0
    completed = min(_progress(task), TARGET_RUNS)
    if completed >= TARGET_RUNS or int(task.get("status") or 0) == 2:
        print("[迷宫活跃] 已完成，尝试领取任务")
    else:
        remaining = TARGET_RUNS - completed
        if mode == "specified":
            from maze_target import query
            specified = query(flow, target_code)
            if specified['uid'] == int(own_uid):raise ValueError('原客户端不支持挑战自己的迷宫')
            if not fingerprint or specified['fingerprint'] != fingerprint:raise ValueError('指定迷宫已变化，请重新查询并确认')
            choices = [{**specified, 'rate': specified['clears'] / specified['attempts'] if specified['attempts'] else 0}]
        else:
            choices = select_mazes(flow, mode, int(own_uid),
                                   1 if mode == "high" else remaining)
        print("[迷宫活跃] %s模式：%s" %
              ("指定迷宫" if mode == "specified" else ("高通关率" if mode == "high" else "低通关率"),
               "；".join("%s_%s（挑战%d次，通关率%.2f%%）" %
                        (maze["uid"], maze["pos"], maze["attempts"], maze["rate"] * 100)
                        for maze in choices)))
        starting_progress = completed
        for number in range(starting_progress + 1, TARGET_RUNS + 1):
            chosen = choices[0] if mode in ("high", "specified") else choices[number - starting_progress - 1]
            # Recheck map availability and current statistics before entering.
            data = _maze_data(flow, chosen["uid"], chosen["pos"])
            if mode == "specified":
                from maze_target import query
                if query(flow, target_code)['fingerprint'] != fingerprint:
                    raise RuntimeError('指定迷宫布局已变化，停止')
            elif not _candidate(data, mode, int(own_uid)):
                print("[迷宫活跃] 迷宫通关率已不符合所选条件，停止")
                break
            from maze_target import play_once
            play_once(flow, chosen['uid'], chosen['pos'], wait=wait)
            current = _task(flow)
            new_progress = _progress(current)
            print("[迷宫活跃] 第%d次结算，任务进度 %d/%d" %
                  (number, new_progress, TARGET_RUNS))
            if new_progress <= completed:
                print("[迷宫活跃] 服务器未增加任务进度，停止")
                break
            completed = new_progress
            if number < TARGET_RUNS:
                time.sleep(5)
    final_task = _task(flow)
    if final_task and int(final_task.get("status") or 0) == 2:
        reward = _checked(flow, "scene.questHandler.commitQuest", {"qId": TASK_ID})
        print("[迷宫活跃] 任务奖励已领取：%s" % (reward.get("give") or []))
    return completed
