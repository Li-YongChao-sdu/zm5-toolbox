"""仅出售精英本场确认新增的BOSS或木矿布材料，强化石不在出售白名单。"""
import json
from pathlib import Path
from datetime import datetime
from bag_warehouse import quantity,sell
ROOT=Path(__file__).resolve().parent
def sale_candidates(before,after,rewards,boss=False,small=False,card_rewards=None,medicine=False):
    cfg=ROOT/'cg_config_out_cg1_20261019_1'
    exchange=json.loads((cfg/'PropExchange.json').read_text(encoding='utf8'))
    props=json.loads((cfg/'Prop.json').read_text(encoding='utf8'))
    kinds=({2,3,4} if boss else set())|({5,6,7} if small else set())
    candidates=[]
    for key,amount in rewards.items():
        pid=str(key);row=exchange.get(pid);prop=props.get(pid,{})
        contents=str(prop.get('attributeV1','')).split(';')
        boss_package=bool(boss and prop.get('attributeT1')=='item' and contents
                          and all(exchange.get(k,{}).get('type') in (2,3,4) for k in contents))
        card_medicine=bool(medicine and int((card_rewards or {}).get(pid,0))>0 and prop.get('propType')==1009)
        if (not row or row.get('type') not in kinds) and not boss_package and not card_medicine:continue
        if str(prop.get('isSell',0))!='1':continue
        new=quantity(after,'bag',pid)-quantity(before,'bag',pid)
        count=min(int(amount),new)
        if card_medicine:count=min(count,int(card_rewards[pid]))
        if count>0:candidates.append({'id':pid,'name':prop.get('name') or (row or {}).get('name',pid),'count':count})
    return candidates
def sell_round(flow,before,current,user,rewards,refresh,*,boss=False,small=False,password='',card_rewards=None,medicine=False):
    candidates=sale_candidates(before,current,rewards,boss,small,card_rewards,medicine)
    if not candidates:
        print('[精英材料出售] 本场没有所选类别的新增可售材料；强化石及原库存保留',flush=True)
        return current,user
    reports=[];folder=ROOT/'elite_sale_reports';folder.mkdir(exist_ok=True)
    path=folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    for row in candidates:
        # 保留开战前库存，即使前一次操作改变了状态也不扩大出售数量。
        surplus=quantity(current,'bag',row['id'])-quantity(before,'bag',row['id'])
        n=min(row['count'],surplus)
        if n<=0:continue
        print('[精英材料出售] %s×%s（仅本场新增）'%(row['name'],n),flush=True)
        report,current,user=sell(flow,current,user,row['id'],n,password,refresh)
        reports.append({'item':row,**report})
        path.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
        if not report['verified']:
            error=(report.get('reply') or {}).get('error') or '库存／点券核对未通过'
            raise RuntimeError('精英材料出售停止：%s；需要二级密码时请填写后重新执行；未自动重试。报告%s'%(error,path))
        print('[精英材料出售] 已核对%s×%s，点券%s→%s'%(row['name'],n,report['ticket_before'],report['ticket_after']),flush=True)
    return current,user
