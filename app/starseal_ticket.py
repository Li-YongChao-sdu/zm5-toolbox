"""按自选数量购买诸星挑战券，禁止自动购买。"""
import argparse
import feature_account as account

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, required=True)
    args = parser.parse_args()
    if args.count < 1:
        parser.error('购买数量必须为正整数')
    flow = account.connect(account.ACCT)
    try:
        info = account.entry(flow, account.ACCT)
        cost = args.count * 1000
        if int(info.get('petArenaMoney') or 0) < cost:
            raise RuntimeError('斗宠币不足：需要%d' % cost)
        result = flow.request('scene.shopHandler.buy', {'shopId':9040, 'count':args.count})
        if result.get('code') != 200 or result.get('error'):
            raise RuntimeError(str(result))
        after = account.entry(flow, account.ACCT)
        print('购买完成；当前挑战券：%s；斗宠币：%s' %
              (((after.get('bag') or {}).get('item') or {}).get('101041001'), after.get('petArenaMoney')))
    finally:
        flow.disconnect()

if __name__ == '__main__':
    main()
