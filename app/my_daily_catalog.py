"""我的日常附加任务，复用趣味活动设置，不进入主日常任务页。"""
import math
DEFINITIONS=(
 ('RUN_FUN_BLACK_MARKET','黑市灵魂日常','black','黑市','仅买灵魂商品，并使用VIP剩余免费刷新；不花点券'),
 ('RUN_FUN_COLLECT_REWARD','领取采集奖励','reward','宠物采集','普通领取原页面选中位置；未完成或已领取时跳过'),
 ('RUN_FUN_COLLECT_START','派遣宠物采集','start','宠物采集','沿用位置、材料和时长；宠物优先页面已选，未查询时运行时自动选第一只空闲宠物；无空闲则跳过'),
 ('RUN_FUN_MONSTER_CARD','妖王帖免费抽取','card','妖王帖','沿用原页面次数；仅剩余免费次数'),
 ('RUN_FUN_CARD_CAVE','藏宝洞免费挑战','cave','藏宝洞','沿用模式、次数和间隔；指定码在运行时自动核验，未填或格式无效时改按推荐最高守备强度；仅免费次数'),
 ('RUN_FUN_FAIRY_FEED','幻兽喂养','feed','幻兽喂养','沿用喂养角色、方式和次数；优先已选或缓存的幻兽，否则默认该角色身上的，喂不了再选等级最低的'),
)
BY_KEY={r[0]:r for r in DEFINITIONS}
def catalog(base):return list(base)+[(label,key,False,False,note) for key,label,kind,page,note in DEFINITIONS]
def pages(base):return {**base,'趣味活动':tuple(BY_KEY)}
def build_plan(app,keys,account,slot):
    jobs=[];errors={}
    for key,label,kind,page,note in DEFINITIONS:
        if key not in keys:continue
        try:jobs.extend(app.fun_batch_page.build([label],account,slot,auto=True)['jobs'])
        except (ValueError,KeyError,TypeError) as exc:errors[key]=str(exc)
    if not jobs and not errors:return None
    return {'uid':str(account['uid']),'slot':slot,'jobs':jobs,'errors':errors}


def prepare_plan(keys,plan,uid,slot):
    jobs=[];errors={}
    for key,label,kind,page,note in DEFINITIONS:
        if key not in keys:continue
        try:
            if not isinstance(plan,dict):raise ValueError('原页面未生成当前存档的设置')
            if key in plan.get('errors',{}):raise ValueError(plan['errors'][key])
            matching=[j for j in plan.get('jobs',[]) if j.get('kind')==kind and j.get('label')==label]
            if len(matching)!=1:raise ValueError('本项设置缺失或重复')
            single={'uid':plan.get('uid'),'slot':plan.get('slot'),'jobs':matching}
            jobs.extend(validate_plan([key],single,uid,slot))
        except (ValueError,TypeError,KeyError) as exc:errors[key]=str(exc)
    return jobs,errors

def validate_plan(keys,plan,uid,slot):
    selected=[row for row in DEFINITIONS if row[0] in keys]
    if not selected:
        if plan and plan.get('jobs'):raise ValueError('存在未选择的趣味活动计划')
        return []
    if not isinstance(plan,dict) or str(plan.get('uid'))!=str(uid) or plan.get('slot')!=slot:raise ValueError('趣味活动计划的账号或存档不符')
    jobs=plan.get('jobs')
    if not isinstance(jobs,list) or len(jobs)!=len(selected):raise ValueError('趣味活动计划数量不符')
    fields={'black':set(),'reward':{'pos'},'start':{'pos','collect_id','entity','gear'},'card':{'count'},'cave':{'matches','wait','mode','code','fingerprint'}}
    for job,(_,label,kind,_,_) in zip(jobs,selected):
        if job.get('kind')!=kind or job.get('label')!=label or not isinstance(job.get('args'),dict):raise ValueError('包含未选择或不支持的趣味活动')
        a=job['args']
        if kind=='feed':
            if set(a)-{'times','use_item','role','entity_id','ordinal','auto'} or not {'times','use_item'}<=set(a):raise ValueError('幻兽喂养参数无效')
            if 'auto' in a:
                if a['auto'] is not True or 'entity_id' in a or 'ordinal' in a:raise ValueError('幻兽喂养参数无效')
            elif ('entity_id' in a)==('ordinal' in a):raise ValueError('幻兽喂养须指定幻兽或序号')
        elif kind!='start' and set(a)!=fields[kind]:raise ValueError('包含未选择或不支持的趣味活动')
        if kind in ('reward','start') and (type(a['pos'])!=int or not 0<=a['pos']<=2):raise ValueError('采集位置无效')
        if kind=='start':
            if not {'pos','collect_id','gear'}<=set(a) or set(a)-{'pos','collect_id','gear','entity','auto'}:raise ValueError('采集派遣参数无效')
            if 'auto' in a:
                if a['auto'] is not True or 'entity' in a:raise ValueError('采集派遣参数无效')
            elif not isinstance(a.get('entity'),str) or not a.get('entity'):raise ValueError('采集派遣参数无效')
            if type(a['collect_id'])!=int or a['collect_id']<=0 or type(a['gear'])!=int or not 0<=a['gear']<=2:raise ValueError('采集派遣参数无效')
        if kind=='card' and (type(a['count'])!=int or a['count']<0):raise ValueError('免费妖王帖次数无效')
        if kind=='cave':
            if type(a['matches'])!=int or not 1<=a['matches']<=5 or not math.isfinite(float(a['wait'])) or not 0<=float(a['wait'])<=3600 or a['mode'] not in ('recommend','specified'):raise ValueError('藏宝洞参数无效')
            if a['mode']=='specified' and (not isinstance(a['code'],str) or not a['code'] or not isinstance(a['fingerprint'],str)):raise ValueError('指定藏宝洞挑战码无效')
        if kind=='feed':
            if type(a['use_item'])!=bool or (a['times'] is not None and (type(a['times'])!=int or a['times']<=0)) or ('role' in a and a['role'] not in (0,1)):raise ValueError('幻兽喂养参数无效')
            if 'entity_id' in a and (not isinstance(a['entity_id'],str) or not a['entity_id']):raise ValueError('幻兽喂养参数无效')
            if 'ordinal' in a and (type(a['ordinal'])!=int or a['ordinal']<1):raise ValueError('幻兽喂养参数无效')
    return jobs
