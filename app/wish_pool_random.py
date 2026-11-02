"""随机选择至多三个当前可参与池，补到各10次；默认不自动启用。"""
import json,math,random,time
from pathlib import Path
from datetime import datetime
import wish_pool_api as api
import wish_pool_data as data
from arena_reward import checked
ROOT=Path(__file__).resolve().parent

def target(cell,level):
    divisor=int(cell['item']['wishCount'])
    if divisor<=0 or level<1:raise ValueError('许愿等级配置缺失')
    return max(1,min(10,math.ceil(level/divisor)-2))

def choose(cells,positions,maximum,rng=random):
    # 已参与的池优先保留，重复运行不重新选第四个池。
    existing=[c for c in cells if int(positions.get(c['pos'],0))>0]
    free=max(0,maximum-len(positions));new=[c for c in cells if c not in existing]
    return existing[:3]+rng.sample(new,min(len(new),free,max(0,3-len(existing))))

def read(flow,slot):
    info=checked(flow.request('connector.entryHandler.entry',{'index':slot,'userAgent':flow.user_agent})).get('info')
    if not isinstance(info,dict):raise RuntimeError('存档状态缺失')
    user=checked(flow.request('connector.roleHandler.getUserInfo',{})).get('user') or {}
    if any(user.get(k) is None for k in ('ticket','yuanbao')) or info.get('spirit') is None:raise RuntimeError('货币余额缺失')
    stages=data.load_stages();home=api.get_pool_info(flow);key=home.get('curKey')
    if not key or not isinstance(home.get('cur'),dict):raise RuntimeError('当前许愿池信息缺失')
    camp,_,_=api.get_my_camp(info);cells=api.select_visible_cells(home['cur'],camp,api.build_item_index(stages))
    positions=api.my_wish_state((info.get('everyWeekSetting') or {}).get('wish') or {},key)['pos']
    if any(n<0 for n in positions.values()):raise RuntimeError('许愿计数异常')
    level=int((info.get('p1') or {}).get('level') or 0)
    for cell in cells:
        item=cell['item']
        if item.get('consumeType')!='coin' or item.get('consumeSub')!='spirit':raise RuntimeError('许愿费用不是灵魂或配置缺失')
        cell['target']=target(cell,level)
    return {'key':key,'positions':positions,'cells':cells,'maximum':int(stages['wishMax']),'spirit':int(info['spirit']),'ticket':user['ticket'],'yuanbao':user['yuanbao']}

def manual_cells(current,plan):
    if not isinstance(plan,dict) or plan.get('key')!=current['key']:raise ValueError('当前期数已变化，请重新查看许愿池')
    rows=plan.get('cells')
    if not isinstance(rows,list) or not rows:raise ValueError('请设置各池的目标次数')
    chosen=[];seen=set()
    for row in rows:
        pos=int(row['pos']);goal=int(row['target'])
        if pos in seen or goal not in (1,10):raise ValueError('池子或目标次数无效')
        seen.add(pos)
        cell=next((c for c in current['cells'] if c['pos']==pos and c['wishId']==int(row['wishId'])),None)
        if cell is None:raise ValueError('池子物品或阵营已变化，请重新查询')
        chosen.append(dict(cell,target=min(goal,cell['target'])))
    if len(set(current['positions'])|seen)>current['maximum']:raise ValueError('本期最多参与%s个不同池子'%current['maximum'])
    return chosen

def do_wish(flow,info,*,slot=None,report_dir=None,manual=None):
    if slot is None:
        import daily_auto as da
        slot=da.RECORD_INDEX
    folder=Path(report_dir) if report_dir else ROOT/'wish_random_reports';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json');report={'slot':slot,'phase':'reading','wishes':[]}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        current=read(flow,slot);key=current['key'];selected=manual_cells(current,manual) if manual is not None else choose(current['cells'],current['positions'],current['maximum']);report.update(before=current,selected=[{'pos':c['pos'],'pool':c['pool'],'wishId':c['wishId'],'target':c['target']} for c in selected]);save()
        for chosen in selected:
            while True:
                current=read(flow,slot)
                if current['key']!=key:raise RuntimeError('许愿期数已变化，停止')
                cell=next((c for c in current['cells'] if c['pos']==chosen['pos'] and c['wishId']==chosen['wishId']),None)
                if cell is None:raise RuntimeError('所选池物品已变化，停止')
                pos=cell['pos'];used=current['positions'].get(pos,0);goal=min(chosen['target'],cell['target'])
                if used>=goal:break
                if pos not in current['positions'] and len(current['positions'])>=current['maximum']:raise RuntimeError('可参与格子数已用尽')
                costs=cell['item']['consumeCosts']
                if used<0 or used>=len(costs):raise RuntimeError('当前次数费用缺失')
                cost=int(costs[used])
                if cost<=0:raise RuntimeError('许愿灵魂费用异常')
                if current['spirit']<cost:
                    report.update(phase='insufficient_spirit',after=current);save();return True,'灵魂不足，已停止；本次成功许愿%s次'%len(report['wishes']),report
                event={'pos':pos,'wishId':cell['wishId'],'used':used,'expected_cost':cost,'phase':'pending'};report['wishes'].append(event);save()
                reply=flow.request(api.ROUTE_WISH,{'wishId':cell['wishId']});event.update(reply=reply,phase='returned');save();checked(reply)
                after=read(flow,slot);event['after']=after;save()
                expected=dict(current['positions']);expected[pos]=used+1
                if after['key']!=key or after['positions']!=expected or current['spirit']-after['spirit']!=cost or any(current[k]!=after[k] for k in ('ticket','yuanbao')):raise RuntimeError('许愿次数或消耗核对不符，未重发')
                for consume in reply.get('consume') or []:
                    if consume.get('type')!='coin' or consume.get('subType')!='spirit':raise RuntimeError('出现非灵魂消耗')
                event['phase']='verified';save()
                print('[随机许愿] %s：%s/%s，灵魂-%s'%(cell['pool'],used+1,goal,cost),flush=True);time.sleep(2)
        report.update(phase='complete',after=read(flow,slot));save()
        return True,'许愿完成：%s个池，本次%s次；已有次数计入目标，受角色等级上限限制。记录：%s'%(len(selected),len(report['wishes']),path),report
    except Exception as exc:
        report.update(phase='stopped',error_type=type(exc).__name__);save()
        return False,'随机许愿停止：%s；结果不明不重发。记录：%s'%(exc,path),report

if __name__=='__main__':
    from wish_pool_run import connect,entry
    flow=connect()
    try:
        ok,message,_=do_wish(flow,entry(flow));print(('[OK] ' if ok else '[--] ')+message,flush=True)
    finally:flow.disconnect()
