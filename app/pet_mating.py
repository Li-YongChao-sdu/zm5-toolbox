"""宠物上推荐：沿用客户端 mateApply 参数，密码不落盘。"""
import argparse
import json
import os
from pathlib import Path
from bag_warehouse import quantity

ROOT = Path(__file__).resolve().parent
FIELDS = {'physical': '体质', 'bone': '根骨', 'capacity': '潜力',
          'hpQualification': '生命资质', 'atkQualification': '攻击资质',
          'defQualification': '防御资质', 'reHpQualification': '回血资质'}

def table(name):
    return json.loads((ROOT/'cg_config_out_cg1_20261019_1'/(name+'.json')).read_text(encoding='utf-8-sig'))

def checked(reply):
    if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
        raise RuntimeError('服务器拒绝：%s' % (reply.get('error', reply.get('code')) if isinstance(reply,dict) else '无效回包'))
    return reply

def summarize(mate):
    mate = mate or {}
    cond = mate.get('cond') or {}
    pet = mate.get('pet') or {}
    return {'present': bool(pet), 'pet': {k: pet.get(k) for k in ('entityId','id','name','level','quality','sex')},
            'has_password': bool(cond.get('password') or mate.get('password')),
            'conditions': {k: cond.get(k) for k in FIELDS},
            'completed': bool(mate.get('rebirthData')), 'rebirthTime': mate.get('rebirthTime')}

def candidates(info):
    pets = table('Pet'); recipes = table('PetQualityUp'); labels = table('PetLabel'); props = table('Prop')
    result = []
    for key, pet in ((info.get('bag') or {}).get('pet') or {}).items():
        pid = str(pet['id'])
        if pid not in labels: continue
        targets = []
        for i in range(1, int(labels[pid]['labelNum'])+1):
            target = str(labels[pid]['icon'+str(i)])
            recipe = recipes.get(pid+'_'+target) or recipes.get(target+'_'+pid)
            if not recipe: continue
            cfg = pets[target]
            targets.append({'id': int(target), 'name': cfg['name'], 'level': int(recipe['petLevel']),
                            'material': int(recipe['consume_subType']), 'count': int(recipe['consume_count']),
                            'material_name': props[str(recipe['consume_subType'])]['name'],
                            'available': quantity(info,'bag',int(recipe['consume_subType'])),
                            'maxima': {k: int(str(cfg[k]).split(';')[-1]) for k in FIELDS}})
        if targets:
            result.append({'entityId': pet.get('entityId',key), 'id': int(pid), 'name': pet.get('name',pets[pid]['name']),
                           'level': int(pet['level']), 'quality': pet['quality'], 'sex': pet['sex'], 'targets': targets})
    return result

def build_params(pet, target, values, mode, password):
    if mode not in ('public','password'): raise ValueError('上架方式无效')
    if mode == 'password' and not password: raise ValueError('密码上架必须填写密码')
    cond = {}
    for k, label in FIELDS.items():
        text = str(values.get(k,''))
        if not text.isascii() or not text.isdecimal(): raise ValueError(label+'须为整数')
        value = int(text)
        if not 1 <= value <= target['maxima'][k]: raise ValueError('%s须为1～%s' % (label,target['maxima'][k]))
        cond[k] = str(value)
    if pet['level'] < target['level']: raise ValueError('宠物等级不足，要求%s级' % target['level'])
    if target['available'] < target['count']: raise ValueError('背包缺少'+target['material_name'])
    cond.update(id=target['id'], password=password if mode == 'password' else '')
    return {'entityId': pet['entityId'], 'petId': pet['id'], 'targetId': target['id'], 'cond': cond}

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--action',choices=['status','apply'],default='status')
    args = parser.parse_args()
    from teacher_trial import connect, enter
    account = json.loads((ROOT/'account.local.json').read_text(encoding='utf-8-sig')); slot=int(account['record_index']); flow=None
    request = json.loads(os.environ.pop('ZM5_PET_MATING_REQUEST','{}'))
    try:
        flow, _ = connect(account,slot); info=enter(flow,slot)
        mate=checked(flow.request('petMate.petMateHandler.getMateData',{})).get('petMate') or {}
        if args.action == 'apply':
            if str(request.get('account')) != str(account.get('username')) or request.get('slot') != slot:
                raise ValueError('账号或槽位已变化，请重新查询')
            if summarize(mate)['present']: raise ValueError('已有推荐记录，请先在游戏中领取或下架')
            pet=next((p for p in candidates(info) if p['entityId']==request.get('entity')),None)
            if not pet: raise ValueError('宠物已变化，请重新查询')
            target=next((t for t in pet['targets'] if t['id']==request.get('target')),None)
            if not target: raise ValueError('配对种类无效')
            params=build_params(pet,target,request['values'],request['mode'],request.get('password',''))
            before=checked(flow.request('connector.roleHandler.getUserInfo',{}))['user']
            if before.get('ticket') is None: raise ValueError('点券余额未知')
            print('[宠物上推荐] 提交一次：%s，%s，消耗%s×%s；结果不明时不重发' % (pet['name'],'密码上架' if params['cond']['password'] else '普通上架',target['material_name'],target['count']),flush=True)
            checked(flow.request('scene.petHandler.mateApply',params))
            mate=checked(flow.request('petMate.petMateHandler.getMateData',{})).get('petMate') or {}
            after=checked(flow.request('connector.roleHandler.getUserInfo',{}))['user']; info=enter(flow,slot)
            verified=((mate.get('pet') or {}).get('entityId')==pet['entityId'] and
                      all(str((mate.get('cond') or {}).get(k))==str(v) for k,v in params['cond'].items()) and
                      quantity(info,'bag',target['material'])==target['available']-target['count'] and
                      all(before.get(k)==after.get(k) for k in ('ticket','yuanbao')))
            print('[宠物上推荐] '+('上架、条件、材料及货币核对通过' if verified else '核对未通过，请刷新状态；未重发'),flush=True)
        data={'account':str(account.get('username','')),'slot':slot,'listing':summarize(mate),'pets':candidates(info)}
        print('__PET_MATING_STATE__'+json.dumps(data,ensure_ascii=False),flush=True)
    finally:
        if flow: flow.disconnect()

if __name__=='__main__': main()
