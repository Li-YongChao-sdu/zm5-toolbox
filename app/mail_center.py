"""邮件列表与领取；领取接口同时删除邮件，不自动重试。"""
import argparse,json
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parent

def checked(reply):
    if reply.get('code')!=200 or reply.get('error'):raise RuntimeError(str(reply))
    return reply

def wallet(flow):
    u=checked(flow.request('connector.roleHandler.getUserInfo',{}))['user']
    return {k:u.get(k) for k in ('ticket','yuanbao','spirit','rechargeMoney')}

def counts(info):
    result={}
    for tab,items in (info.get('bag') or {}).items():
        if not isinstance(items,dict):continue
        for key,v in items.items():
            if isinstance(v,dict):result[tab+'/'+str(key)]=int(v.get('count') or 1)
    return result

def claim(flow,mail_id,refresh):
    before_list=checked(flow.request('scene.mailHandler.getAllMail',{}))['mails']
    if not any(str(m.get('id'))==str(mail_id) for m in before_list):raise ValueError('邮件已不存在，请刷新')
    before_wallet=wallet(flow);before=counts(refresh())
    reply=flow.request('scene.mailHandler.getAndRemoveMail',{'mailId':mail_id})
    after_list=checked(flow.request('scene.mailHandler.getAllMail',{}))['mails']
    after_wallet=wallet(flow);after=counts(refresh())
    delta={k:after.get(k,0)-before.get(k,0) for k in before.keys()|after.keys() if after.get(k,0)!=before.get(k,0)}
    return {'mailId':mail_id,'reply':reply,'removed':not any(str(m.get('id'))==str(mail_id) for m in after_list),
            'wallet_before':before_wallet,'wallet_after':after_wallet,'inventory_delta':delta},after_list

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--claim');args=parser.parse_args()
    from teacher_trial import connect,enter
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account.get('record_index',0));flow=None
    try:
        flow,info=connect(account,slot)
        if args.claim:
            report,mails=claim(flow,args.claim,lambda:enter(flow,slot))
            folder=ROOT/'mail_reports';folder.mkdir(exist_ok=True)
            path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json');path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print('[邮件领取] '+json.dumps(report,ensure_ascii=False),flush=True)
            print('[邮件] 已记录回包、邮件移除状态、货币及背包变化；请按实际发放核对。报告：'+str(path),flush=True)
        else:mails=checked(flow.request('scene.mailHandler.getAllMail',{})).get('mails',[])
        print('__MAIL_STATE__'+json.dumps({'account':str(account.get('username','')),'slot':slot,'mails':mails},ensure_ascii=False),flush=True)
    finally:
        if flow:flow.disconnect()
if __name__=='__main__':main()
