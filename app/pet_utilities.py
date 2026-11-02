"""宠物采集、妖王帖免费招募、藏宝仙魄日限卷轴。"""
import argparse,json,time,os
from pathlib import Path
from datetime import datetime
from bag_warehouse import quantity
from old_shop import inventory
ROOT=Path(__file__).resolve().parent
CFG=ROOT/'cg_config_out_cg1_20261012_1'
def table(name):return json.loads((CFG/(name+'.json')).read_text(encoding='utf-8-sig'))
def checked(reply):
    if not isinstance(reply,dict) or reply.get('code')!=200 or reply.get('error'):raise RuntimeError('服务器拒绝：'+str(reply))
    return reply

def scrolls():
    return {k:v for k,v in table('Shop').items() if str(v.get('type'))=='8' and v.get('consume_type')=='coin' and v.get('consume_subType')=='fairyMoney' and int(v.get('dayPurchaseMaxNum') or 0)>0 and not v.get('extTicket')}

def free_quota(info,card_id=1):
    cfg=table('MonsterCardLottery')[str(card_id)];vip=int((info.get('vip') or {}).get('level',0));quotas=[int(v) for v in cfg['vipFreeNum'].split(';')]
    if not 0<=vip<len(quotas):raise ValueError('VIP免费次数配置缺失')
    daily=info.get('everyDaySetting')
    if not isinstance(daily,dict):raise ValueError('未读取到每日计数，禁止抽取')
    data=daily.get('monsterCardLottery') or {};used=int(data.get('freeNum_'+str(card_id),0));limit_used=int(data.get('limit_'+str(card_id),0))
    return {'vip':vip,'limit':quotas[vip],'used':used,'remaining':max(0,min(quotas[vip]-used,int(cfg['monsterCardLotteryDayNum'])-limit_used))}

def bought(info,sid):
    data=((info.get('everyDaySetting') or {}).get('shopBuyCount') or {}).get(str(sid),{})
    return int(data.get('buyCount',0)) if isinstance(data,dict) else int(data or 0)

def photo_status(info,collect_id=None):
    photos=table('CollectPhoto');album=info.get('petAlbum')
    if not isinstance(album,dict):return {'known':False,'missing':[],'related_missing':[],'photos':[]}
    def describe(pid):
        c=photos.get(str(pid),{})
        return {'id':int(pid),'name':c.get('name','未知照片'),'group':c.get('nameMax','')}
    owned={str(k) for k,v in album.items() if k!='reward' and isinstance(v,dict)}
    missing=[describe(k) for k in sorted(photos,key=int) if k not in owned]
    ids=str(table('Collect').get(str(collect_id),{}).get('photoId','-1')).split(';')
    related=[describe(k) for k in ids if k not in ('','-1') and k not in owned]
    rows=[]
    for k in sorted(photos,key=int):
        record=album.get(k) if isinstance(album.get(k),dict) else {}
        rows.append({**describe(k),'owned':k in owned,'time':record.get('time'),
                     'pet':record.get('nickName') or record.get('name',''),'level':record.get('level')})
    return {'known':True,'owned':len(set(photos)&owned),'total':len(photos),'missing':missing,'related_missing':related,'photos':rows}

def photo_result(before,after,reply,collect_id):
    result=photo_status(after,collect_id)
    pid=reply.get('photoId');result.update(photoId=pid,rate=reply.get('rate'))
    a=before.get('petAlbum') or {};b=after.get('petAlbum') or {}
    result['album_added']=[k for k in b if k!='reward' and k not in a]
    result['album_updated']=[k for k in b if k!='reward' and k in a and a[k]!=b[k]]
    if reply.get('code')!=200 or reply.get('error'):result['outcome']='failed'
    elif pid is None:result['outcome']='unknown'
    elif int(pid)<=0:result['outcome']='none'
    else:
        result['photo']=table('CollectPhoto').get(str(pid),{'name':'未知照片','id':pid})
        result['persisted']=isinstance(b.get(str(pid)),dict)
        result['changed']=str(pid) in result['album_added']+result['album_updated']
        result['outcome']='confirmed' if result['persisted'] and result['changed'] else 'needs_check'
    return result

def print_photo_result(result):
    outcome=result['outcome']
    if outcome=='none':text='本次未出照片（photoId=%s）'%result['photoId']
    elif outcome in ('confirmed','needs_check'):
        photo=result['photo'];text='本次照片：%s（ID %s）；%s'%(photo.get('name','未知'),result['photoId'],'相册新增/更新已核对' if outcome=='confirmed' else '服务器回包与相册变化需进一步核对')
    else:text='领奖失败，未判定出片' if outcome=='failed' else '回包缺少photoId，无法判断本次出片'
    print('[采集照片] '+text,flush=True)
    if result.get('rate') is not None:print('[采集照片] 服务器rate原值：'+str(result['rate'])+'（不在本地决定是否出片）',flush=True)
    if result['known']:
        print('[采集照片] 相册已收集%d/%d；全相册缺%d张'%(result['owned'],result['total'],len(result['missing'])),flush=True)
        print('[采集照片] 全相册尚缺：'+('、'.join('%s[%s]'%(p['name'],p['id']) for p in result['missing']) or '已集齐'),flush=True)
        print('[采集照片] 本材料尚缺：'+('、'.join('%s[%s]'%(p['name'],p['id']) for p in result['related_missing']) or '已集齐／该材料无对应照片'),flush=True)
    else:print('[采集照片] 未下发相册，缺图状态未知',flush=True)

def status(info,user):
    props=table('Prop');collect=info.get('collectData')
    slots=[]
    for pos in range(3):
        d=(collect or {}).get(str(pos),{}) or {};finish=d.get('finishTime',0)
        slots.append({'pos':pos,'name':props.get(str(d.get('collectId')),{}).get('name','空闲'),**d,'finished':bool(d and not d.get('reward') and finish and finish<=time.time()*1000)})
    pets=[]
    for key,p in (info.get('bag',{}).get('pet') or {}).items():
        pets.append({'entityId':p.get('entityId',key),'name':p.get('nickName') or p.get('name') or str(p.get('id')),'level':p.get('level'),'busy':any(s.get('petEntityId')==p.get('entityId',key) and not s.get('reward') for s in slots)})
    goods=[{'id':int(k),'name':v['name'],'price':int(v['consume_count']),'remaining':max(0,int(v['dayPurchaseMaxNum'])-bought(info,k))} for k,v in scrolls().items()]
    vip=int((info.get('vip') or {}).get('level',0));gear=int(table('VIP').get(str(vip),{}).get('collectGear',0))
    album=photo_status(info);missing={str(p['id']):p for p in album['missing']}
    by_material={str(k):[missing[pid] for pid in str(v.get('photoId','-1')).split(';') if pid in missing] for k,v in table('Collect').items()}
    return {'photo_status':album,'photo_by_material':by_material,'slots':slots,'pets':pets,'card':free_quota(info),'scrolls':goods,'fairyMoney':info.get('fairyMoney'),'ticket':user.get('ticket'),'collectGear':gear}

def wallet(info,user):return {'ticket':user.get('ticket'),'fairyMoney':info.get('fairyMoney'),'spirit':user.get('spirit'),'yuanbao':user.get('yuanbao')}

def perform(flow,info,user,action,refresh,*,pos=0,collect_id=None,entity=None,gear=0,shop=None,count=1,password=''):
    if user.get('ticket') is None:raise ValueError('未读取到点券余额，停止操作')
    params=None;route=None;before_quota=None
    if action=='start':
        cfg=table('Collect').get(str(collect_id))
        if not cfg:raise ValueError('采集材料无效')
        s=status(info,user)
        if not 0<=pos<3 or not 0<=gear<=min(2,s['collectGear']):raise ValueError('采集位置或时长未开放')
        slot=s['slots'][pos]
        if slot.get('collectId') and not slot.get('reward'):raise ValueError('该位置尚未领奖，不能覆盖')
        pet=next((p for p in s['pets'] if p['entityId']==entity),None)
        if not pet or pet['busy']:raise ValueError('宠物不存在或正在采集')
        route='scene.petHandler.collect';params={'pos':pos,'collectId':int(collect_id),'entityId':entity,'gear':gear}
    elif action=='reward':
        if not 0<=pos<3:raise ValueError('采集位置无效')
        slot=status(info,user)['slots'][pos]
        if not slot['finished']:raise ValueError('该位置未完成采集或已领奖，不发送领取请求')
        route='scene.petHandler.getCollectReward';params={'pos':pos,'double':0,'must':0}
    elif action=='card':
        before_quota=free_quota(info)
        if before_quota['remaining']<=0:raise ValueError('无免费妖王帖次数，禁止转为道具抽取')
        route='scene.monsterCardHandler.lottery';params={'id':1}
    elif action=='buy':
        cfg=scrolls().get(str(shop))
        if not cfg:raise ValueError('仅允许藏宝仙魄日限商品')
        if type(count) is not int or count<1 or count>int(cfg['dayPurchaseMaxNum'])-bought(info,shop):raise ValueError('购买数量超过剩余日限额')
        if info.get('fairyMoney') is None or info['fairyMoney']<int(cfg['consume_count'])*count:raise ValueError('仙魄不足或余额未读取')
        route='scene.shopHandler.buy';params={'shopId':int(shop),'count':count,'password':password}
    else:raise ValueError('未知操作')
    before_wallet=wallet(info,user);before_items=inventory(info);before_keys={k:quantity(info,'bag',k) for k in ['101039001','101039002']}
    reply=flow.request(route,params)
    after=refresh();after_user=checked(flow.request('connector.roleHandler.getUserInfo',{}))['user'];after_wallet=wallet(after,after_user);after_items=inventory(after)
    delta=[]
    for key in before_items.keys()|after_items.keys():
        a=before_items.get(key,{}).get('count',0);b=after_items.get(key,{}).get('count',0)
        if a!=b:delta.append({'key':key,'before':a,'after':b,'delta':b-a})
    report={'action':action,'route':route,'params':{k:v for k,v in params.items() if k!='password'},'reply':reply,'needs_password':reply.get('code')==502,'wallet_before':before_wallet,'wallet_after':after_wallet,'inventory_delta':delta,'ticket_unchanged':before_wallet['ticket']==after_wallet['ticket']}
    ok=reply.get('code')==200 and not reply.get('error')
    if action=='card':
        report['quota_before']=before_quota;report['quota_after']=free_quota(after)
        report['free_verified']=ok and report['quota_after']['used']==before_quota['used']+1 and report['ticket_unchanged'] and all(quantity(after,'bag',k)==v for k,v in before_keys.items())
    if action=='buy':
        cfg=scrolls()[str(shop)];pid=str(cfg['sell_subType']);expected_cost=int(cfg['consume_count'])*count
        report.update(bought_before=bought(info,shop),bought_after=bought(after,shop),expected_fairy_cost=expected_cost,
            verified=ok and report['ticket_unchanged'] and info['fairyMoney']-after.get('fairyMoney',info['fairyMoney'])==expected_cost
            and bought(after,shop)==bought(info,shop)+count
            and quantity(after,'bag',pid)-quantity(info,'bag',pid)==int(cfg['sell_count'])*count)
    elif action=='start':
        d=(after.get('collectData') or {}).get(str(pos),{}) or {}
        report['verified']=ok and report['ticket_unchanged'] and int(d.get('collectId',0))==int(collect_id) and d.get('petEntityId')==entity and int(d.get('gear',-1))==gear and not d.get('reward')
    elif action=='reward':
        collect_id=((info.get('collectData') or {}).get(str(pos)) or {}).get('collectId')
        report['photos']=photo_result(info,after,reply,collect_id)
        print_photo_result(report['photos'])
        d=(after.get('collectData') or {}).get(str(pos),{}) or {}
        report['verified']=ok and report['ticket_unchanged'] and (not d or bool(d.get('reward')))
    return report,after,after_user

def draw_free_cards(flow,info,user,count,refresh):
    if type(count) is not int or count<1:raise ValueError('抽取次数必须为正整数')
    available=free_quota(info)['remaining']
    if count>available:raise ValueError('所选次数超过剩余免费次数，未抽取')
    reports=[]
    for i in range(count):
        if free_quota(info)['remaining']<=0:break
        if i:time.sleep(1)
        report,info,user=perform(flow,info,user,'card',refresh)
        reports.append(report)
        if not report.get('free_verified'):break
    return reports,info,user

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--action',choices=['status','start','reward','card','buy'],default='status');p.add_argument('--pos',type=int,default=0);p.add_argument('--collect-id',type=int);p.add_argument('--entity');p.add_argument('--gear',type=int,default=0);p.add_argument('--shop',type=int);p.add_argument('--count',type=int,default=1);a=p.parse_args()
    from teacher_trial import connect,enter
    account=json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig'));slot=int(account.get('record_index',0));f=None
    try:
        f,info=connect(account,slot);user=checked(f.request('connector.roleHandler.getUserInfo',{}))['user']
        if a.action!='status':
            if a.action=='card':
                reports,info,user=draw_free_cards(f,info,user,a.count,lambda:enter(f,slot))
            else:
                report,info,user=perform(f,info,user,a.action,lambda:enter(f,slot),pos=a.pos,collect_id=a.collect_id,entity=a.entity,gear=a.gear,shop=a.shop,count=a.count,password=os.environ.pop('ZM5_PET_UTILITY_PASSWORD',''))
                reports=[report]
            for report in reports:
                print('[执行结果] '+json.dumps(report,ensure_ascii=False),flush=True)
            report=reports[-1]
            if a.action=='card':print('[妖王帖] 计划%s次，成功%s次；剩余免费%s次'%(a.count,sum(bool(r.get('free_verified')) for r in reports),free_quota(info)['remaining']),flush=True)
            folder=ROOT/'pet_utility_reports';folder.mkdir(exist_ok=True);path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json');path.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
            print('[宠物采集/免费招募/藏宝购买] '+json.dumps(report,ensure_ascii=False),flush=True)
            if report.get('needs_password'):print('[二级密码] 服务器要求正确的二级密码，请在藏宝购买页填写后手动重试；本次未重发。',flush=True)
            if report.get('verified',report.get('free_verified')) is False:print('[核对异常] 服务端回复或到账/状态变化未通过核对，请查看报告；未重试。',flush=True)
            if not report['ticket_unchanged']:print('[异常] 点券发生变化，停止；未重试。',flush=True)
        data=status(info,user);data.update(account=str(account.get('username','')),slot=slot)
        if a.action=='reward':data['last_photo_result']=report.get('photos')
        print('__PET_UTILITY_STATE__'+json.dumps(data,ensure_ascii=False),flush=True)
    finally:
        if f:f.disconnect()
if __name__=='__main__':main()
