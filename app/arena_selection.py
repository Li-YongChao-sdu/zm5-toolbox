"""竞技场、斗宠推荐对手选择；战力缺失时不伪造为零。"""
import math
import random

MODES=('fixed','refresh','highest','lowest')
def opponent_power(row, handler):
    if handler=='petArena':
        if row.get('totalScore') is not None and row.get('battleScore') is not None:
            value=float(row['totalScore'])-float(row['battleScore'])
        else:
            pets=row.get('pets') or []
            if not pets or any(p.get('fightPower') is None for p in pets):return None
            value=sum(float(p['fightPower']) for p in pets)
    else:
        player=row.get('p1') if int(row.get('index') or 0)==0 else row.get('p2')
        if not player or player.get('fightPower') is None:return None
        value=float(player['fightPower'])
    return value if math.isfinite(value) and value>=0 else None

def choose_opponent(rows,handler,mode,previous=None):
    rows=[r for r in rows if r.get('rid')]
    if not rows:raise ValueError('推荐对手列表为空')
    if mode in ('highest','lowest'):
        ranked=[]
        for row in rows:
            try:power=opponent_power(row,handler)
            except (TypeError,ValueError):power=None
            if power is not None:ranked.append((power,row))
        if not ranked:raise ValueError('推荐列表无可确认战力，未随机替代')
        target=(max if mode=='highest' else min)(ranked,key=lambda pair:pair[0])[1]
        return target
    choices=[r for r in rows if r['rid']!=previous] or rows
    return random.choice(choices)
