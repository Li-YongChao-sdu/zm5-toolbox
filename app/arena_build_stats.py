"""纯本地属性重建；来自已核对六宠 HP/抗性的客户端公式。"""
import math

def calculate(snapshot, configs):
    attrs=['hpMax','atk','phyDef','reHP','hit','dodge','critical','toughness','lucky','guardian']
    resattrs=['lightResist','darkResist','waterResist','fireResist','woodResist','soilResist','windResist','rayResist']
    def round_as(x):return math.floor(float(x)+0.5)
    def f(x):return format(x,',.10g')
    def number(x):return float(x or 0)
    used={n:{} for n in configs}
    def conf(name,key,required=True):
     key=str(key);v=configs[name].get(key)
     if v is None:
      if required:raise ValueError('缺配置 '+name+'/'+key)
      return {}
     used[name][key]=v;return v
    # 倍率由历史配置读取。
    common=[(k,v) for k,v in configs['Common'].items() if 'petpkHpMaxQualificationIndex' in v]
    assert len(common)==1
    multiplier=number(common[0][1]['petpkHpMaxQualificationIndex']);conf('Common',common[0][0])

    results=[]
    for side,user in enumerate(snapshot['data']):
     for rawpos,pet in enumerate(user['pets']):
      name=pet.get('nickName') or pet['name'];steps=[]
      def add(label,kind,values,formula,metadata=None):
       steps.append({'component':label,'kind':kind,'values':values,'formulas':formula,'metadata':metadata or {}})
      add('宠物基础','base',{k:number(pet.get(k)) for k in attrs},{k:'快照 pets.'+k for k in attrs})
      def item_calc(item,label):
       iid=str(item.get('id') or '')
       c={};source='无配置等级加成'
       if iid:
        if item.get('part')=='petElf':
         elf=conf('PetElf',iid);c=conf('PetElfAtt',elf['baseId']);source='PetElfAtt/'+str(elf['baseId'])
        else:c=conf('Equipment',iid,False);source='Equipment/'+iid if c else '无配置等级加成'
       vals={};formulas={}
       for k in attrs:
        raw=number(item.get(k));lev=number(item.get('level'));coeff=number(c.get(k+'Add'))
        strengthen=round_as(lev*coeff+0.0002) if item.get('part')!='petElf' or raw>0 else 0
        val=round_as(raw+0.0001)+strengthen
        vals[k]=val
        formulas[k]=f'Math.round({raw}+0.0001) + Math.round({lev}×{coeff}+0.0002) = {val}' if item.get('part')!='petElf' or raw>0 else f'Math.round({raw}+0.0001) + 0（真灵该项基础为0，不加等级成长） = {val}'
       add(label,'item',vals,formulas,{'id':iid,'source':source,'level':item.get('level',0)})
       for pos,gid in (item.get('inlay') or {}).items():
        g=conf('Prop',gid);k=g['attributeV1'];base=int(g['attributeV2'])
        assert k in attrs
        add(label+f'/孔{pos}/'+g['name'],'gem',{k:base},{k:f'Prop/{gid}.{k} = {base}'},{'gemId':gid})
        if item.get('injectLevel',0)>0:
         key=iid+'_'+str(item['injectLevel']);ic=conf('EquInject',key);coeff=number(ic[k]);value=round_as(coeff*base)
         add(label+f'/孔{pos}/注灵','inject',{k:value},{k:f'Math.round({base}×{coeff}) = {value}'},{'source':'EquInject/'+key})
        if int((item.get('extract') or {}).get('level',0))>0:raise ValueError('存在尚未实现的萃取：'+label)
       for k,v in (item.get('recast') or {}).items():
        assert k in attrs
        value=round_as(number(v['add'])+.0001);add(label+'/洗练','recast',{k:value},{k:f'Math.round({v["add"]}+0.0001) = {value}'})
       if item.get('inlaySoul') and item['inlaySoul'].get('entityId'):item_calc(item['inlaySoul'],label+'/符魂')
       if (item.get('petElfAtt') or {}).get('special'):item_calc(item['petElfAtt']['special'],label+'/真灵特殊属性')
      for slot,item in pet.get('equipments',{}).items():
       if slot in ('pet','fairy'):continue
       item_calc(item,slot)
      static={k:sum(s['values'].get(k,0) for s in steps) for k in attrs}
      # 宠物本体抗性 + 抗性被动的擂台折算。装备八系均为0，显式检查。
      pc=conf('Pet',pet['id']);assert int(pc['type'])==1
      resistance_steps=[];resists={k:number(pc.get(k)) for k in resattrs}
      for k in resattrs:resistance_steps.append({'attribute':k,'source':'Pet/'+str(pet['id']),'formula':'本体抗性 = '+str(resists[k]),'value':resists[k]})
      for skill,level in pet.get('skill',{}).get('passivity',{}).items():
       perk=conf('PetPerks',skill+'_'+str(level));k=perk.get('attributeT1')
       if k not in resattrs:continue
       base=number(perk.get('attributeV1'));growth=number(perk.get('boneValue'));bone=number(pet.get('bone'));value=round_as((base+growth*bone)*.45)
       resists[k]+=value
       resistance_steps.append({'attribute':k,'source':'PetPerks/'+skill+'_'+str(level),'formula':f'Math.round(({base}+{growth}×{bone})×0.45) = {value}','value':value})
      for item in pet['equipments'].values():
       assert not any(number(item.get(k)) for k in resattrs),'存在装备抗性，需要补汇总'
       c=configs['Equipment'].get(str(item.get('id')),{});assert not any(number(c.get(k+'Add')) for k in resattrs)
      battle=static.copy();battle['hpMax']=static['hpMax']*multiplier
      character=conf('PetCharacter',pet['character']);character_formulas={}
      for attr in ('atk','phyDef','dodge','critical'):
       coefficient=number(character.get(attr));battle[attr]=static[attr]+static[attr]*coefficient
       character_formulas[attr]=f"{static[attr]} + {static[attr]} × {coefficient} = {battle[attr]}"
      checks={'verified_against_runtime':False}
      elf=pet['equipments'].get('petElf') or {};ec=conf('PetElf',elf['id']) if elf else {}
      results.append({'name':name,'species':pet['name'],'player':user['name'],'rid':user['rid'],'side':'左/主场' if side==0 else '右/客场','raw_position':rawpos+1,'battle_position':3-rawpos if side==0 else rawpos+1,'pet_id':pet['id'],'entityId':pet['entityId'],'level':pet['level'],'bone':pet['bone'],'elf':{'id':elf.get('id'),'name':ec.get('name'),'level':elf.get('level'),'quality':ec.get('quality')},'character':{'id':pet['character'],'name':character['name'],'coefficients':{k:character.get(k,0) for k in ('atk','phyDef','dodge','critical')},'formulas':character_formulas},'static_10':static,'battle_initial_10':battle,'resistances':resists,'calculation_steps':steps,'resistance_steps':resistance_steps,'checks':checks})

    return results
