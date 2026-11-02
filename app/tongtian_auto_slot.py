"""发船/刷新自动使用主角色等级最低且不低于40级的存档。"""
def select(records):
    if not isinstance(records,list):raise ValueError('未读取到账号存档列表，已中止发船')
    candidates=[]
    for row in records:
        if not isinstance(row,dict):continue
        slot=row.get('index');level=(row.get('p1') or {}).get('level')
        if type(slot) is not int or not 0<=slot<=7:continue
        if type(level) not in (int,float) or level<40 or int(level)!=level:continue
        candidates.append((int(level),slot))
    if not candidates:raise ValueError('没有主角色等级≥40的可用存档，已中止发船／刷新')
    level,slot=min(candidates)
    return slot,level

def connect_auto(connect=None):
    if connect is None:
        from main_farm import _connect
        connect=_connect
    from teacher_trial import enter,checked
    flow=connect()
    try:
        q=checked(flow.request('connector.roleHandler.getUserInfo',{}),'读取账号存档')
        slot,level=select((q.get('user') or {}).get('records'))
        info=enter(flow,slot)
        actual=(info.get('p1') or {}).get('level')
        if type(actual) not in (int,float) or actual<40:raise ValueError('选中存档的实际等级不满足40级，已中止')
        print('[通天河自动存档] 槽%s，主角色Lv%s；按最低等级≥40选择，同级优先槽号小者'%(slot,actual),flush=True)
        return flow,info,slot,int(actual)
    except Exception:
        flow.disconnect();raise
