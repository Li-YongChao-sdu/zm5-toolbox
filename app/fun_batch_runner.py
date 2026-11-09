"""趣味活动批量执行；复用现有功能，异常停止，不重试。"""
import argparse,json,os
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parent
KINDS={'black','reward','start','card','buy','cave','feed','dispatch'}
def execute(flow,account,slot,jobs):
    from teacher_trial import enter,checked
    import pet_utilities as pet
    folder=ROOT/'fun_batch_reports';folder.mkdir(exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    report={'slot':slot,'jobs':[],'status':'running'}
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def read():return enter(flow,slot),checked(flow.request('connector.roleHandler.getUserInfo',{}),'余额')['user']
    try:
        for job in jobs:
            kind=job['kind'];args=dict(job.get('args',{}))
            if kind not in KINDS:raise ValueError('未知批量项目')
            row={'kind':kind,'args':args,'phase':'pending'};report['jobs'].append(row);save()
            print('[趣味活动] 开始：'+job['label'],flush=True)
            info,user=read()
            if kind=='black':
                import black_market_daily
                result=black_market_daily.run(flow,slot,account=account)
                if result.get('status')!='complete':raise RuntimeError('黑市未完整执行，停止后续项目')
            elif kind=='cave':
                from card_cave_target import run_matches
                result=run_matches(flow,slot,**args)
            elif kind=='dispatch':
                import fairy_daily
                result=fairy_daily.run(flow,slot,apply=True,**args)
                if result.get('status')!='complete':raise RuntimeError('幻兽派遣未完成，停止')
            elif kind=='feed':
                import fairy_feed_run as feed
                import fairy_feed_data as data
                role=args.get('role',0)
                call={k:v for k,v in args.items() if k!='auto'}
                if args.get('auto'):
                    fairy,err=data.auto_fairy(info,role)
                    if not fairy:raise RuntimeError(err)
                    call['entity_id']=fairy['entityId']
                    print('[幻兽喂养] 自动选择 %s（%s，%s级）'%(fairy['name'],fairy['source'],fairy['level']),flush=True)
                before=data.feed_quota(info,role=role)
                ok,message,result=feed.do_feed(flow,info,**call);print('[幻兽喂养] '+message,flush=True)
                if result and result.get('stop') in ('rejected','safety','noConfig','badConfig'):raise RuntimeError(message)
                if not ok and (not result or result.get('stop') not in ('daily','level','spirit')):raise RuntimeError(message)
                latest,latest_user=read()
                if not args.get('use_item') and result:
                    if data.feed_quota(latest,role=role)['used']-before['used']!=result['feeds']:raise RuntimeError('喂养次数核对失败')
                    if info['spirit']-latest['spirit']!=result['spiritCost']:raise RuntimeError('喂养灵魂核对失败')
                feed.emit_state(latest)
            else:
                if kind=='card':
                    count=min(args['count'],pet.free_quota(info)['remaining'])
                    result=[]
                    if count:result,info,user=pet.draw_free_cards(flow,info,user,count,lambda:enter(flow,slot))
                    if any(not x.get('free_verified') for x in result):raise RuntimeError('妖王帖核对失败')
                else:
                    if kind=='start':
                        state=pet.status(info,user);current_slot=state['slots'][args['pos']]
                        if current_slot.get('collectId') and not current_slot.get('reward'):
                            row['phase']='skipped';save();print('[趣味活动] 该位置尚在采集或未领奖，跳过派遣，不覆盖',flush=True);continue
                        if args.get('auto'):
                            animals=[x for x in state['pets'] if not x['busy']]
                            if not animals:
                                row.update(phase='skipped',reason='没有空闲宠物');save();print('[宠物采集] 没有空闲宠物，跳过派遣，不占用位置',flush=True);continue
                            chosen=animals[0];args=dict(args);args['entity']=chosen['entityId'];args['gear']=min(int(args.get('gear',0)),int(state['collectGear']))
                            print('[宠物采集] 自动选择 %s（%s级，%s小时）'%(chosen['name'],chosen['level'],3*(int(args['gear'])+1)),flush=True)
                    if kind=='reward' and not pet.status(info,user)['slots'][args['pos']]['finished']:
                        row['phase']='skipped';save();print('[趣味活动] 采集未完成或已领取，跳过',flush=True);continue
                    if kind=='buy':
                        cfg=pet.scrolls().get(str(args.get('shop')))
                        if not cfg:raise ValueError('商品不在仙魄商店配置中')
                        count=args.get('count')
                        cap=pet.limit(cfg)
                        if type(count) is not int or not 1<=count<=cap:raise ValueError('购买数量无效')
                        remaining=max(0,cap-pet.bought(info,args['shop']))
                        row['requested_count']=count
                        if remaining==0:
                            row.update(phase='skipped',reason='本周已买满');save();print('[仙魄商店] '+job['label']+'：本周已买满，跳过并继续其他商品',flush=True);continue
                        if count>remaining:
                            args['count']=remaining
                            print('[仙魄商店] '+job['label']+'：剩余限购%s，本次由%s调整为%s'%(remaining,count,remaining),flush=True)
                        row['args']=dict(args);save()
                    call={k:v for k,v in args.items() if k!='auto'}
                    result,info,user=pet.perform(flow,info,user,kind,lambda:enter(flow,slot),password=os.environ.get('ZM5_PET_UTILITY_PASSWORD','') if kind=='buy' else '',**call)
                    row['result']=result;save()
                    if not result.get('verified') or not result.get('ticket_unchanged'):
                        reason=(result.get('reply') or {}).get('error') or '扣费、到账或次数核对未通过'
                        raise RuntimeError('操作未完成：'+str(reason)+'；停止后续项目，不自动重发')
                payload=pet.status(info,user);payload.update(account=str(account.get('username','')),slot=slot)
                print('__PET_UTILITY_STATE__'+json.dumps(payload,ensure_ascii=False),flush=True)
            row.update(phase='complete',result=result);save();print('[趣味活动] 完成：'+job['label'],flush=True)
        report['status']='complete';save()
    except Exception:
        report['status']='stopped';save();raise
    finally:print('[趣味活动] 报告：'+str(path),flush=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',required=True);a=p.parse_args();plan=json.loads(a.plan)
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account['record_index'])
    if str(account['uid'])!=plan['uid'] or slot!=plan['slot']:raise ValueError('账号或存档已变化，未执行')
    if not plan['jobs'] or any(j['kind'] not in KINDS for j in plan['jobs']):raise ValueError('批量计划无效')
    from teacher_trial import connect
    from my_daily_policy import FreeDailyFlow
    shops=json.loads((ROOT/'cg_config_out_cg1_20261019_1/Shop.json').read_text(encoding='utf-8-sig'))
    flow=None
    try:
        raw,_=connect(account,slot);flow=FreeDailyFlow(raw,shops)
        execute(flow,account,slot,plan['jobs'])
    finally:
        if flow:flow.disconnect()
if __name__=='__main__':main()
