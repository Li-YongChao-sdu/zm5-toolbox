"""将擂台回放 JSON 转换为研究室可修改种类的标准配队方案（无联网）。"""
import argparse
import copy
import json
import re
from pathlib import Path
from arena_build_stats import calculate

HERE = Path(__file__).resolve().parent
LAB = HERE.parent / 'new-chat' / 'pet_lab_v4750'
if not (LAB/'ui'/'catalog.mjs').is_file():
    LAB = HERE/'附件'/'宠物对战研究室'
TABLES = ('Equipment', 'Prop', 'PetElf', 'PetElfAtt', 'EquInject', 'PetPerks', 'Pet', 'Common', 'PetCharacter')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def catalog(path):
    text = Path(path).read_text(encoding='utf-8-sig')
    match = re.search(r'export const CATALOG\s*=\s*', text)
    if not match:
        raise ValueError('目录缺少 CATALOG')
    return json.JSONDecoder().raw_decode(text[match.end():])[0]

def convert(obj, cat, config_dir):
    if obj.get('format') == 'zm5-pet-build-v1':
        raise ValueError('这个文件已经是标准配队方案，无需转换')
    if obj.get('format') not in (None, 'zm5-local-replay-input-v1', 'zm5-pet-client-input-v1'):
        raise ValueError('不是支持的擂台/研究室对战输入格式')
    response = copy.deepcopy(obj.get('response', obj))
    users = [json.loads(u) if isinstance(u, str) else u for u in response['data']]
    if len(users) != 2 or any(len(u.get('pets', [])) != 3 for u in users):
        raise ValueError('需要双方各三只宠物的完整快照')
    seed = response.get('message', {}).get('randomSeed', obj.get('metadata', {}).get('battle', {}).get('rnd'))
    if isinstance(seed, bool) or not isinstance(seed, int) or not -2147483648 <= seed <= 2147483647:
        raise ValueError('没有有效种子，不能用虚构种子替换')
    configs = {n: read(Path(config_dir) / (n + '.json')) for n in TABLES}
    species = {int(p['id']): p for p in cat['pets']}
    for user in users:
        for p in user['pets']:
            pc = configs['Pet'][str(p['id'])]
            if int(pc['type']) == 2:
                pid = pc.get('switchId', -1)
                p['id'] = pid if int(pid) >= 0 else pc['hetiId']
            if int(p['id']) not in species:
                raise ValueError('配队目录不支持宠物 ' + str(p['id']))
    panels = obj.get('finalPanels')
    rows = {} if panels else {r['entityId']: r for r in calculate({'data': users}, configs)}
    teams = []
    for user in users:
        team = []
        for p in user['pets']:
            sp = species[int(p['id'])]
            if panels:
                stats = copy.deepcopy(panels[p['entityId']])
            else:
                row = rows[p['entityId']]
                stats = dict(row['battle_initial_10'], **row['resistances'])
                # 配队格式输入入场前面板，客户端自行乘擂台生命倍率。
                common = [v for v in configs['Common'].values() if 'petpkHpMaxQualificationIndex' in v]
                if len(common) != 1 or float(common[0]['petpkHpMaxQualificationIndex']) <= 0:
                    raise ValueError('无法确认擂台生命倍率')
                stats['hpMax'] /= float(common[0]['petpkHpMaxQualificationIndex'])
            skills = {}
            for action, ac in sp['actions'].items():
                sid = str(ac['id'])
                sk = p.get('skill', {})
                ao = p.get('aoyiSkill', {})
                level = (ao.get('pet', {}).get(sid) if action == 'aoyiSkill' else sk.get('pet', {}).get(sid))
                level = level or sk.get(sid) or ao.get(sid)
                # 普攻不在快照技能栏；沿用研究室标准的20级，可在配队页调整。
                if not level and action.startswith('attack'):
                    level = 20
                if not level:
                    raise ValueError(f"{p.get('name')} 缺少技能 {action}/{sid} 等级，停止转换")
                skills[action] = int(level)
            elf = p.get('equipments', {}).get('petElf') or {}
            ec = configs['PetElf'].get(str(elf.get('id'))) if elf else None
            # 多种旧真灵共用wearELfType=-1；必须按名称匹配唯一目录项。
            matches = [e for e in cat['spirits'] if ec and e['name'] == ec['name']]
            if ec and len(matches) != 1:
                raise ValueError('真灵目录缺失或重名：' + str(ec['name']))
            elf_type = int(matches[0]['id']) if ec else None
            elf_level = int(str(ec['skills']).split(',')[0][-1]) if ec and ec.get('skills') else 1
            team.append(dict(pet_id=int(p['id']), level=int(p['level']), stats=stats,
                             skill_levels=skills, petelf_type=elf_type, petelf_absent=ec is None,
                             petelf_skill_level=elf_level, label=str(p.get('nickName') or p.get('name') or sp['name'])))
        teams.append(team)
    return dict(format='zm5-pet-build-v1', catalogVersion=cat['version'],
                orderMode='runtime' if response.get('setsit') is True or obj.get('experiment', {}).get('orderBasis') == 'battle_runtime' else 'formation',
                seed=seed, names=[str(u.get('name') or f'阵容{i+1}') for i,u in enumerate(users)], teams=teams)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*', type=Path)
    parser.add_argument('--config', type=Path, help='指定快照对应的反编译配置目录；默认按快照cg版本查找')
    parser.add_argument('--catalog', type=Path, default=LAB / 'ui' / 'catalog.mjs')
    args = parser.parse_args()
    if not args.files:
        from tkinter import Tk, filedialog
        window = Tk(); window.withdraw()
        args.files = list(map(Path, filedialog.askopenfilenames(title='选择擂台导出 JSON（可多选）', filetypes=[('JSON', '*.json')])))
        window.destroy()
    cat = catalog(args.catalog)
    failed = 0
    for source in args.files:
        try:
            obj = read(source)
            config = args.config
            if config is None:
                cg = obj.get('response', {}).get('message', {}).get('cg') or obj.get('metadata', {}).get('battle', {}).get('cg', '')
                name = 'cg_config_out_' + Path(cg).stem
                candidates = [HERE / name, Path.home() / 'Downloads' / name]
                config = next((p for p in candidates if (p / 'Pet.json').is_file()), None)
                if config is None:
                    if obj.get('finalPanels'):
                        config = HERE / 'cg_config_out_cg1_20261008_1'
                    else:
                        raise ValueError(f'找不到快照配置 {cg}，请用 --config 指定对应目录，避免版本混算')
            result = convert(obj, cat, config)
            target = source.with_name(source.stem + '_标准配队.json')
            if target.exists():
                raise FileExistsError('目标已存在，请改名或移走：' + str(target))
            target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            print('已生成：' + str(target))
        except Exception as exc:
            failed += 1
            print(f'转换失败：{source.name}：{exc}')
    if failed:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
