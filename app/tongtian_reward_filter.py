"""通天河等级奖励表；满额指可抢的标准最高比例，不是整船货物。"""
import json,math
from pathlib import Path
from functools import lru_cache
ROOT=Path(__file__).resolve().parent

@lru_cache(maxsize=1)
def rates():
    paths=[p/'TongtianRiver.json' for p in sorted(ROOT.glob('cg_config_out_cg1_*'),reverse=True)]
    path=next((p for p in paths if p.is_file()),None)
    if path is None:raise ValueError('缺少通天河等级奖励配置，已停止抢船')
    text=json.loads(path.read_text(encoding='utf-8-sig'))['1']['robLevelReward']
    result={int(k):float(v) for k,v in (part.split(',') for part in text.split(';'))}
    if not result or any(not math.isfinite(v) or v<=0 for v in result.values()):raise ValueError('通天河等级奖励配置异常')
    return result

def full_reward(own_level,target_level,table=None):
    table=rates() if table is None else table
    delta=own_level-target_level
    return abs(delta)<=10 and table.get(delta,0)>=max(table.values())

def target_range(level):
    table=rates();levels=[level-d for d in table if level-d>0 and full_reward(level,level-d,table)]
    return min(levels),max(levels)

def explanation():
    table=rates();deltas=[d for d in table if abs(d)<=10 and table[d]>=max(table.values())]
    return '船主可低于自身最多%s级、高于自身最多%s级；保持正常可抢奖励比例'%(max(deltas),-min(deltas))
