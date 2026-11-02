"""复用daily_auto，仅运行我的日常明确选中的项目。"""
import argparse,json
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--tasks',required=True);p.add_argument('--fun-plan');a=p.parse_args()
    import daily_auto as da
    from gui import TASKS
    from activity_availability import disabled_reason
    from my_daily_policy import configure,FreeDailyFlow
    keys=json.loads(a.tasks)
    if not isinstance(keys,list) or not all(isinstance(k,str) for k in keys):raise ValueError('任务列表无效')
    from my_daily_catalog import catalog,validate_plan
    jobs=validate_plan(set(keys),json.loads(a.fun_plan) if a.fun_plan else None,da.UID,da.RECORD_INDEX)
    configure(da,keys,catalog(TASKS))
    da.MY_DAILY_FUN_JOBS=jobs;da.RUN_MY_DAILY_FUN=bool(jobs)
    for key in keys:
        if disabled_reason(key):setattr(da,key,False);print('[我的日常] 跳过：'+disabled_reason(key),flush=True)
    config=Path(__file__).resolve().parent/'cg_config_out_cg1_20261019_1/Shop.json'
    shops=json.loads(config.read_text(encoding='utf-8-sig'));original_login=da.login;flows=[]
    def login(*args,**kwargs):
        flow,info=original_login(*args,**kwargs);guard=FreeDailyFlow(flow,shops);flows.append(guard);return guard,info
    da.login=login
    print('[我的日常] 本次只执行：'+', '.join(keys)+'；禁用点券续战和付费入口。灵魂、材料等沿用原任务设置。',flush=True)
    try:
        da.main()
        if any(flow.halted for flow in flows):raise RuntimeError('本批存在付费拦截或未确认请求，已停止')
    finally:
        for flow in flows:flow.disconnect()

if __name__=='__main__':main()
