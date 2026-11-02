"""我的日常附加任务，复用趣味活动设置，不进入主日常任务页。"""
import math
DEFINITIONS=(
 ('RUN_FUN_BLACK_MARKET','黑市灵魂日常','black','黑市','仅买灵魂商品，并使用VIP剩余免费刷新；不花点券'),
 ('RUN_FUN_COLLECT_REWARD','领取采集奖励','reward','宠物采集','普通领取原页面选中位置；未完成或已领取时跳过'),
 ('RUN_FUN_COLLECT_START','派遣宠物采集','start','宠物采集','沿用原页面的位置、材料、宠物和时长'),
 ('RUN_FUN_MONSTER_CARD','妖王帖免费抽取','card','妖王帖','沿用原页面次数；仅剩余免费次数'),
 ('RUN_FUN_CARD_CAVE','藏宝洞免费挑战','cave','藏宝洞','沿用模式、次数、间隔和已确认的指定码；仅免费次数'),
 ('RUN_FUN_FAIRY_FEED','幻兽喂养','feed','幻兽喂养','沿用原页面的幻兽、喂养角色、方式和次数'),
)
BY_KEY={r[0]:r for r in DEFINITIONS}
def catalog(base):return list(base)+[(label,key,False,False,note) for key,label,kind,page,note in DEFINITIONS]
def pages(base):return {**base,'趣味活动':tuple(BY_KEY)}
def build_plan(app,keys,account,slot):
    labels=[label for key,label,kind,page,note in DEFINITIONS if key in keys]
    return app.fun_batch_page.build(labels,account,slot) if labels else None

def validate_plan(keys,plan,uid,slot):
    selected=[row for row in DEFINITIONS if row[0] in keys]
    if not selected:
        if plan and plan.get('jobs'):raise ValueError('存在未选择的趣味活动计划')
        return []
    if not isinstance(plan,dict) or str(plan.get('uid'))!=str(uid) or plan.get('slot')!=slot:raise ValueError('趣味活动计划的账号或存档不符')
    jobs=plan.get('jobs')
    if not isinstance(jobs,list) or len(jobs)!=len(selected):raise ValueError('趣味活动计划数量不符')
    fields={'black':set(),'reward':{'pos'},'start':{'pos','collect_id','entity','gear'},'card':{'count'},'cave':{'matches','wait','mode','code','fingerprint'},'feed':{'entity_id','times','use_item'},'feed_role':{'entity_id','times','use_item','role'}}
    for job,(_,label,kind,_,_) in zip(jobs,selected):
        allowed=fields[kind+'role'] if kind=='feed' and 'role' in job.get('args',{}) else fields['feed'] if kind=='feed' else fields[kind]
        if job.get('kind')!=kind or job.get('label')!=label or not isinstance(job.get('args'),dict) or set(job['args'])!=allowed:raise ValueError('包含未选择或不支持的趣味活动')
        a=job['args']
        if kind in ('reward','start') and (type(a['pos'])!=int or not 0<=a['pos']<=2):raise ValueError('采集位置无效')
        if kind=='start' and (type(a['collect_id'])!=int or a['collect_id']<=0 or type(a['gear'])!=int or not 0<=a['gear']<=2 or not isinstance(a['entity'],str) or not a['entity']):raise ValueError('采集派遣参数无效')
        if kind=='card' and (type(a['count'])!=int or a['count']<0):raise ValueError('免费妖王帖次数无效')
        if kind=='cave':
            if type(a['matches'])!=int or not 1<=a['matches']<=5 or not math.isfinite(float(a['wait'])) or not 0<=float(a['wait'])<=3600 or a['mode'] not in ('recommend','specified'):raise ValueError('藏宝洞参数无效')
            if a['mode']=='specified' and (not isinstance(a['code'],str) or not a['code'] or not isinstance(a['fingerprint'],str) or not a['fingerprint']):raise ValueError('指定藏宝洞未确认')
        if kind=='feed' and (not isinstance(a['entity_id'],str) or not a['entity_id'] or type(a['use_item'])!=bool or (a['times'] is not None and (type(a['times'])!=int or a['times']<=0)) or ('role' in a and a['role'] not in (0,1))):raise ValueError('幻兽喂养参数无效')
    return jobs
