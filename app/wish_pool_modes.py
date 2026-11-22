"""许愿池手动／排序／随机模式入口，默认手动。"""
import argparse,json
from pathlib import Path
import wish_pool_random as backend
ROOT=Path(__file__).resolve().parent

def ranked_plan(flow,slot=None,uid=None):
    """按道具优先级表现场生成排序方案；没有需要补许的池子时返回 None。"""
    import wish_pool_order as order
    if slot is None or uid is None:
        import daily_auto as da
        slot=da.RECORD_INDEX if slot is None else slot
        uid=da.UID if uid is None else uid
    state=backend.read(flow,slot)
    picks=order.select(state['cells'],state['positions'],state['maximum'])
    if not picks:return None
    return {'uid':str(uid),'slot':int(slot),'key':state['key'],'cells':[{'pos':p['cell']['pos'],'wishId':p['cell']['wishId'],'target':p['target']} for p in picks]}

def run_selected(flow,info):
    import daily_auto as da
    mode=getattr(da,'WISH_POOL_MODE','manual');plan=getattr(da,'WISH_POOL_PLAN',None)
    if mode not in ('manual','random','ranked'):raise ValueError('许愿模式无效')
    if mode=='manual':
        if not plan or str(plan.get('uid'))!=str(da.UID) or plan.get('slot')!=da.RECORD_INDEX:raise ValueError('请先查看当前账号存档的许愿池并设置次数')
    elif mode=='ranked':
        plan=ranked_plan(flow,da.RECORD_INDEX,da.UID)
        if plan is None:return True,'本期没有需要补许的池子（已达目标或名额已满）',None
    labels={'manual':'手动许愿','ranked':'排序许愿','random':'随机许愿'}
    return backend.do_wish(flow,info,slot=da.RECORD_INDEX,manual=plan if mode!='random' else None,label=labels[mode])

def main():
    p=argparse.ArgumentParser();p.add_argument('--query',action='store_true');p.add_argument('--mode',choices=['manual','random','ranked'],default='manual');p.add_argument('--plan');p.add_argument('--uid',required=True);p.add_argument('--slot',type=int,required=True);a=p.parse_args()
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
    if str(account['uid'])!=a.uid or int(account['record_index'])!=a.slot:raise ValueError('账号或存档已变化，未执行')
    from teacher_trial import connect
    flow=None
    try:
        flow,info=connect(account,a.slot)
        if a.query:
            state=backend.read(flow,a.slot)
        else:
            if a.mode=='manual':
                plan=json.loads(a.plan) if a.plan else None
                if not plan or str(plan.get('uid'))!=a.uid or plan.get('slot')!=a.slot:raise ValueError('手动计划与账号存档不符')
            elif a.mode=='ranked':
                plan=ranked_plan(flow,a.slot,a.uid)
                if plan is None:raise ValueError('本期没有需要补许的池子（已达目标或名额已满）')
            else:
                plan=None
            labels={'manual':'手动许愿','ranked':'排序许愿','random':'随机许愿'}
            ok,message,_=backend.do_wish(flow,info,slot=a.slot,manual=plan,label=labels[a.mode]);print(('[OK] ' if ok else '[--] ')+message,flush=True)
            state=backend.read(flow,a.slot)
        state.update(uid=a.uid,slot=a.slot)
        print('__WISH_POOL_STATE__'+json.dumps(state,ensure_ascii=False),flush=True)
    finally:
        if flow:flow.disconnect()
if __name__=='__main__':main()
