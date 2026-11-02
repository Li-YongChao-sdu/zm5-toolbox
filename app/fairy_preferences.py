"""幻兽派遣偏好：档位决定刷新，档内顺序决定当前同档任务的选择。"""
import fairy_api as api
import fairy_data as fd
REWARDS={'1级宝石盒':'101098001','幻之精华':'101035002','妖元':'101035001','天清气':'101042005','地浊气':'101042006','土灵参':'101042001','火灵参':'101042002','风灵参':'101042003','水灵参':'101042004'}
STRATEGIES={1:'① 优先最高档偏好',2:'② 尽量派满',3:'③ 命中任一偏好即派遣'}

def normalize(value=None):
    if value is None:value={}
    if not isinstance(value,dict):raise ValueError('奖励偏好格式无效')
    enabled=value.get('enabled',False);strategy=value.get('strategy',3);groups=value.get('groups',[[],[],[]]);fill=value.get('fill',False)
    if type(enabled) is not bool or type(fill) is not bool or type(strategy) is not int or strategy not in STRATEGIES:raise ValueError('奖励偏好策略无效')
    if not isinstance(groups,list) or len(groups)!=3 or any(not isinstance(group,list) for group in groups):raise ValueError('奖励偏好须为三个档位')
    seen=set()
    for group in groups:
        for name in group:
            if not isinstance(name,str) or name not in REWARDS or name in seen:raise ValueError('奖励无效或重复，请每种奖励只安排一处')
            seen.add(name)
    if enabled and not seen:raise ValueError('启用奖励偏好后，请至少选择一种奖励')
    if strategy==3:groups=[[name for group in groups for name in group],[],[]]
    return {'enabled':enabled,'strategy':strategy,'groups':[list(g) for g in groups],'fill':fill}

def reward_order(raw,settings):
    actual={str(g.get('subType')) for g in raw.get('reward',[]) if isinstance(g,dict) and g.get('type')=='item'}
    ranks=[(tier,index) for tier,group in enumerate(settings['groups']) for index,name in enumerate(group) if REWARDS[name] in actual]
    return min(ranks) if ranks else None

def choose(info,tasks,settings,positions=(0,1,2),help_=None):
    settings=normalize(settings);quota=api.quota(info,help_);slots=api.slots(info)
    if quota['sendLeft']<=0:return {'action':'stop','reason':'今日派遣次数已用完'}
    occupied={entity for row in slots.values() if api.slot_state(row)['dispatched'] for entity in row.get('fairy',[])}
    pool=[f for f in fd.list_fairies(info) if f['entityId'] not in occupied]
    free=quota['refreshFreeLeft'];top=next((i for i,g in enumerate(settings['groups']) if g),0)
    allow_fallback=free<=0 and (settings['strategy']==2 or settings['fill'])
    candidates=[];blocked=[]
    for pos in positions:
        raw=slots.get(pos)
        if not raw or api.slot_state(raw)['dispatched']:continue
        task=tasks.get(raw.get('id'))
        if not task:blocked.append({'pos':pos,'reason':'任务配置未知'});continue
        rank=reward_order(raw,settings)
        if settings['enabled']:
            if rank is None and not allow_fallback:continue
            if settings['strategy'] in (1,2) and free>0 and (rank is None or rank[0]!=top):continue
        pick=fd.pick_fairies(task,pool)
        if not pick.get('ok'):blocked.append({'pos':pos,'reason':pick.get('reason')});continue
        fallback=settings['enabled'] and rank is None
        order=rank if rank is not None else (3,0)
        if not settings['enabled']:order=(0,0)
        score=(*order,-task.get('level',0) if fallback else 0,pick.get('secondary_is_primary',False),pick['second']['step'],pick['first']['step'],pos)
        if not settings['enabled']:score=(pos,)
        candidates.append((score,{'action':'dispatch','pos':pos,'ids':[pick['first']['entityId'],pick['second']['entityId']],
                                 'fairies':[pick['first'],pick['second']],'rank':rank,'fallback':fallback,'reward':raw.get('reward',[])}))
    if candidates:return min(candidates,key=lambda row:row[0])[1]
    idle=any(slots.get(pos) and not api.slot_state(slots[pos])['dispatched'] for pos in positions)
    if settings['enabled'] and free>0 and idle:
        # The game refreshes ALL idle slots. Restricted-slot execution must not change other idle slots.
        outside=[pos for pos,raw in slots.items() if pos not in positions and not api.slot_state(raw)['dispatched']]
        if outside:return {'action':'stop','reason':'刷新会同时改变范围外的空闲档位，已停止刷新；可改选全部档位','blocked':blocked}
        return {'action':'refresh','blocked':blocked}
    return {'action':'stop','reason':'没有符合偏好且能匹配幻兽的任务，或免费刷新已用尽','blocked':blocked}
