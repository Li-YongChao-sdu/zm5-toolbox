"""噩梦宝石盒翻牌：跨周结转，按钥匙机会成本决策。"""
import random
from functools import lru_cache
KEY = 101006501
GEM = 101098002


EXTENDED_PROBABILITY = 0.55
KEY_RESERVE = 6


def should_continue(gems, results, balance, fee):
    opened = len(results)
    if opened == 0: return True  # 首张免费
    remaining = 4 - opened
    gem_remaining = gems - sum(results)
    if remaining <= 0 or gem_remaining <= 0 or balance < opened:
        return False
    if gem_remaining > remaining: return False
    @lru_cache(None)
    def value(n, g, cost, keys):
        if n <= 0 or g <= 0 or keys < cost: return 0.0
        p = g / n
        take = p * (1 + value(n-1, g-1, cost+1, keys-cost)) + (1-p) * value(n-1, g, cost+1, keys-cost) - fee * cost
        return max(0.0, take)
    p = gem_remaining / remaining
    take = p * (1 + value(remaining-1, gem_remaining-1, opened+1, balance-opened)) + (1-p) * value(remaining-1, gem_remaining, opened+1, balance-opened) - fee * opened
    return take > 1e-10


def static_continue(gems, results):
    opened = len(results)
    if opened == 0: return True
    if opened >= 4 or gems <= 1: return False
    if gems == 2: return opened < 3 and not any(results)
    if gems == 3: return not (opened >= 2 and results[0] and results[1])
    return True


def claim_cards_gem(flow, info, paid=False, strategy=None):
    strategy = strategy or ('dynamic' if paid else 'free')
    if strategy not in ('free', 'static', 'dynamic'):
        raise ValueError('未知噩梦翻牌策略')
    paid = strategy != 'free'
    bag=(info.setdefault('bag',{})).setdefault('item',{})
    item=bag.get(str(KEY)) or {}
    balance=int(item.get('count') or 0)
    initial=balance
    # 两种策略只在边际收益恰好为1/3盒/钥匙的选择上不同。
    # 库存足够时55%的场次接受这一档，长期约12.33把/20场；低库存优先积攒。
    extended = strategy == 'dynamic' and balance >= KEY_RESERVE and random.random() < EXTENDED_PROBABILITY
    fee = 1/3 - 1e-6 if extended else 1/3 + 1e-6
    print('[噩梦] 翻牌策略：%s' % {'free':'不使用翡翠钥匙','static':'静态策略','dynamic':'动态策略'}[strategy], flush=True)
    if strategy == 'dynamic':
        print('[噩梦] 跨周收益策略：%s；无周末清空或每周硬上限' %
              ('接受1/3边际收益档' if extended else '优先高收益档、保留钥匙'), flush=True)
    print('[噩梦] 当前背包翡翠钥匙×%s'%balance,flush=True)
    rewards=[];hits=[]
    try:
        cards=flow.request('scene.copyHandler.getCard',{})
        if not isinstance(cards,dict) or cards.get('code')!=200 or cards.get('error'):
            print('[噩梦] 牌面读取失败，停止翻牌',flush=True);return rewards
        items=cards.get('items') or []
        def item_id(row):
            if isinstance(row,dict): return str(row.get('subType') or row.get('id') or '')
            return str(row)
        if len(items)!=4:
            print('[噩梦] 牌面不是4张，停止翻牌',flush=True);return rewards
        gems=sum(item_id(row)==str(GEM) for row in items)
        print('[噩梦] 牌面扫描：%s；2级宝石盒×%s'%(items,gems),flush=True)
        def more():
            if strategy == 'free': return not hits
            if strategy == 'static': return static_continue(gems,hits)
            return should_continue(gems,hits,balance,fee)
        while more():
            number=len(hits)+1
            required=number-1
            if required and not paid:break
            if balance<required:
                print('[噩梦] 第%s张需%s把钥匙，余额%s，停止'%(number,required,balance),flush=True);break
            try: reply=flow.request('scene.copyHandler.turnCard',{})
            except Exception:
                print('[噩梦] 翻牌请求异常，停止；不重复提交',flush=True);break
            if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):
                print('[噩梦] 翻牌被拒绝：%s，停止'%(reply or {}),flush=True);break
            consumed=reply.get('consume') or []
            actual=0;unexpected=False
            for row in consumed:
                if row.get('type')=='item' and str(row.get('subType'))==str(KEY):
                    actual+=int(row.get('count') or 0)
                elif int(row.get('count') or 0)>0:unexpected=True
            balance=max(0,balance-actual)
            item['count']=balance;bag[str(KEY)]=item
            give=reply.get('give') or []
            rewards.extend(give)
            hits.append(any(item_id(row)==str(GEM) for row in give))
            print('[噩梦] 第%s张翻牌奖励%s；实际钥匙消耗%s'%(number,give,actual),flush=True)
            if actual!=required:
                print('[噩梦] 消耗与预计%s不符，以服务端%s为准，停止后续翻牌'%(required,actual),flush=True)
                break
            if unexpected:
                print('[噩梦] 出现非钥匙消耗，停止后续翻牌',flush=True);break
        print('[噩梦] 宝石盒策略：牌面%s个，已翻%s张'%(gems,len(hits)),flush=True)
        return rewards
    finally:
        print('[噩梦] 翻牌后剩余翡翠钥匙×%s（本次消耗×%s）'%(balance,initial-balance),flush=True)
