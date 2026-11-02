"""联盟补贡：补本周缺失日期；补贡券不足时跑一次星斗幻境免费领奖，再到星斗商店用星辰石换券。
铁律：只买 Shop 23004（星辰石→补贡券），绝不调用点券补贡/点券购买接口。"""
import argparse,json,time
from pathlib import Path
from bag_warehouse import quantity

ROOT=Path(__file__).resolve().parent
COUPON='101019003'
STONE='101022016'
SHOP_ID=23004
MAZE_REWARD_MAX=3


def _config_dir():
    for name in ('cg_config_out_cg1_20261026_1','cg_config_out_cg1_20261012_1'):
        path=ROOT/name
        if path.exists():return path
    raise RuntimeError('未找到配置目录')


def _table(name):
    return json.loads((_config_dir()/name).read_text(encoding='utf-8-sig'))


def shop_rule():
    shop=_table('Shop.json').get(str(SHOP_ID)) or {}
    if str(shop.get('consume_subType'))!=STONE or str(shop.get('sell_subType'))!=COUPON:
        raise RuntimeError('星斗商店%s不是星辰石换补贡券，拒绝购买'%SHOP_ID)
    return shop


def _rule(index):
    return (_table('UnionReDevote.json').get(str(index)) or {})


def week_day(info):
    """服务器日期：周一=1..周六=6，周日=0（与客户端 Date.day 一致）。"""
    import datetime
    ts=int(info.get('serverTime') or 0)
    if ts<=0:raise RuntimeError('未读取到服务器时间')
    return datetime.datetime.fromtimestamp(ts/1000).isoweekday()%7


def week_state(info):
    week=info.get('everyWeekSetting') or {}
    devote=week.get('devote') or {}
    days=sorted(int(k) for k in devote if str(k).isdigit())
    return {'count':int(devote.get('count') or 0),'days':days,
            'shop_bought':int(((week.get('shopBuyCount') or {}).get(str(SHOP_ID)) or {}).get('buyCount') or 0),
            'maze_cnt':int(week.get('mazeCnt') or 0),
            'maze_claimed':int(week.get('rewardMazeCnt') or 0)}


def plan(info):
    """按客户端规则生成本周可补日期及每次消耗；reDevoteCount 递增决定灵魂/补贡券档位。"""
    st=week_state(info);today=week_day(info)
    allowed=set(range(1,7)) if today==0 else set(range(1,today))
    pending=sorted(allowed-set(st['days']))
    rows=[];count=st['count']
    for day in pending:
        rule=_rule(min(count+1,6))
        item=str(rule.get('item') or '0,0').split(',')
        item_id=int(item[0] or 0);item_n=int(item[1] or 0) if len(item)>1 else 0
        spirit=int(rule.get('spirit') or 0)
        if spirit>0:kind,tag=0,'灵魂%d'%spirit
        elif item_id==int(COUPON):kind,tag=2,'补贡券%d'%item_n
        else:raise RuntimeError('UnionReDevote 档位%d配置异常：%s'%(count+1,rule))
        rows.append({'day':day,'type':kind,'spirit':spirit,'need':item_n if kind==2 else 0,'count':count+1})
        count+=1
    return rows


def maze_free_left(info):
    st=week_state(info)
    return max(0,min(MAZE_REWARD_MAX,st['maze_cnt'])-st['maze_claimed'])


def buy_coupons(flow,info,account,need,log):
    """用星辰石在星斗商店换补贡券；周限3张，缺星辰石时先跑一次星斗幻境免费领奖。"""
    from feature_account import entry
    have=quantity(info,'bag',COUPON)
    if have>=need:return info
    rule=shop_rule();limit=int(rule.get('weekPurchaseMaxNum') or 0) or 0
    st=week_state(info);stones=quantity(info,'bag',STONE)
    left_shop=max(0,limit-st['shop_bought']) if limit>0 else need
    want=min(need-have,left_shop,stones)
    log('补贡券%d张，现有%d张；星辰石%d颗，本周商店已换%d/%d；本次兑换%d张'
        %(need,have,stones,st['shop_bought'],limit,want))
    while want>0:
        r=flow.request('scene.shopHandler.buy',{'shopId':SHOP_ID,'count':1})
        if not isinstance(r,dict) or r.get('error'):
            raise RuntimeError('星斗商店兑换失败：%s'%(r.get('error') if isinstance(r,dict) else r))
        given=sum(int(x.get('count') or 0) for x in (r.get('give') or []) if str(x.get('subType'))==COUPON)
        used=sum(int(x.get('count') or 0) for x in (r.get('consume') or []) if str(x.get('subType'))==STONE)
        if given!=1 or used!=1:
            raise RuntimeError('星斗商店兑换回包异常：give=%s consume=%s'%(r.get('give'),r.get('consume')))
        want-=1;time.sleep(.4)
    info=entry(flow,account)
    have=quantity(info,'bag',COUPON)
    if have<need:
        st=week_state(info)
        if limit>0 and st['shop_bought']>=limit:
            raise RuntimeError('补贡券仍不足(%d/%d)，本周星斗商店兑换次数已用完(%d/%d)；停止，不使用点券'
                               %(have,need,st['shop_bought'],limit))
        free=maze_free_left(info)
        if free<=0:
            raise RuntimeError('补贡券仍不足(%d/%d)，星辰石%d颗，本周星斗免费宝箱已领完；停止，不使用点券'
                               %(have,need,quantity(info,'bag',STONE)))
        log('星辰石不足，调用一次星斗路由：本周剩余免费宝箱%d次'%free)
        import star_maze
        star_maze.run_star_maze(flow,info,account.get('record_index'))
        info=entry(flow,account)
        st=week_state(info);stones=quantity(info,'bag',STONE)
        left_shop=max(0,limit-st['shop_bought']) if limit>0 else need
        want=min(need-have,left_shop,stones)
        if want<=0:
            raise RuntimeError('星斗奖励领取后仍无法兑换：券%d/%d 石%d 商店余%d'
                               %(have,need,stones,left_shop))
        while want>0:
            r=flow.request('scene.shopHandler.buy',{'shopId':SHOP_ID,'count':1})
            if not isinstance(r,dict) or r.get('error'):
                raise RuntimeError('星斗商店兑换失败：%s'%(r.get('error') if isinstance(r,dict) else r))
            given=sum(int(x.get('count') or 0) for x in (r.get('give') or []) if str(x.get('subType'))==COUPON)
            if given!=1:raise RuntimeError('星斗商店兑换回包异常：%s'%r.get('give'))
            want-=1;time.sleep(.4)
        info=entry(flow,account)
        have=quantity(info,'bag',COUPON)
        if have<need:
            raise RuntimeError('补贡券仍不足(%d/%d)，停止，不使用点券'%(have,need))
    return info


def run(flow,info,account,log,max_days=0,use_maze=True,use_shop=True):
    """按顺序补本周缺失日期；返回最终 info。每次补贡后重新读取服务器状态核对。"""
    from feature_account import entry
    done=0
    while True:
        if max_days and done>=max_days:break
        rows=plan(info)
        if not rows:
            log('本周暂无可补贡日期（服务器日期周%s，已贡日=%s）'
                %(week_day(info) or 7,'、'.join(map(str,week_state(info)['days'])) or '无'))
            break
        step=rows[0]
        log('补第%d天：档位%d，%s'%(step['day'],step['count'],
              '灵魂%d'%step['spirit'] if step['type']==0 else '补贡券%d张'%step['need']))
        if step['type']==2:
            if not use_shop:
                raise RuntimeError('缺补贡券但已禁用商店兑换；停止，不使用点券')
            if quantity(info,'bag',COUPON)<step['need']:
                if not use_maze:
                    raise RuntimeError('补贡券不足且已禁用星斗幻境；停止，不使用点券')
                info=buy_coupons(flow,info,account,step['need'],log)
        before=week_state(info);spirit0=int(info.get('spirit') or 0)
        coupon0=quantity(info,'bag',COUPON)
        r=flow.request('scene.leagueHandler.leagueRedevote',{'day':step['day'],'type':step['type']})
        if not isinstance(r,dict) or r.get('error'):
            raise RuntimeError('第%d天补贡失败：%s'%(step['day'],r.get('error') if isinstance(r,dict) else r))
        time.sleep(.5);info=entry(flow,account)
        after=week_state(info)
        spirit1=int(info.get('spirit') or 0);coupon1=quantity(info,'bag',COUPON)
        if step['day'] not in after['days'] or after['count']!=before['count']+1:
            raise RuntimeError('第%d天补贡未生效：count %d→%d days %s→%s'
                               %(step['day'],before['count'],after['count'],before['days'],after['days']))
        if step['type']==0 and spirit0-spirit1!=step['spirit']:
            raise RuntimeError('第%d天灵魂扣除异常：%d→%d，应减%d'%(step['day'],spirit0,spirit1,step['spirit']))
        if step['type']==2 and coupon0-coupon1!=step['need']:
            raise RuntimeError('第%d天补贡券扣除异常：%d→%d，应减%d'%(step['day'],coupon0,coupon1,step['need']))
        log('第%d天补贡成功：贡献+12，本周已补贡%d次，剩余补贡券%d张，星辰石%d颗'
            %(step['day'],after['count'],coupon1,quantity(info,'bag',STONE)))
        done+=1
    return info


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--account',default='',help='accounts 目录下账号文件名；留空=工具箱当前账号')
    ap.add_argument('--slot',type=int)
    ap.add_argument('--dry-run',action='store_true',help='只读取并打印本周补贡计划，不执行')
    ap.add_argument('--max-days',type=int,default=0,help='本次最多补几天，0=全部可补日期')
    ap.add_argument('--no-maze',action='store_true',help='缺星辰石时不跑星斗幻境')
    ap.add_argument('--no-shop',action='store_true',help='不自动兑换补贡券')
    args=ap.parse_args()
    import feature_account as ta
    if args.account:
        source=json.loads((ROOT/'accounts'/(args.account+'.json')).read_text(encoding='utf-8-sig'))
        ta.ACCT=dict(uid=source['uid'],username=source['username'],cookies=source['cookies'],
                     record_index=int(source.get('record_index') or 0))
        label=source['username']
    else:
        import daily_auto as da
        ta.ACCT=dict(uid=da.UID,username=da.USERNAME,cookies=da.COOKIES,record_index=da.RECORD_INDEX)
        label=da.USERNAME
    if args.slot is not None:ta.ACCT['record_index']=args.slot
    print('账号：%s（槽%s）'%(label,ta.ACCT['record_index']),flush=True)
    flow=None
    try:
        flow=ta.connect(ta.ACCT);info=ta.entry(flow,ta.ACCT)
        st=week_state(info)
        print('当前：周%s 已贡日=%s 已补贡%d次 补贡券%d张 星辰石%d颗 星斗免费宝箱剩%d次'
              %(week_day(info) or 7,'、'.join(map(str,st['days'])) or '无',st['count'],
                quantity(info,'bag',COUPON),quantity(info,'bag',STONE),maze_free_left(info)),flush=True)
        rows=plan(info)
        if not rows:
            print('本次无补贡计划：周一00:00周重置后需等出现已过去的日期。',flush=True)
            return
        print('补贡计划：',json.dumps(rows,ensure_ascii=False),flush=True)
        if args.dry_run:return
        run(flow,info,ta.ACCT,lambda s:print(s,flush=True),args.max_days,
            use_maze=not args.no_maze,use_shop=not args.no_shop)
    finally:
        if flow:
            try:flow.disconnect()
            except Exception:pass


if __name__=='__main__':main()
