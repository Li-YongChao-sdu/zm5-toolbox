"""主程序狗卡管理：单轮操作，发送前留痕，未知结果不重发。"""
import argparse,json,os,time,copy
from pathlib import Path
from datetime import datetime
from union_boss_batch import DOG_NAMES,dog_inventory
from teacher_trial import connect,enter,checked
ROOT=Path(__file__).resolve().parent

def execute(flow,slot,action,ids,code,save,sleep=time.sleep):
    report={'action':action,'requests':[],'status':'running'}
    def publish(state,status,message):
        print('__DOG_CARD_STATE__'+json.dumps({'uid':str(getattr(flow,'uid',state['rid'].split('_r')[0])),'slot':slot,'state':state,'status':status,'message':message},ensure_ascii=False),flush=True)
    def snapshot():
        info=enter(flow,slot)
        dog=checked(flow.request('scene.activityHandler.getDouble11Data',{}),'查询狗卡')
        user=checked(flow.request('connector.roleHandler.getUserInfo',{}),'查询余额')['user']
        return {'rid':info['_id'],'cards':dog_inventory(dog),'daily':{k:v for k,v in (info.get('everyDaySetting') or {}).items() if 'double11' in k.lower()},'wallet':{k:user[k] for k in ('ticket','yuanbao')}}
    def write(route,params):
        row={'route':route,'params':{k:('[redacted]' if k=='cdkey' else v) for k,v in params.items()},'phase':'pending'}
        report['requests'].append(row);save(report)
        try:reply=flow.request(route,params)
        except Exception:row['phase']='uncertain';save(report);raise
        row.update(phase='returned',reply=copy.deepcopy(reply));save(report)
        return checked(reply,'狗卡操作')
    def verify(a,b,delta,activate=None):
        if a['rid']!=b['rid'] or a['wallet']!=b['wallet']:raise ValueError('身份或个人余额变化，停止')
        for n,(old,new) in enumerate(zip(a['cards'],b['cards']),1):
            if new['count']-old['count']!=delta.get(n,0):raise ValueError('卡片变化未核对通过')
            if n==activate:
                if not new['active']:raise ValueError('激活状态未确认')
            elif new['active']!=old['active']:raise ValueError('其他激活状态变化')
    try:
        state=snapshot();report['before']=state;save(report);publish(state,'running','已读取库存；正在执行所选操作')
        if action=='query':
            for row in state['cards']:print('%s：%s张｜%s｜可赠送%s张'%(row['name'],row['count'],'已激活' if row['active'] else '未激活',row['giftable']),flush=True)
            print('今日次数：'+json.dumps(state['daily'],ensure_ascii=False),flush=True)
        elif action=='activate':
            for n in ids:
                row=state['cards'][n-1]
                if row['active'] or row['count']<1:print(row['name']+'：已激活或缺卡，跳过',flush=True);continue
                write('scene.activityHandler.activeDouble11Dog',{'id':n,'type':0});after=snapshot();verify(state,after,{n:-1},n);state=after
                print(row['name']+'：激活成功',flush=True)
        elif action=='redeem':
            if not code:raise ValueError('请输入兑换码')
            reply=write('scene.activityHandler.double11Code2Dog',{'cdkey':code});after=snapshot();delta={}
            for item in reply.get('give') or []:
                if item.get('type')=='coin' and str(item.get('subType','')).startswith('dog_'):
                    n=int(item['subType'][4:]);delta[n]=delta.get(n,0)+int(item['count'])
            if not delta:raise ValueError('领取未返回可核对的狗卡奖励')
            verify(state,after,delta);state=after;print('兑换码领取成功：'+str({DOG_NAMES[n-1]:v for n,v in delta.items()}),flush=True)
        elif action=='gift_draw':
            n=ids[0];row=state['cards'][n-1]
            if not row['active'] or row['count']<1:raise ValueError('请选择已激活且持有余卡的品种')
            old_extra=int(state['daily'].get('addDouble11LotteryCnt',0))
            if old_extra>=1:raise ValueError('今日赠送额外机会已获得，不继续消耗余卡')
            reply=write('scene.activityHandler.double11Dog2Code',{'id':n,'type':1});after=snapshot();verify(state,after,{n:-1});report['generated_code']=reply.get('cdkey');save(report)
            if not report['generated_code']:raise ValueError('未读到赠送码，停止')
            daily=reply.get('everyDaySetting') or after['daily'];extra=int(daily.get('addDouble11LotteryCnt',0));used=int(daily.get('double11LotteryCnt',0))
            if extra<=old_extra or 1+extra-used<=0:raise ValueError('已生成码，但未确认新增抽数，不抽卡')
            state=after;sleep(2);reply=write('scene.activityHandler.double11Lottery',{});after=snapshot();delta={}
            for item in reply.get('give') or []:
                if item.get('type')=='coin' and str(item.get('subType','')).startswith('dog_'):
                    k=int(item['subType'][4:]);delta[k]=delta.get(k,0)+int(item['count'])
            if not delta:raise ValueError('额外抽取无可核对的卡片奖励')
            verify(state,after,delta)
            if int((reply.get('everyDaySetting') or after['daily']).get('double11LotteryCnt',0))!=used+1:raise ValueError('抽数核对失败')
            state=after;print('赠送及额外抽卡成功：'+str({DOG_NAMES[k-1]:v for k,v in delta.items()}),flush=True)
        else:raise ValueError('未知操作')
        report.update(status='complete',after=state);save(report);publish(state,'complete',{'query':'库存查询完成','activate':'所选激活处理完成，已激活或缺卡项目跳过','redeem':'兑换码领取成功，卡片到账已核对','gift_draw':'赠送及额外抽取成功，到账已核对'}[action]);return report
    except Exception:
        report['status']='stopped';save(report)
        if 'before' in report:publish(report.get('after',report['before']),'stopped','操作未完成，表格保留最后核对信息；请核对私有记录，勿重复提交')
        raise

def main():
    p=argparse.ArgumentParser();p.add_argument('--action',choices=('query','activate','redeem','gift_draw'),required=True);p.add_argument('--id',type=int,choices=range(1,12),action='append');p.add_argument('--account',required=True);p.add_argument('--slot',type=int,required=True);a=p.parse_args()
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'))
    if str(account['uid'])!=a.account or int(account['record_index'])!=a.slot:raise ValueError('账号或槽位已改变，请重新执行')
    folder=ROOT/'dog_card_reports';folder.mkdir(exist_ok=True)
    for old in folder.glob('*.private.json'):
        olddata=json.loads(old.read_text(encoding='utf8'))
        if a.action!='query' and olddata.get('uid')==a.account and olddata.get('slot')==a.slot and olddata.get('status')!='complete' and any(q.get('phase') in ('pending','uncertain') or (q.get('reply') or {}).get('code')==200 for q in olddata.get('requests',[])):raise ValueError('此存档有未完成狗卡操作，请先核对本地记录，不自动重试')
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.private.json')
    def save(report):
        data=dict(report,uid=a.account,slot=a.slot);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
    flow=None
    try:
        flow,_=connect(account,a.slot);report=execute(flow,a.slot,a.action,list(dict.fromkeys(a.id or [1])),os.environ.pop('ZM5_DOG_REDEEM_CODE',''),save)
        if report.get('generated_code'):print('赠送码已保存在私有记录，请在狗卡管理中查看上次生成码。',flush=True)
        print('狗卡记录：'+str(path),flush=True)
    except Exception as exc:
        print('狗卡操作停止（%s），请核对记录，不自动重发'%type(exc).__name__,flush=True);raise SystemExit(1)
    finally:
        if flow:flow.disconnect()
if __name__=='__main__':main()
