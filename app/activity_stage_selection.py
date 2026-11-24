"""悬赏活动只选择已通关且当前可免费进入的普通主线。"""
def choose_normal_stage(stages, info, dungeon_table):
    from daily_auto import _dungeon_rec

    level = max(int((info.get(role) or {}).get('level') or 0) for role in ('p1', 'p2'))
    candidates = []
    for stage in stages:
        config = dungeon_table.get(str(stage['mid'])) or {}
        if config.get('difficult') != 0:
            continue
        if level < int(stage.get('rolelevel', 0)):
            continue
        record = _dungeon_rec(info, stage['mid']) or {}
        if int(record.get('passNum') or 0) < 1:
            continue
        maximum = int(config.get('dailyCountMax', 0))
        if maximum >= 0 and int(record.get('dailyCount') or 0) >= maximum:
            continue
        candidates.append(stage)
    return max(candidates, key=lambda stage: (float(stage['probability']), stage['mid'])) if candidates else None
