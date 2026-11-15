"""竞技场／斗宠界面策略的本地记忆；只保存设置，不保存对手查询确认结果。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def daily_rounds(now=None):
    """当天免费挑战次数：周五/六/日10次，周一至周四5次（jjcChallengeNum 按周日~周六排列）。"""
    now = now or datetime.now(timezone(timedelta(hours=8)))
    return 10 if now.weekday() in (4, 5, 6) else 5


FIELDS = {
    'arena': (
        ('mode', 'var_arena_mode'),
        ('target_uid', 'var_arena_target_uid'),
        ('target_r_number', 'var_arena_target_r_number'),
        ('top_n', 'var_arena_top_n'),
        ('input', 'var_arena_target_input'),
        ('rid', 'var_arena_target_rid'),
        ('battle_wait', 'var_arena_battle_wait'),
        ('round_wait', 'var_arena_round_wait'),
    ),
    'petArena': (
        ('mode', 'var_pet_arena_mode'),
        ('target_uid', 'var_pet_arena_target_uid'),
        ('target_r_number', 'var_pet_arena_target_r_number'),
        ('top_n', 'var_pet_arena_top_n'),
        ('input', 'var_pet_arena_target_input'),
        ('rid', 'var_pet_arena_target_rid'),
        ('battle_wait', 'var_pet_arena_battle_wait'),
        ('round_wait', 'var_pet_arena_round_wait'),
    ),
}


def variables(app):
    return [getattr(app, name) for fields in FIELDS.values() for _, name in fields]


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def restore(app, data):
    for handler, fields in FIELDS.items():
        row = data.get(handler)
        if not isinstance(row, dict):
            continue
        for key, name in fields:
            if key in row:
                try:
                    getattr(app, name).set(row[key])
                except Exception:
                    pass


def save(path, app):
    data = {handler: {key: getattr(app, name).get() for key, name in fields}
            for handler, fields in FIELDS.items()}
    bits = ''.join('1' if var.get() else '0'
                   for var in app.spend_permissions.variables['dungeons'])
    data['hidden_unlock'] = bits == '001'
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
