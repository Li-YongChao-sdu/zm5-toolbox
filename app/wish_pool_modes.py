"""许愿池手动／随机模式入口，默认手动。"""
import argparse,json
from pathlib import Path
import wish_pool_random as backend
ROOT=Path(__file__).resolve().parent

def run_selected(flow,info):
    import daily_auto as da
    mode=getattr(da,'WISH_POOL_MODE','manual');plan=getattr(da,'WISH_POOL_PLAN',None)
    if mode not in ('manual','random'):raise ValueError('许愿模式无效')
    if mode=='manual':
        if not plan or str(plan.get('uid'))!=str(da.UID) or plan.get('slot')!=da.RECORD_INDEX:raise ValueError('请先查看当前账号存档的许愿池并设置次数')
    return backend.do_wish(flow,info,manual=plan if mode=='manual' else None)

def main():
    p=argparse.ArgumentParser();p.add_argument('--query',action='store_true');p.add_argument('--mode',choices=['manual','random'],default='manual');p.add_argument('--plan');p.add_argument('--uid',required=True);p.add_argument('--slot',type=int,required=True);a=p.parse_args()
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
    if str(account['uid'])!=a.uid or int(account['record_index'])!=a.slot:raise ValueError('账号或存档已变化，未执行')
    from teacher_trial import connect
    flow=None
    try:
        flow,info=connect(account,a.slot)
        if a.query:
            state=backend.read(flow,a.slot)
        else:
            plan=json.loads(a.plan) if a.mode=='manual' and a.plan else None
            if a.mode=='manual' and (not plan or str(plan.get('uid'))!=a.uid or plan.get('slot')!=a.slot):raise ValueError('手动计划与账号存档不符')
            ok,message,_=backend.do_wish(flow,info,slot=a.slot,manual=plan);print(('[OK] ' if ok else '[--] ')+message,flush=True)
            state=backend.read(flow,a.slot)
        state.update(uid=a.uid,slot=a.slot)
        print('__WISH_POOL_STATE__'+json.dumps(state,ensure_ascii=False),flush=True)
    finally:
        if flow:flow.disconnect()
if __name__=='__main__':main()
