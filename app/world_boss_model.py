"""三界共伐面板与技能伤害估算（使用本地客户端配置表）。"""
import json
import random
import time
from pathlib import Path

ATTRS = ('atk', 'hpMax', 'mpMax', 'phyDef', 'critical', 'hit', 'dodge',
         'toughness', 'lucky', 'guardian', 'reHP', 'reMP')

_TABLES = {}
_CONFIG_DIR = None


def _config_dir():
    global _CONFIG_DIR
    if _CONFIG_DIR is None:
        root = Path(__file__).resolve().parent
        for path in sorted(root.glob('cg_config_out_cg1_*'), reverse=True):
            if (path / 'Skill.json').is_file() and (path / 'Monster.json').is_file():
                _CONFIG_DIR = path
                break
        else:
            raise FileNotFoundError('未找到 cg_config_out_cg1_* 配置目录')
    return _CONFIG_DIR


def _table(name):
    if name not in _TABLES:
        path = _config_dir() / (name + '.json')
        _TABLES[name] = json.loads(path.read_text(encoding='utf-8-sig'))
    return _TABLES[name]


def _split(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    if value in (None, ''):
        return []
    return [x for x in str(value).split(';') if x not in ('', 'None')]


def _numbers(value):
    result = []
    for item in _split(value):
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            result.append(0.0)
    return result


def _by_level(value, level, offset=0):
    """按等级取数组值；offset=1 表示数组索引0对应等级1。"""
    arr = _numbers(value)
    if not arr:
        return 0.0
    index = max(int(level) - offset, 0)
    return arr[min(index, len(arr) - 1)]


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _panel_power(panel):
    power = _table('PowerAttribute').get('1') or {}
    return sum(_num(panel.get(attr)) * _num(power.get(attr)) for attr in ATTRS)


def build_panel(info):
    """合成 p1/p2 完整面板，取合成战力高者；失败返回原始角色属性。"""
    best = None
    for key in ('p1', 'p2'):
        player = info.get(key) or {}
        if not isinstance(player, dict) or not player.get('atk'):
            continue
        try:
            panel = _build_panel(player, info)
        except Exception:
            panel = dict(player)
        panel['_pk'] = key
        panel['_power'] = _panel_power(panel)
        if best is None or panel['_power'] > best['_power']:
            best = panel
    return best


def _build_panel(player, info):
    total = {attr: _num(player.get(attr)) for attr in ATTRS}
    level = int(player.get('level') or 168)
    equipments = [item for item in (player.get('equipments') or {}).values()
                  if isinstance(item, dict)]
    equip_cfg = _table('Equipment')
    fashion_cfg = _table('Fashion')
    fashion_suit = _table('FashionSuit')
    fashion_extra = _table('FashionExtract').get('1') or {}
    basic_att = _numbers(fashion_extra.get('basicAtt'))
    suit_att = _numbers(fashion_extra.get('suitAtt'))
    prop_cfg = _table('Prop')
    extract_cfg = _table('EquExtract')
    fashion_ids = []
    jewel_level = 0

    for item in equipments:
        if item.get('part') == 'pet' or item.get('type') in (1, '1'):
            continue
        is_fashion = item.get('type') == 'fashion'
        item_id = str(item.get('id'))
        item_level = int(item.get('level') or 0)
        if is_fashion:
            # 时装等级每 6 级折算一档成长，已在真实账号战力上校验。
            add_level = item_level % 6
            jewel_level = int(item.get('baoZhuLv') or 0)
            fashion_ids.append(item_id)
        else:
            add_level = item_level
        cfg = equip_cfg.get(item_id) or fashion_cfg.get(item_id) or {}
        for attr in ATTRS:
            value = item.get(attr)
            if not value:
                continue
            base = _num(value)
            total[attr] += base
            growth = _num(cfg.get(attr + 'Add'))
            if growth:
                grown = add_level * growth
                total[attr] += grown
                if is_fashion and 0 <= jewel_level < len(basic_att):
                    total[attr] += round((base + grown) * basic_att[jewel_level])
        inlay = item.get('inlay')
        if isinstance(inlay, dict):
            for gem in inlay.values():
                if isinstance(gem, dict):
                    for attr in ATTRS:
                        if gem.get(attr):
                            total[attr] += _num(gem[attr])
                    continue
                gem_cfg = prop_cfg.get(str(gem))
                if not gem_cfg:
                    continue
                attr = gem_cfg.get('attributeV1')
                value = _num(gem_cfg.get('attributeV2'))
                if attr not in ATTRS or not value:
                    continue
                total[attr] += value
                extract = item.get('extract')
                if isinstance(extract, dict) and extract.get('level'):
                    arr = _numbers((extract_cfg.get(str(cfg.get('equExtractId') or 1)) or {}).get(attr))
                    if arr:
                        index = min(int(extract['level']), len(arr) - 1)
                        total[attr] += value * arr[index]
        recast = item.get('recast')
        if isinstance(recast, dict):
            for attr, value in recast.items():
                if attr in ATTRS and isinstance(value, dict) and value.get('add'):
                    total[attr] += _num(value['add'])
        train = item.get('train')
        if isinstance(train, dict):
            for attr in ATTRS:
                if train.get(attr):
                    total[attr] += _num(train[attr])

    role_cfg = _table('Role').get(str(player.get('charId') or '')) or {}
    for attr, value in role_cfg.items():
        if attr.endswith('Add') and attr[:-3] in ATTRS:
            total[attr[:-3]] += _num(value) * (level - 1)

    for suit in fashion_suit.values():
        if not isinstance(suit, dict):
            continue
        have = sum(1 for item_id in _split(suit.get('relateFashionId'))
                   if item_id in fashion_ids)
        needs = _split(suit.get('fashionNum'))
        attrs = _split(suit.get('attr'))
        values = _split(suit.get('value'))
        for index, need in enumerate(needs):
            if have < int(_num(need)):
                continue
            row_attrs = attrs[index].split(',') if index < len(attrs) else []
            row_values = values[index].split(',') if index < len(values) else []
            for pos, attr in enumerate(row_attrs):
                if attr not in ATTRS:
                    continue
                value = _num(row_values[pos]) if pos < len(row_values) else 0.0
                total[attr] += value
                if 0 <= jewel_level < len(suit_att):
                    total[attr] += round(value * suit_att[jewel_level])

    for item in equipments:
        if item.get('part') == 'wing':
            wing = _table('Wing').get('%s_%s' % (item.get('id'), item.get('level')))
            if wing and wing.get('attributeT') in ATTRS:
                total[wing['attributeT']] += _num(wing.get('attributeV'))
            break

    for group in (player.get('secretSkill') or {}).values():
        if not isinstance(group, dict):
            continue
        for skill in group.values():
            if isinstance(skill, dict) and skill.get('equip') == 1:
                for attr in ATTRS:
                    if skill.get(attr):
                        total[attr] += _num(skill[attr])

    heart_cfg = _table('Heart')
    heart_level_cfg = _table('HeartLev')
    for heart_id, heart_level in (player.get('heart') or {}).items():
        base = heart_cfg.get(str(heart_id)) or {}
        grown = heart_level_cfg.get('%s_%s' % (heart_id, heart_level)) or {}
        if base.get('attributeT') in ATTRS:
            total[base['attributeT']] += _num(grown.get('attributeV'))

    medical_cfg = _table('Medical')
    for medical_id, count in (player.get('medical') or {}).items():
        cfg = medical_cfg.get(str(medical_id)) or {}
        if cfg.get('attributeT1') in ATTRS:
            total[cfg['attributeT1']] += _num(cfg.get('attributeV1')) * _num(count)

    for flag in (info.get('formation') or {}).values():
        if isinstance(flag, dict):
            for attr in ATTRS:
                if flag.get(attr):
                    total[attr] += _num(flag[attr])

    panel = {attr: round(total.get(attr, 0.0)) for attr in ATTRS}
    panel['level'] = level
    panel['charId'] = player.get('charId')
    return panel


class WorldBossModel:
    """根据面板、技能栏及本地配置估算伤害，不等同于客户端战斗录像。"""

    REPORT_INTERVAL = 2.0

    def __init__(self, info, boss_id, boss=None, cd_field='worldBossCD'):
        self.info = info
        self.boss_id = int(boss_id)
        self.cd_field = cd_field
        self.panel = build_panel(info)
        if not self.panel:
            raise ValueError('角色面板缺少 atk')
        if boss:
            self.boss_name = boss.get('name') or str(boss_id)
            self.boss_level = int(boss.get('level') or 0)
            self.boss_hp_max = _num(boss.get('hpMax'))
            self.boss_def = _num(boss.get('phyDef'))
            self.boss_atk = _num(boss.get('atk'))
            self.high_power = int(_num(boss.get('highPower')))
            self.boss_toughness = _num(boss.get('toughness'))
            self.boss_guardian = _num(boss.get('guardian'))
        else:
            world = _table('WorldBoss').get(str(self.boss_id)) or {}
            monster = _table('Monster').get(str(self.boss_id)) or {}
            self.boss_name = world.get('bossName') or monster.get('name') or str(boss_id)
            self.boss_level = int(world.get('bossLevel') or monster.get('level') or 0)
            self.boss_hp_max = _num(monster.get('hpMax'))
            self.boss_def = _num(monster.get('phyDef'))
            self.boss_atk = _num(monster.get('atk'))
            self.high_power = int(_num(world.get('highPower')))
            self.boss_toughness = _num(monster.get('toughness'))
            self.boss_guardian = _num(monster.get('guardian'))
        self.player = info.get(self.panel.get('_pk') or 'p1') or {}
        self.levels = {}
        for skill_id, level in (self.player.get('skill') or {}).items():
            try:
                self.levels[str(skill_id)] = int(level)
            except (TypeError, ValueError):
                pass
        self.mp_max = _num(self.panel.get('mpMax'))
        self.re_mp = _num(self.panel.get('reMP')) or (self.mp_max * 0.01 if self.mp_max else 0)
        self.mp = self.mp_max
        self.ready = {}
        self.normal_next = 0.0
        self.action_ready = 0.0
        self.raw_skills = _table('Skill')
        self.bar = self._skill_bar()
        self.normal_id = self._normal_id()
        self.skills = {}
        for skill_id in list(self.bar) + [self.normal_id]:
            self._add_skill(skill_id)
        self.crit_rate, self.crit_mult = self._crit_values()
        self._alive_seconds = self._calc_alive_seconds()

    def _skill_bar(self):
        store = (self.info.get('clientStore') or {}).get(
            str(self.info.get('_id') or '') + '-setKeyboard-' +
            ('1' if self.panel.get('_pk') == 'p2' else '0')) or {}
        bar = []
        for index in range(1, 6):
            value = store.get('skill%d' % index)
            if value:
                try:
                    bar.append(int(value))
                except (TypeError, ValueError):
                    pass
        return bar

    def _normal_id(self):
        for skill_id in self.bar:
            prefix = str(skill_id)[:4]
            if prefix.isdigit() and len(prefix) == 4:
                return int(prefix + '010')
        return 1101010

    def _level(self, skill_id):
        return max(1, self.levels.get(str(skill_id), 1))

    def _segments(self, raw):
        param = raw.get('param') or {}
        if isinstance(param, str):
            try:
                param = json.loads(param)
            except ValueError:
                param = {}
        segments = param.get('s') if isinstance(param, dict) else None
        if not isinstance(segments, list):
            return 1, [], 0.3
        hits = 0
        subs = []
        stiff = 0.0
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            count = int(_num(segment.get('atkMax')))
            if count <= 0 or segment.get('type') not in (1, 2, 5):
                continue
            stiff = max(stiff, _num(segment.get('stiff')))
            sub_id = segment.get('skillid')
            if sub_id and int(_num(sub_id)) > 0:
                subs.append((int(_num(sub_id)), count))
            else:
                hits += count
        return hits or 1, subs, stiff or 0.3

    def _skill_values(self, skill_id, level):
        raw = self.raw_skills.get(str(skill_id)) or {}
        coefficient = _num(raw.get('skillDefault'))
        add = _num(raw.get('skillAdd'))
        add_max = int(_num(raw.get('skillAddLevelMax')))
        effective = max(level - 1, 0)
        if add_max > 0:
            effective = min(effective, add_max)
        coefficient += add * effective
        fixed = _by_level(raw.get('skillCountAdd'), level, 1)
        return raw, coefficient, fixed

    def _add_skill(self, skill_id):
        skill_id = int(skill_id)
        if skill_id in self.skills:
            return
        level = self._level(skill_id)
        raw, coefficient, fixed = self._skill_values(skill_id, level)
        hits, subs, stiff = self._segments(raw)
        if skill_id == self.normal_id and coefficient <= 0 and fixed <= 0:
            coefficient = 1.0
        damage = coefficient > 0 or fixed > 0
        cd = _by_level(raw.get(self.cd_field), level)
        if cd <= 0 and self.cd_field != 'worldBossCD':
            cd = _by_level(raw.get('worldBossCD'), level)
        if skill_id == self.normal_id and cd <= 0:
            cd = 1.2
        if cd <= 0:
            cd = 1.5
        cost = 0 if skill_id == self.normal_id else _by_level(raw.get('consumeMP'), level)
        sub_data = []
        for sub_id, count in subs:
            sub_raw, sub_coef, sub_fixed = self._skill_values(sub_id, level)
            if sub_coef > 0 or sub_fixed > 0:
                sub_data.append((sub_raw.get('name') or str(sub_id), sub_coef, sub_fixed, count))
        self.skills[skill_id] = {
            'id': skill_id,
            'name': raw.get('name') or str(skill_id),
            'level': level,
            'coef': coefficient if coefficient > 0 else 0.0,
            'fixed': fixed,
            'hits': hits,
            'subs': sub_data,
            'cd': cd,
            'mp': cost,
            'stiff': stiff,
            'damage': damage,
        }

    def _crit_values(self):
        exp = _table('EXP')
        player_level = int(self.player.get('level') or self.panel.get('level') or 168)
        player_exp = exp.get(str(player_level)) or {}
        boss_exp = exp.get(str(self.boss_level)) or {}
        crit = _num(self.panel.get('critical'))
        lucky = _num(self.panel.get('lucky'))
        toughness = _num(self.panel.get('toughness'))
        guardian = _num(self.panel.get('guardian'))
        crit_max = _num(boss_exp.get('criticalMax'))
        lucky_max = _num(boss_exp.get('luckyMax'))
        guardian_max = _num(player_exp.get('guardianMax'))
        toughness_max = _num(player_exp.get('toughnessMax'))
        rate = 0.0
        if crit_max > 0 and crit > 0:
            rate = crit / crit_max
        if toughness_max > 0 and self.boss_toughness > 0:
            rate -= self.boss_toughness / toughness_max
        rate = max(0.0, min(1.0, rate))
        bonus = 0.0
        if lucky_max > 0:
            bonus += lucky / lucky_max
        if guardian_max > 0 and self.boss_guardian > 0:
            bonus -= self.boss_guardian / guardian_max
        bonus = max(0.0, min(2.0, 1.0 + bonus))
        return rate, 1.0 + bonus

    def _calc_alive_seconds(self):
        hp_max = _num(self.panel.get('hpMax'))
        taken = max(self.boss_atk - _num(self.panel.get('phyDef')) - _num(self.panel.get('reHP')), 50.0)
        return max(6.0, hp_max / taken) * random.uniform(0.7, 1.3)

    def alive_seconds(self):
        return self._alive_seconds

    def reset_after_revive(self):
        self.mp = self.mp_max
        # Callers may restart the simulation clock after revival.
        self.ready.clear()
        self.normal_next = 0.0
        self.action_ready = 0.0

    def _net_attack(self):
        return max(_num(self.panel.get('atk')) - self.boss_def, 1.0)

    def estimate(self, skill_id):
        skill = self.skills.get(int(skill_id))
        if not skill or not skill['damage']:
            return 0.0
        net = self._net_attack()
        total = skill['hits'] * (skill['fixed'] + net * skill['coef'])
        for _name, coef, fixed, count in skill['subs']:
            total += count * (fixed + net * coef)
        return max(total, 1.0) * (1 + self.crit_rate * (self.crit_mult - 1))

    def choose(self, now=None):
        now = time.monotonic() if now is None else now
        if now < self.action_ready:
            return None
        best_id = None
        best_damage = 0.0
        for skill_id in self.bar:
            if now < self.ready.get(skill_id, 0):
                continue
            skill = self.skills.get(skill_id)
            if not skill or not skill['damage']:
                continue
            if self.mp < skill['mp']:
                continue
            damage = self.estimate(skill_id)
            if damage > best_damage:
                best_damage = damage
                best_id = skill_id
        if best_id is None and now >= self.normal_next:
            best_id = self.normal_id
        return best_id

    def cast(self, skill_id, now=None):
        now = time.monotonic() if now is None else now
        skill = self.skills[int(skill_id)]
        net = self._net_attack()
        total = 0.0
        for _ in range(skill['hits']):
            total += skill['fixed'] + net * random.uniform(0.95, 1.05) * skill['coef']
        for _name, coef, fixed, count in skill['subs']:
            for _ in range(count):
                total += fixed + net * random.uniform(0.95, 1.05) * coef
        if random.random() < self.crit_rate:
            total *= self.crit_mult
        damage = max(int(total), 1)
        if skill['id'] == self.normal_id:
            self.normal_next = now + skill['cd'] * random.uniform(0.95, 1.05)
            gap = skill['cd']
        else:
            self.ready[skill['id']] = now + skill['cd'] * random.uniform(0.95, 1.05)
            gap = max(0.2, skill['stiff'] + random.uniform(0.1, 0.4))
            if skill['mp'] > 0:
                self.mp = max(0.0, self.mp - skill['mp'])
        if self.mp_max > 0:
            self.mp = min(self.mp_max, self.mp + self.re_mp * gap)
        self.action_ready = now + gap
        return damage, gap

    def skill_lines(self):
        lines = []
        for skill_id in list(self.bar) + [self.normal_id]:
            skill = self.skills.get(skill_id)
            if not skill:
                continue
            subs = ''.join('+%s×%s' % (name, count)
                           for name, _coef, _fixed, count in skill['subs'])
            lines.append('%s %s lv%s %s段%s 系数%.3f 固伤%.0f CD%.1fs 耗蓝%.0f%s' % (
                skill['id'], skill['name'], skill['level'], skill['hits'], subs,
                skill['coef'], skill['fixed'], skill['cd'], skill['mp'],
                '' if skill['damage'] else '（无伤害）'))
        return lines

    def summary(self):
        return ('%s lv%s 防御%s；面板%s 攻击%.0f 血量%.0f 暴击率%.1f%% 爆伤%.2f；'
                '技能栏%s；普攻%s' % (
                    self.boss_name, self.boss_level, int(self.boss_def),
                    self.panel.get('_pk'), _num(self.panel.get('atk')),
                    _num(self.panel.get('hpMax')), self.crit_rate * 100, self.crit_mult,
                    self.bar, self.normal_id))
