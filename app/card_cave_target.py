"""指定挑战码的正式藏宝洞挑战，只使用每日免费次数。"""
import argparse,hashlib,json,re,time
from datetime import datetime
from pathlib import Path
from bag_warehouse import quantity
ROOT=Path(__file__).resolve().parent

def checked(r):
    if not isinstance(r,dict) or r.get('code')!=200 or r.get('error'):raise RuntimeError(str(r.get('error') or r.get('code')) if isinstance(r,dict) else '无效回包')
    return r

def target(flow,code):
    if not re.fullmatch(r'\d+_r\d+_\d+',code):raise ValueError('挑战码格式应为 UID_r编号_展位编号')
    d=checked(flow.request('scene.cardHandler.getPublishLandform',{'id':code})).get('data')
    if not isinstance(d,dict) or d.get('entityId')!=code:raise ValueError('未找到对应的已发布藏宝洞')
    u=d.get('userdata') or {}
    fingerprint=hashlib.sha256(json.dumps(u,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'code':code,'owner':u.get('username','未知'),'name':u.get('name',''),'stars':u.get('defensiveLevel'),'strength':u.get('defensive'),'fingerprint':fingerprint}

def state(flow,slot):
    from teacher_trial import enter
    info=enter(flow,slot);u=checked(flow.request('connector.roleHandler.getUserInfo',{}))['user']
    if any(u.get(k) is None for k in ('ticket','yuanbao')) or not isinstance(info.get('everyDaySetting'),dict):raise ValueError('无法核对余额或免费次数')
    return info,{'used':int(info['everyDaySetting'].get('landformChallengeCnt') or 0),'ticket':u['ticket'],'yuanbao':u['yuanbao'],'fairyMoney':info.get('fairyMoney')}

def item_count(info,pid,is_card=False):
    if not is_card:return quantity(info,'bag',pid)
    return sum(int(v.get('count') or 0) for k,v in ((info.get('bag') or {}).get('cardItem') or {}).items() if str(v.get('id',k))==str(pid))

def verify(before_info,after_info,before,after,reply):
    checked(reply)
    if reply.get('consume'):raise RuntimeError('结算出现非预期消耗')
    if after['used']!=before['used']+1:raise RuntimeError('免费次数核对异常')
    if any(before[k]!=after[k] for k in ('ticket','yuanbao')):raise RuntimeError('点券或元宝变化')
    for g in reply.get('give') or []:
        if g.get('type')=='item':
            card=int(g.get('isConsume',0))==2;pid=int(g['subType'])
            if item_count(after_info,pid,card)-item_count(before_info,pid,card)!=int(g['count']):raise RuntimeError('奖励道具到账核对异常：%s'%pid)
        elif g.get('type')=='coin' and g.get('subType')=='fairyMoney':
            if before['fairyMoney'] is None or after['fairyMoney']-before['fairyMoney']!=int(g['count']):raise RuntimeError('仙魄到账核对异常')

def recommend(flow):
    rows=checked(flow.request('scene.cardHandler.getRecommend',{})).get('recommend') or []
    valid=[]
    for d in rows:
        if not isinstance(d,dict) or not d.get('entityId'):continue
        try:score=int((d.get('userdata') or {})['defensive'])
        except (KeyError,TypeError,ValueError):continue
        if score>=0:valid.append((score,d))
    if not valid:raise ValueError('推荐列表没有有效守备强度的目标')
    d=max(valid,key=lambda x:x[0])[1];u=d['userdata']
    return {'code':d['entityId'],'owner':u.get('username','未知'),'name':u.get('name',''),'stars':u.get('defensiveLevel'),'strength':u['defensive'],'fingerprint':''}

def select(flow,mode,code=''):
    if mode=='recommend':return recommend(flow)
    if mode=='specified':return target(flow,code)
    raise ValueError('挑战方式无效')

def run_matches(flow,slot,matches=1,wait=2,mode='recommend',code='',fingerprint='',report_dir=None):
    if not 1<=int(matches)<=5 or not 0<=float(wait)<=3600:raise ValueError('次数须为1～5，等待须为0～3600秒')
    if mode not in ('recommend','specified'):raise ValueError('挑战方式无效')
    if mode=='specified' and not fingerprint:fingerprint=target(flow,code)['fingerprint']
    folder=Path(report_dir) if report_dir else ROOT/'card_cave_target_reports';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json');report={'slot':slot,'mode':mode,'rounds':[]}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for i in range(int(matches)):
        info,before=state(flow,slot)
        bag_before=item_count(info,101029001)
        if before['used']>=5:print('[藏宝洞] 免费次数用尽，停止。',flush=True);break
        if before['used']<0:raise RuntimeError('每日次数异常')
        t=select(flow,mode,code)
        if mode=='specified' and t['fingerprint']!=fingerprint:raise RuntimeError('对方布局已变化，请重新查询并确认')
        row={'round':i+1,'target':t,'before':before,'item101029001_before':bag_before,'phase':'begin_pending'};report['rounds'].append(row);save()
        print('[藏宝洞] %s｜%s星｜强度%s｜%s'%(t['owner'],t['stars'],t['strength'],t['code']),flush=True)
        try:
            start=flow.request('scene.cardHandler.beginBattle',{'entityId':t['code']});row.update(begin=start,phase='begin_returned');save();checked(start)
            if start.get('consume'):raise RuntimeError('开局出现非预期消耗')
            time.sleep(float(wait));row['phase']='end_pending';save()
            end=flow.request('scene.cardHandler.endBattle',{'entityId':t['code'],'win':1});row.update(end=end,phase='end_returned');save()
            after_info,after=state(flow,slot);row['after']=after;verify(info,after_info,before,after,end);row['phase']='verified';save()
        except Exception:
            print('[藏宝洞] 本局未确认完成，已停止且不会自动重发；记录：'+str(path),flush=True);raise
        bag_after=item_count(after_info,101029001);row['item101029001_after']=bag_after;save()
        print('[藏宝洞] 第%s局核对通过；乾金玉%s→%s（%+d）；奖励%s；免费次数%s/5；点券%s、元宝%s未变化'%(i+1,bag_before,bag_after,bag_after-bag_before,json.dumps(end.get('give') or [],ensure_ascii=False),after['used'],after['ticket'],after['yuanbao']),flush=True)
        if i+1<int(matches):time.sleep(float(wait))
    save();print('[藏宝洞] 记录：'+str(path),flush=True);return report

def defense_rank(flow):
    reply=checked(flow.request('scene.cardHandler.getRank',{'type':'rank_defensive','page':0}))
    rows=[];seen=set()
    for i,raw in enumerate(reply.get('rows') or []):
        try:
            d=json.loads(raw) if isinstance(raw,str) else raw
            code=d['entityId'];score=int(d['score'])
            if not re.fullmatch(r'\d+_r\d+_\d+',code) or score<0 or code in seen:continue
            seen.add(code);rows.append({'rank':int(d.get('rank',i))+1,'code':code,'owner':d.get('name','未知'),'strength':score})
        except (ValueError,TypeError,KeyError):continue
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--rank',action='store_true');p.add_argument('--mode',choices=['recommend','specified'],default='specified');p.add_argument('--code',default='');p.add_argument('--matches',type=int,default=0);p.add_argument('--wait',type=float,default=2);p.add_argument('--account');p.add_argument('--slot',type=int);p.add_argument('--fingerprint');a=p.parse_args()
    if not 0<=a.matches<=5 or not 0<=a.wait<=3600:raise ValueError('次数须为1～5，等待须为0～3600秒')
    from teacher_trial import connect
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account['record_index']);f=None
    if a.matches and (a.account!=str(account.get('username')) or a.slot!=slot):raise ValueError('账号或槽位已变化，请重新查询')
    try:
        f,_=connect(account,slot)
        if a.rank:
            if a.matches:raise ValueError('排行榜查询不能同时执行挑战')
            data={'account':str(account.get('username','')),'slot':slot,'rows':defense_rank(f)}
            print('__CARD_CAVE_RANK_STATE__'+json.dumps(data,ensure_ascii=False),flush=True)
            return
        if a.matches:run_matches(f,slot,a.matches,a.wait,a.mode,a.code,a.fingerprint)
        _,latest=state(f,slot)
        t=select(f,a.mode,a.code) if latest['used']<5 or not a.matches else {'code':a.code,'owner':'','name':'','stars':'','strength':'','fingerprint':''}
        t.update(mode=a.mode,account=str(account.get('username','')),slot=slot,remaining=max(0,5-latest['used']))
        print('__CARD_CAVE_TARGET_STATE__'+json.dumps(t,ensure_ascii=False),flush=True)
    finally:
        if f:f.disconnect()

if __name__=='__main__':main()
