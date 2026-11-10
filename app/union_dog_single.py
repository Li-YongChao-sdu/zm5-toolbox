"""单账号狗卡写操作；私有留痕，结果不明不重试。"""
import json
from datetime import datetime
from pathlib import Path
from teacher_trial import connect
from dog_card_tool import execute

def run_single(account,slot,action,card,code):
    uid=str(account['uid']);folder=Path(__file__).resolve().parent/'dog_card_reports';folder.mkdir(exist_ok=True)
    for path in ([] if action=='codes' else folder.glob('*.private.json')):
        report=json.loads(path.read_text(encoding='utf-8'))
        if str(report.get('uid'))==uid and report.get('slot')==slot and report.get('status')!='complete' and any(r.get('phase') in ('pending','uncertain') or (r.get('reply') or {}).get('code')==200 for r in report.get('requests',[])):
            raise ValueError('此存档有未完成狗卡操作，请先核查私有记录')
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.private.json')
    def save(report):
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(dict(report,uid=uid,slot=slot,card=card),ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
    def publish(state,status,message):
        print('__UNION_DOG_OVERVIEW__'+json.dumps(dict(uid=uid,slot=slot,status='ok',cards=state['cards'],daily=state['daily']),ensure_ascii=False),flush=True)
        print(message,flush=True)
    flow=None
    try:
        flow,_=connect(account,slot)
        if action=='codes':
            from teacher_trial import enter,checked
            from union_boss_batch import DOG_NAMES
            enter(flow,slot)
            reply=checked(flow.request('scene.activityHandler.getDouble11Data',{}),'查询服务器兑换码')
            data=reply.get('data')
            if not isinstance(data,dict) or not isinstance(data.get('codeLog'),list):
                raise ValueError('服务器未返回有效codeLog，未使用本地记录替代')
            rows=[]
            for item in data['codeLog']:
                if not isinstance(item,list) or len(item)<3:raise ValueError('服务器兑换码记录格式异常')
                n=int(item[1])
                rows.append([DOG_NAMES[n-1] if 1<=n<=len(DOG_NAMES) else '未知卡种',str(item[2])])
            print('__UNION_DOG_CODES__'+json.dumps(dict(uid=uid,slot=slot,rows=rows),ensure_ascii=False),flush=True)
            return True
        execute(flow,slot,action,[card],code,save,publish_callback=publish)
        print('单账号操作完成；兑换码仅保存在本地私有记录。',flush=True)
        return True
    finally:
        if flow:flow.disconnect()
