#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local PVP battle simulator for 造梦西游5 (client-side model).

Reproduces:
  * PVE stats from onCreateOnlineCopy/sceneInfo (equipment/formation/halo/secret skill)
  * PVP correction (GoToBattleCmd: checkCorr/checkMax + hpMax qualification)
  * Damage per hit (BattleModelManager.calDamage/calPhysicalDamage/calBaoJiDamage)
  * Hit/crit rates (calHitRate/calBaoJiRate) from Exp.json
  * Hit schedule from Skill.json param (shootFrame/shootTime/atkMax/atkInterval)
  * Opponent position/movement from key frames (1-D approximation)
  * HP timeline and the moment HP reaches 0

Usage:
  python pvp_sim.py --capture <capture.jsonl> --me 0 --p0-x 150 --p1-x 1350
  python pvp_sim.py --report <report.json> --me 0
  python pvp_sim.py --capture ... --hit-mode all          # upper bound
  python pvp_sim.py --capture ... --hit-mode fraction --hit-fraction 0.3
"""
import argparse, ast, collections, heapq, json, math, os, random, sys

FPS = 30.0
ATTRS = ('hpMax','mpMax','atk','phyDef','hit','dodge','critical','toughness','lucky','guardian','reHP','reMP')
# ResistType.Types index -> equipment/UserVO field
RESIST_ATTRS = ('lightResist','darkResist','waterResist','fireResist','woodResist','soilResist','windResist','rayResist')
RESIST_BY_TYPE = {i + 1: a for i, a in enumerate(RESIST_ATTRS)}
TABLE = {'10':'Prop','11':'Equipment','12':'Fashion','13':'Magicweapon','14':'Title','15':'Wing','16':'Feather',
         '17':'Pet','18':'Card','19':'Fairy','20':'MonsterCard','21':'Rune','22':'FormationFlag','24':'PetElf','29':'Emoji'}

DEFAULT_CFG = r'D:\li xicheng\.trae-cn\worktrees\2026-09-18\new-chat-1\cg_config_out_cg1_20261026_1'
DEFAULT_KEYS = {'attack':74,'jump':75,'walkUp':87,'walkLeft':65,'walkDown':83,'walkRight':68,
                'skill1':89,'skill2':85,'skill3':73,'skill4':79,'skill5':76,'magicWeapon':72}

def num(v):
    try: return float(v)
    except Exception: return 0.0

def clamp(v, lo, hi): return max(lo, min(hi, v))

class Config:
    def __init__(self, cfg_dir):
        self.dir = cfg_dir
        self._cache = {}
    def get(self, name):
        if name not in self._cache:
            p = os.path.join(self.dir, name + '.json')
            self._cache[name] = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
        return self._cache[name]

def cfg_vo(cfg, item):
    if not isinstance(item, dict): return {}
    iid = item.get('id')
    if iid is None: return {}
    tn = TABLE.get(str(iid)[:2], '')
    tbl = cfg.get(tn)
    key = str(iid)
    if key in tbl: return tbl[key]
    if tn == 'Wing' and item.get('level'):
        k = f'{key}_{item["level"]}'
        if k in tbl: return tbl[k]
    return {}

def obj_of(v):
    if isinstance(v, dict): return v
    if isinstance(v, str) and v.strip().startswith('{'):
        try: return json.loads(v)
        except Exception:
            try: return ast.literal_eval(v)
            except Exception: return {}
    return {}

def _add_fields(obj, vo, part, level, baozhu, out, keys):
    for a in keys:
        raw = num(obj.get(a)); add = 0.0
        af = a + 'Add'
        if af in vo and part != 'amulet':
            lv = (level % 6) if str(part).startswith('fashion') else level
            add = num(vo.get(af)) * lv
        val = raw + add
        if baozhu and str(part).startswith('fashion'):
            val += round(val * baozhu)
        out[a] += val


def add_item(cfg, obj, out, baozhu=0.0, extract_cfg=None, res=None):
    """Reproduce ItemVo.getBasicAndLevelAdd + inlay/recast recursion."""
    if not isinstance(obj, dict): return
    if res is None: res = {}
    vo = cfg_vo(cfg, obj); part = obj.get('part'); level = int(num(obj.get('level')))
    if str(part) in ('pet', 'fairy'):  # Equipment.checkPartChangeAtt excludes pet/fairy
        return
    _add_fields(obj, vo, part, level, baozhu, out, ATTRS)
    _add_fields(obj, vo, part, level, baozhu, res, RESIST_ATTRS)
    inlay = obj.get('inlay')
    if isinstance(inlay, dict):
        ext = obj_of(obj.get('extract'))
        elv = int(num(ext.get('level'))) if ext else 0
        ev = extract_cfg.get(str(vo.get('equExtractId'))) if vo else None
        for v in inlay.values():
            if isinstance(v, dict):
                cv = cfg_vo(cfg, v)
                for keys, dst in ((ATTRS, out), (RESIST_ATTRS, res)):
                    _add_fields(v, cv, v.get('part'), int(num(v.get('level'))), 0.0, dst, keys)
                for a in ATTRS:
                    if ev and a in ev:
                        raw = num(v.get(a)); add = 0.0
                        af = a + 'Add'
                        if af in cv and v.get('part') != 'amulet':
                            add = num(cv.get(af)) * int(num(v.get('level')))
                        val = raw + add
                        arr = str(ev[a]).split(';')
                        rate = num(arr[elv]) if 0 <= elv < len(arr) else 0.0
                        out[a] += round(rate * val)
            else:
                pv = cfg.get('Prop').get(str(v)) or {}
                a = pv.get('attributeV1'); val = num(pv.get('attributeV2'))
                if a in ATTRS:
                    out[a] += val
                    if ev and a in ev:
                        arr = str(ev[a]).split(';')
                        rate = num(arr[elv]) if 0 <= elv < len(arr) else 0.0
                        out[a] += round(rate * val)
                elif a in RESIST_ATTRS:
                    res[a] += val
    recast = obj_of(obj.get('recast'))
    if recast:
        for a, rv in recast.items():
            val = num(rv.get('add') if isinstance(rv, dict) else rv)
            if a in ATTRS:
                out[a] += val
            elif a in RESIST_ATTRS:
                res[a] += val

def pve_stats(cfg, pl):
    t = {a: 0.0 for a in ATTRS}
    res = {a: 0.0 for a in RESIST_ATTRS}
    # fashion treasure (baoZhu) multiplier
    fe = cfg.get('FashionExtract'); rate = 0.0
    blv = int(num((pl.get('baoZhu') or {}).get('lv')))
    for block in fe.values():
        if not isinstance(block, dict): continue
        basic = block.get('basicAtt') or block.get('basicAtten')
        if not basic: continue
        if isinstance(basic, str):
            arr = basic.split(';'); rate = num(arr[blv]) if 0 <= blv < len(arr) else 0.0
        elif isinstance(basic, dict):
            rate = num(basic.get(str(blv)))
        break
    for _, it in (pl.get('equipments') or {}).items():
        add_item(cfg, it, t, rate, cfg.get('EquExtract'), res)
    for _, fv in (pl.get('formation') or {}).items():
        if isinstance(fv, dict):
            for a in ATTRS: t[a] += num(fv.get(a))
            for a in RESIST_ATTRS: res[a] += num(fv.get(a))
    for _, hv in ((pl.get('halo') or {}).get('bag') or {}).items():
        if isinstance(hv, dict):
            for a in ATTRS: t[a] += num(hv.get(a))
            for a in RESIST_ATTRS: res[a] += num(hv.get(a))
    for _, sk in (pl.get('secretSkill') or {}).items():
        if isinstance(sk, dict):
            for _, it in sk.items():
                if isinstance(it, dict) and it.get('equip') == 1:
                    for a in ATTRS: t[a] += num(it.get(a))
                    for a in RESIST_ATTRS: res[a] += num(it.get(a))
    out = {}
    for a in ATTRS:
        out[a] = num(pl.get(a)) + t[a]
    for a in RESIST_ATTRS:
        out[a] = num(pl.get(a)) + res[a]
    role = cfg.get('Role').get(str(pl.get('charId'))) or {}
    lv = int(num(pl.get('level')))
    for a in ('hpMax','mpMax','atk','phyDef'):
        out[a] += (lv - 1) * num(role.get(a + 'Add'))
    out['fightPower'] = num(pl.get('fightPower')); out['level'] = lv; out['charId'] = int(num(pl.get('charId')))
    return out

RAW_CHAR_IDS = {b + o: 2000 + o for b in (2000, 2010, 2020, 2080, 2090) for o in range(1, 9)}

def raw_char_id(cid):
    # UserModelManager.getRawCharId: 2001-2008 / 2011-2018 / 2021-2028 / 2081-2088 / 2091-2098
    # collapse by last digit; anything else falls back to 2001
    return RAW_CHAR_IDS.get(cid, 2001)

def pvp_final(cfg, p0, p1, verbose=False):
    ps = [pve_stats(cfg, p0), pve_stats(cfg, p1)]
    fps = [x['fightPower'] for x in ps]
    maxfp, minfp = max(fps), min(fps)
    strong = 0 if fps[0] >= fps[1] else 1; weak = 1 - strong
    common = cfg.get('Common')['1']
    ratio = minfp / maxfp if maxfp else 1
    S = P = 1.0
    corr_on = ratio <= num(common['PVPcorrection'])
    if corr_on:
        w = ps[weak]
        wts = cfg.get('PvpPowerAttribute')['3']
        vals = sorted([w[a] * num(wts[a]) for a in ATTRS], reverse=True)
        total2 = [sum(vals[:8]), sum(vals[8:])]
        B = total2[0] / total2[1] if total2[1] else 999
        ccfg = {'C':5.4,'V':0.09,'W':0.09,'F':9}
        pc = common.get('PVPcorrectionConfig')
        if isinstance(pc, str) and pc.strip():
            for kv in pc.split(','):
                if ':' in kv:
                    k, v = kv.split(':'); ccfg[k.strip()] = num(v)
        N = num(common['PVPcorrection'])
        if B > ccfg['C']:
            j = clamp(ccfg['V'] * (B - ccfg['C']) / ccfg['F'], 0, ccfg['V'])
            N -= j
            S = N / num(common['PVPcorrection'])
            k = clamp(ccfg['W'] * (B - ccfg['C']) / ccfg['F'], 0, ccfg['W'])
            P = (num(common['PVPcorrection']) - k) / num(common['PVPcorrection'])
        base = cfg.get('PvpPowerAttribute')['1']
        weak_pl = p0 if weak == 0 else p1
        rolecfg = cfg.get('PvpPowerAttribute').get(str(raw_char_id(int(num(weak_pl.get('charId')))) - 2000 + 10)) or {}
        A = maxfp / 12
        def ratio_for(a):
            return S if a in ('hpMax','mpMax','atk','phyDef','reHP','reMP') else (P if a in ('hit','dodge','critical','toughness','lucky','guardian') else 1)
        excess = 0.0
        for a in ATTRS:
            mx = A / num(base[a]) * num(rolecfg.get(a)) * ratio_for(a)
            if w[a] > mx: excess += (w[a] - mx) * num(wts[a])
        oldw = {a: w[a] for a in ATTRS}          # checkCorr 前的快照，checkMax 的下限
        for a in ATTRS:
            mx = A / num(base[a]) * num(rolecfg.get(a)) * ratio_for(a)
            if w[a] >= mx: continue
            val = w[a] * ((maxfp * N - excess) / (minfp - excess))   # checkCorr: maxFP*PVPcorrection(N)
            w[a] = max(min(val, mx), w[a])
        capcfg = cfg.get('PvpPowerAttribute')['31']
        for a in ATTRS:
            cap = max(num(capcfg[a]) * ps[strong][a], oldw[a])
            if w[a] > cap: w[a] = cap
    amp = num(common['pkBaseHpMaxQualificationIndex']) + num(common['pkLvHpMaxQualificationIndex']) * ps[strong]['level']
    for i in range(2):
        ps[i]['hpMax'] = round(ps[i]['hpMax'] * amp)
        ps[i]['mpMax'] = round(ps[i]['mpMax'] * num(common['PVPmpMaxQualificationIndex']))
        ps[i]['allhpMax'] = ps[i]['hpMax']
        ps[i]['allatk'] = ps[i]['atk']; ps[i]['allphyDef'] = ps[i]['phyDef']
        ps[i]['allhit'] = ps[i]['hit']; ps[i]['alldodge'] = ps[i]['dodge']
        ps[i]['allcritical'] = ps[i]['critical']; ps[i]['alltoughness'] = ps[i]['toughness']
        ps[i]['alllucky'] = ps[i]['lucky']; ps[i]['allguardian'] = ps[i]['guardian']
        for a in RESIST_ATTRS:
            ps[i]['all' + a] = ps[i][a]
    ps[weak]['level'] = ps[strong]['level']  # GoToBattleCmd: weak player level := strong level
    if verbose:
        print(f'[stats] fightPower p0={fps[0]:.0f} p1={fps[1]:.0f} strong={strong} ratio={ratio:.4f} '
              f'correction={corr_on} S={S:.4f} P={P:.4f} amp={amp:.4f}')
    return ps, strong, weak

# ---------------- damage ----------------
class DamageModel:
    def __init__(self, cfg, ps, rng):
        self.cfg = cfg; self.ps = ps; self.rng = rng
        self.exp = cfg.get('Exp')
        self.skill_tbl = cfg.get('Skill')
    def e(self, level): return self.exp.get(str(int(level))) or {}
    def cheat(self, u, sid, attr):
        return num(((u.get('cheat') or {}).get(str(sid)) or {}).get(attr))
    def hit_rate(self, a, d, sid=None):
        # calHitRate: (allhit + hit*cheat("hit"))/Exp[d].hitAttr - alldodge/Exp[a].dodgeAttr
        ed = self.e(d['level']); ea = self.e(a['level'])
        extra = self.cheat(a, sid, 'hit') * num(a.get('hit'))
        diff = (a['allhit'] + extra) / num(ed.get('hitAttribute')) - d['alldodge'] / num(ea.get('dodgeAttribute'))
        return clamp(1 + diff / (abs(diff) + 1), 0, 1)
    def crit_rate(self, a, d, sid=None):
        # calBaoJiRate: (allcritical + (critical+Exp[a].criticalMax*2)*cheat("critical"))/Exp[d].criticalMax - ...
        ed = self.e(d['level']); ea = self.e(a['level'])
        extra = (num(a.get('critical')) + num(ea.get('criticalMax')) * 2) * self.cheat(a, sid, 'critical')
        r = (a['allcritical'] + extra) / num(ed.get('criticalMax')) - d['alltoughness'] / num(ea.get('toughnessMax'))
        return clamp(r, 0, 1)
    def crit_mult(self, a, d, sid=None):
        # BattleModelManager.calBaoJiDamage:
        #   luckyMax  -> Exp[defender.level]
        #   guardianMax -> Exp[attacker.level]
        ed = self.e(d['level']); ea = self.e(a['level'])
        extra = (num(a.get('lucky')) + num(ea.get('luckyMax')) * 2) * self.cheat(a, sid, 'lucky')
        r = 1 + (a['alllucky'] + extra) / num(ed.get('luckyMax')) - d['allguardian'] / num(ea.get('guardianMax'))
        return 1 + clamp(r, 0, 2)
    def skill_info(self, sid):
        return self.skill_tbl.get(str(sid)) or {}
    def resist_of(self, d, sid):
        """BattleModelManager.calDamage L646-667: element resist -> damage multiplier offset."""
        t = int(num(self.skill_info(sid).get('type')))
        if t <= 0: return 0.0
        r = num(d.get('all' + RESIST_BY_TYPE.get(t, '')))
        if r > 0: return r / (r + 100)
        if r < 0: return r / 100
        return 0.0
    def physical(self, a, d, sid, level, buff_add=0, rnd=None):
        sc = self.skill_info(sid)
        if not sc: return 0, 0
        sdef = num(sc.get('skillDefault'))
        sadd = num(sc.get('skillAdd'))
        smax = num(sc.get('skillAddLevelMax')) or 0
        if str(sc.get('skillType')) == '3': sadd = 0
        lv = level - 1
        if lv > smax > 0: lv = smax
        mult = sdef + sadd * (lv + buff_add)
        if mult == 0: mult = 1.0
        arr = str(sc.get('skillCountAdd') or '').split(';')
        lv2 = max(1, level) - 1
        cadd = num(arr[min(lv2, len(arr) - 1)]) if arr and arr[0] else 0
        base = max(a['allatk'] + self.cheat(a, sid, 'atk') * num(a.get('atk')) - d['allphyDef'], 1)
        r = 0.95 + 0.1 * (self.rng.random() if rnd is None else rnd)
        return base * r * mult + cadd, mult
    def cal_damage(self, a, d, sid, level, rnd=None, crit=False, ratio_add=0.0, combo=0):
        """calDamage outer multipliers: combo -> resist -> skillDefaultRatio -> 狂血."""
        base, _ = self.physical(a, d, sid, level, rnd=rnd)
        if crit: base = int(base * self.crit_mult(a, d, sid))
        if int(num(a.get('passive'))) == 1303110 and combo > 0:
            base *= 1 + self.combo_bonus(combo)
        sc = self.skill_info(sid)
        dmg = int(base * (1 - self.resist_of(d, sid)))
        ratio = num(sc.get('skillDefaultRatio')) + ratio_add
        if ratio: dmg *= 1 + ratio
        add, _crit_add = self.blood_add(a)
        if add: dmg *= 1 + add
        return max(1, int(dmg))

    @staticmethod
    def combo_bonus(n):
        """1303110 连击: (sqrt(n*25) - (25-n)/10)/100, cap 0.25."""
        if n >= 25: return 0.25
        return clamp((math.sqrt(n * 25) - (25 - n) / 10) / 100, 0, 0.25)

    def blood_add(self, a):
        """1301110 狂血: totalLoastHpPercent -> (伤害加成, 暴击率加成)。

        我方模型不模拟对手掉血，lost_hp_pct 恒为 0（满血），
        即 damageAdd=b=5%，暴击加成=z=5%。
        """
        if int(num(a.get('passive'))) != 1301110:
            return 0.0, 0.0
        c = obj_of(self.skill_info(1301110).get('custom')).get('s') or {}
        lost = a.get('lost_hp_pct', 0.0)
        hp_ratio = max(0.0, 1.0 - lost)
        add = min(lost / num(c.get('c')) * num(c.get('n')), num(c.get('n')))
        add = add * hp_ratio / (hp_ratio + num(c.get('a'))) + num(c.get('b'))
        crit = clamp(num(c.get('k')) * lost / (num(c.get('y')) + lost) + num(c.get('z')),
                     num(c.get('z')), num(c.get('MAX')))
        return add, crit

COMBO_NAMES = ('attack1', 'attack2', 'attack3', 'attack4', 'attack5')


def skill_param(cfg, sid):
    sc = cfg.get('Skill').get(str(sid)) or {}
    prm = sc.get('param')
    if isinstance(prm, dict):
        return prm
    try:
        return json.loads(prm or '{}')
    except Exception:
        return {}


def skill_schedule(cfg, sid):
    """返回 [(delay_sec, hit_sid, n_hits)]。

    只收 atkMax>0 的实体（很多实体 hasDamage 为 None）；
    带 skillid 的实体改用子技能的倍率（如 1101080 的 1101081）。
    """
    sc = cfg.get('Skill').get(str(sid))
    if not sc: return []
    out = []
    for e in (skill_param(cfg, sid).get('s') or []):
        if e.get('hasDamage') is False: continue
        n = int(num(e.get('atkMax')))
        if n <= 0: continue
        sub = int(num(e.get('skillid')))
        hit_sid = str(sub) if sub > 0 and cfg.get('Skill').get(str(sub)) else str(sid)
        delay = num(e.get('shootFrame')) / FPS + num(e.get('shootTime'))
        interval = num(e.get('atkInterval'))
        if interval <= 0 and n > 1: interval = 0.1
        out.append((delay, hit_sid, n, interval))
    if not out:
        n = int(num(sc.get('atkMax')) or 1)
        interval = num(sc.get('atkInterval')) or 0.1
        out.append((0.0, str(sid), max(1, n), interval))
    return out


def skill_anim_len(cfg, sid, tail=0.0):
    """技能动作时长估计：所有实体 shootFrame 与最后一次伤害命中的较大者。"""
    sc = cfg.get('Skill').get(str(sid)) or {}
    last_ent = 0.0
    for e in (skill_param(cfg, sid).get('s') or []):
        last_ent = max(last_ent, num(e.get('shootFrame')) / FPS)
    sched = skill_schedule(cfg, sid)
    last_hit = max((d + (n - 1) * iv for d, _s, n, iv in sched), default=0.0)
    return max(last_ent, last_hit) + tail


def skill_range(cfg, sid, facing):
    sc = cfg.get('Skill').get(str(sid)) or {}
    arr = str(sc.get('atkRange') or '0;0;100;100').split(';')
    x0 = num(arr[0]) if len(arr) > 0 else 0
    w = num(arr[2]) if len(arr) > 2 else 100
    lo, hi = x0, x0 + w
    if facing > 0: return x0, x0 + w
    return -(x0 + w), -x0


def buff_cfg(cfg, bid):
    tbl = cfg.get('Buff')
    for lv in range(1, 40):
        b = tbl.get(str(int(bid) * 100 + lv))
        if b: return b
    return {}


def cheat_profiles(cfg, pl):
    """秘籍(SecretSkill): 同一技能上已装备秘籍的 skillAttrT 加成。

    CheatVO.attrs[skillAttrT] += skillAttrV[level]，SkillParam.getCheatValue 按技能取用；
    影响 calHitRate(hit)、calBaoJiRate(critical)、calBaoJiDamage(lucky)、calPhysicalDamage(atk)。
    """
    tbl = cfg.get('SecretSkill')
    out = {}
    for sid, items in (pl.get('secretSkill') or {}).items():
        for it in (items or {}).values():
            if int(num(it.get('equip'))) != 1: continue
            c = tbl.get(str(it.get('id'))) or {}
            attr = c.get('skillAttrT')
            if not attr: continue
            vals = str(c.get('skillAttrV') or '').split(';')
            lv = max(0, int(num(it.get('level'))))
            d = out.setdefault(str(sid), {})
            d[attr] = d.get(attr, 0.0) + num(vals[min(lv, len(vals) - 1)])
    return out


def ring_profiles(cfg, pl):
    """Ornament ring effect (ManEntity.CheckRing)。

    触发概率 = 当前施放技能的 pvpRingDefault * trigger（PvP 分支覆盖 ringDefault），
    触发上限取施放技能的 pvpRingMaxCount，命中后 RelaseSkill 释放戒指技能（atkMax=1）。
    戒指 buff 是 dmgRate，但客户端 calDamage 从不读取 dmgRate，故不按增伤处理。
    """
    orn = (pl.get('equipments') or {}).get('ornament') or {}
    ev = cfg.get('Equipment').get(str(orn.get('id'))) or {}
    out = []
    for sid in str(ev.get('skillId') or '').split(';'):
        sc = cfg.get('Skill').get(str(sid)) or {}
        c = obj_of(sc.get('custom')).get('s')
        if not isinstance(c, dict) or not c.get('ring'): continue
        trig = num(c.get('trigger'))
        special = {}
        for k, ids in (c.get('specialRingRatio') or {}).items():
            for x in ids:
                special[int(num(x))] = num(k)
        out.append(dict(sid=str(sid), name=str(sc.get('name') or sid), trigger=trig,
                        special=special, single=bool(c.get('isSingle'))))
    return out


def pvp_disabled_skills(cfg):
    """CommonConfig.pvpDisableSkills：PvP(非 PvP2) 下 getCanUse 直接返回 false。"""
    raw = str((cfg.get('Common').get('1') or {}).get('pvpDisableSkills') or '')
    return {int(num(x)) for x in raw.split(';') if num(x)}


def secret_ratio_buffs(cfg, pl):
    """秘籍 custom(type 1/2) 的 buff(type 72)：给 validSkills 临时加 skillDefaultRatio。"""
    out = []
    for sid, items in (pl.get('secretSkill') or {}).items():
        for it in (items or {}).values():
            if int(num(it.get('equip'))) != 1: continue
            c = cfg.get('SecretSkill').get(str(it.get('id'))) or {}
            if str(c.get('type')) not in ('1', '2'): continue
            for bid in (obj_of(c.get('custom')).get('s') or {}).get('buffIds') or []:
                b = buff_cfg(cfg, bid)
                if int(num(b.get('type'))) != 72: continue
                val = num(b.get('attributeV1'))
                if val <= 0: continue
                out.append(dict(cast=str(sid), add=val,
                                dur=num(b.get('totalTime')) or 5.0,
                                skills=str(b.get('validSkills') or sid).split(';')))
    return out


class DeterministicRNG:
    """复刻 MathUtils.getRandom：多人模式每帧同步一个 _rand。

    多人在线的 getRandom 不推进序列，只取当前帧的 _rand；_rand 由 createRandom 推进：
        RandSeed = (RandSeed * 29 + 37) % 1000 ; _rand = RandSeed / 1000
    客户端每收 1 个服务端帧会处理 2 个 FrameVO（都带 rand=true），故每帧推进 2 次；
    每次伤害事件还会额外推进 1 次（暴击 roll 用 getRandom(...,false)）。
    """
    def __init__(self, seed=1000):
        self.seed = seed
        self.val = 0.0
    def advance(self):
        self.seed = (self.seed * 29 + 37) % 1000
        self.val = self.seed / 1000.0
        return self.val


class BattleSim:
    """单侧（attacker -> defender）动作状态机 + 伤害结算。

    动作规则（CharEntity.ToAttack / updateAction）：
      - 待机按 J -> 从 attack1 起手；
      - 攻击中按 J -> 只把下一段连招排队（每段动画结束才播下一段）；
      - 技能可打断普攻（breakActionNames 含 attack1..5）；普攻不能打断技能；
      - PVP 技能冷却用 pkCD（UserVO: isPvP -> getpkCDPer()）。
    """

    def __init__(self, cfg, att, dfd, opts):
        self.cfg = cfg; self.att = att; self.dfd = dfd; self.opts = opts
        self.dm = DamageModel(cfg, [att, dfd], None)
        self.disabled = pvp_disabled_skills(cfg)      # pvpDisableSkills
        self.rng = DeterministicRNG(1000)
        self.rng.advance()
        self.hit_rate = self.dm.hit_rate(att, dfd)
        self.crit_rate = self.dm.crit_rate(att, dfd)
        self.crit_mult = self.dm.crit_mult(att, dfd)
        self.passive = int(num(att.get('passive')))
        self.hit_combo = 0; self.combo_t = 0.0; self.combo_changes = 0
        self.keys = dict(DEFAULT_KEYS)
        self.key2skill = {int(self.keys[s]): str(att['keyboard'][s])
                          for s in ('skill1', 'skill2', 'skill3', 'skill4', 'skill5')
                          if s in att['keyboard']}
        self.key2skill = {k: v for k, v in self.key2skill.items() if int(num(v)) not in self.disabled}
        self.levels = att['skill_levels']
        self.combo = att.get('attack_combo') or ['1001010']
        self.att_key = int(self.keys['attack'])
        self.jump_key = int(self.keys['jump'])
        # CharEntity.updateAction/ToJump：空中有 jumpAttack、双击方向奔跑有 runAttack
        self.jump_attack = str(att.get('jump_attack') or '')
        self.run_attack = str(att.get('run_attack') or '')
        self.on_ground = True; self.air_until = -1.0; self.jumps = 0
        self.air_time = num(opts.get('air_time', 0.9))
        self.run_window = int(num(opts.get('run_window', 20))) / FPS
        self.last_dir_up = {}; self.run_dir = 0
        self.state = 'idle'; self.att_i = 0; self.state_end = -1.0; self.queued = False
        self.cur_skill = None; self.next_cast = {}
        self.pending = []; self.seq = 0; self.potential = 0.0
        self.casts = []; self.landed = []; self.hp = dfd['allhpMax']
        # UserVO.doIn1Second: PvP 每秒回复 allreHP * PVPreHpQualificationIndex
        self.regen = num(dfd.get('reHP')) * num(cfg.get('Common')['1'].get('PVPreHpQualificationIndex'))
        self.timeline = [(0.0, self.hp)]
        self.death_t = None
        self.hp_max = dfd['allhpMax']
        # 焚天境岩浆灼烧（buff 133000101）：在固定窗口内按总伤害占比线性扣血
        self.burn_total = float(opts.get('burn_total', 0.0) or 0.0)
        self.burn_start = int(opts.get('burn_start', 204))
        self.burn_frames = int(opts.get('burn_frames', 360))
        self.x_att = opts.get('x_att', 150); self.x_dfd = opts.get('x_dfd', 1350)
        self.held = set()
        self.ring = att.get('ring') or []
        self.ring_count = {}                          # 施放技能 -> 已触发次数（pvpRingMaxCount）
        self.ring_procs = []                          # (time, ring_name)
        self.sd_buffs = att.get('sd_buffs') or []     # 秘籍 type72: 临时 skillDefaultRatio
        self.sd_active = []                           # (expire, {skills}, add)

    # ---- 位置 ----
    def _move(self, t):
        if self.opts.get('lock_movement') and self.state in ('attack', 'skill'):
            return
        sp = self.opts.get('speed', 240) / FPS
        if 'L' in self.held and 'R' not in self.held: self.x_att -= sp
        elif 'R' in self.held and 'L' not in self.held: self.x_att += sp
        self.x_att = clamp(self.x_att, 40, 1460)

    def facing(self):
        return 1 if self.x_dfd >= self.x_att else -1

    # ---- 戒指（破军/廉贞等）----
    def _check_ring(self, t, sid):
        """ManEntity.CheckRing：按当前技能 pvpRingDefault*trigger 触发，释放戒指技能。"""
        if not self.ring: return
        sc = self.cfg.get('Skill').get(str(sid)) or {}
        base = num(sc.get('pvpRingDefault'))          # PvP 只认 pvpRingDefault
        cap = int(num(sc.get('pvpRingMaxCount')))
        if base <= 0: return
        if cap > -1 and self.ring_count.get(str(sid), 0) >= cap: return
        roll = self.rng.val
        for r in self.ring:
            ratio = r['special'].get(int(num(sid)), r['trigger'])
            ratio = base * ratio
            if ratio <= 0: return
            if roll > ratio: continue
            self.ring_count[str(sid)] = self.ring_count.get(str(sid), 0) + 1
            self.ring_procs.append((t, r['name']))
            # RelaseSkill(戒指技能)：param 为空、atkMax=1，按一次技能伤害结算
            self._schedule(t, r['sid'], 1)
            return

    def _sd_add(self, t, sid):
        """秘籍 buff(type72) 给 skillDefaultRatio 的临时加成。"""
        if self.sd_active:
            self.sd_active = [x for x in self.sd_active if x[0] > t]
        return sum(v for _e, sk, v in self.sd_active if str(sid) in sk)

    # ---- 连击（1303110）----
    def combo_at(self, t):
        """HitCombox.advanceTime: 1.5s 无命中则 ×0.65，<9 归零，最多衰减 4 次。"""
        while self.hit_combo > 0 and t - self.combo_t >= 1.5:
            if self.hit_combo < 9 or self.combo_changes >= 3:
                self.hit_combo = 0
                break
            self.hit_combo = int(round(self.hit_combo * 0.65))
            self.combo_changes += 1
            self.combo_t += 1.5
        return self.hit_combo

    def _hit_landed(self, t):
        self.hit_combo = self.combo_at(t) + 1
        if self.hit_combo == 1: self.combo_changes = 0
        self.combo_t = t

    # ---- 排期 ----
    def _sd_cast(self, t, sid):
        """释放技能时触发秘籍 buff(type72)，给 validSkills 临时加 skillDefaultRatio。"""
        for b in self.sd_buffs:
            if b['cast'] == str(sid):
                self.sd_active.append((t + b['dur'], set(b['skills']), b['add']))

    def _schedule(self, t, sid, level, hits=None):
        for d, hs, n, iv in skill_schedule(self.cfg, sid):
            self.potential += self.dm.cal_damage(self.att, self.dfd, hs, level, rnd=1.0) * n
            for i in range(n):
                heapq.heappush(self.pending, (t + d + i * iv, self.seq, hs, level))
                self.seq += 1

    def _start_attack(self, t, idx, sid=None):
        # sid 显式给出（jumpAttack/runAttack）时不推进普攻连招序列
        if sid:
            sid = str(sid)
        else:
            sid = self.combo[idx % len(self.combo)]
            self.att_i = idx % len(self.combo)
        self.state = 'attack'
        # 每段普攻的实际动作时长（Skill.param.s shootFrame），短于 attack_interval 时取后者
        anim = skill_anim_len(self.cfg, sid)
        self.state_end = t + max(self.opts.get('att_len', 0.33), anim)
        self._sd_cast(t, sid)
        self._check_ring(t, sid)
        self._schedule(t, sid, 1)

    def _start_skill(self, t, sid, level):
        self.state = 'skill'; self.cur_skill = sid
        self.state_end = t + skill_anim_len(self.cfg, sid, self.opts.get('skill_tail', 0.0))
        sc = self.cfg.get('Skill').get(str(sid)) or {}
        cd = num(sc.get('pkCD'))
        if cd <= 0: cd = num(str(sc.get('cd') or '').split(';')[-1]) or 0.3
        self.next_cast[sid] = t + cd
        self.casts.append((t, sid, level))
        self._sd_cast(t, sid)
        self._check_ring(t, sid)
        self._schedule(t, sid, level)
        # 身外身等召唤物：无法精确复刻分身 AI，用“若干次普攻伤害”近似
        summon = None
        for e in (skill_param(self.cfg, sid).get('s') or []):
            if int(num(e.get('mid'))) > 0:
                summon = (num(e.get('shootFrame')) / FPS + num(e.get('shootTime')),
                          int(num(e.get('mid'))))
                break
        if summon and self.opts.get('summon_hits', 0) > 0:
            d0, _mid = summon
            life = self.opts.get('summon_life', 5.0)
            n = self.opts['summon_hits']
            for i in range(n):
                heapq.heappush(self.pending, (t + d0 + 0.3 + i * life / n, self.seq,
                                              self.combo[0], 1))
                self.seq += 1

    # ---- 每帧 ----
    def feed(self, frame_index, keys):
        t = frame_index / FPS
        self.rng.advance(); self.rng.advance()      # 两个 FrameVO
        if self.state != 'idle' and t >= self.state_end:
            if self.state == 'attack' and self.queued:
                self.queued = False
                self._start_attack(t, self.att_i + 1)
            else:
                self.state = 'idle'; self.cur_skill = None
        for k in keys:
            if k >= 300:
                if k - 300 == int(self.keys['walkLeft']): self.held.discard('L')
                elif k - 300 == int(self.keys['walkRight']): self.held.discard('R')
                continue
            if k == int(self.keys['walkLeft']): self.held.add('L'); continue
            if k == int(self.keys['walkRight']): self.held.add('R'); continue
            if k == self.jump_key: continue
            if k == self.att_key:
                if self.state == 'skill':
                    continue                          # 技能期间 J 无效
                if self.state == 'attack':
                    self.queued = True                # 只排队下一段
                else:
                    self._start_attack(t, 0)
                continue
            sid = self.key2skill.get(k)
            if not sid: continue
            if t < self.next_cast.get(sid, -1): continue
            if self.state == 'skill':
                # 新技能的 breakActionNames 必须包含当前动作名才可打断
                cur_name = str((self.cfg.get('Skill').get(str(self.cur_skill)) or {}).get('actionName') or '')
                new_sc = self.cfg.get('Skill').get(str(sid)) or {}
                if cur_name not in str(new_sc.get('breakActionNames') or '').split(';'):
                    continue
            level = int(num(self.levels.get(str(sid)) or self.levels.get(sid) or 1))
            self._start_skill(t, sid, level)
        self._move(t)
        if frame_index % 30 == 0 and self.death_t is None and self.hp > 0 and self.regen > 0:
            self.hp = min(self.dfd['allhpMax'], self.hp + self.regen)
            self.timeline.append((t, self.hp))
        if self.burn_total > 0 and self.hp > 0 and \
                self.burn_start <= frame_index < self.burn_start + self.burn_frames:
            self.hp = max(0.0, self.hp - self.hp_max * self.burn_total / max(1, self.burn_frames))
            if frame_index % 30 == 0:
                self.timeline.append((t, self.hp))
            if self.death_t is None and self.hp <= 0:
                self.death_t = t
        self._resolve(t)

    def _resolve(self, t):
        while self.pending and self.pending[0][0] <= t + 1e-9:
            due, _seq, sid, level = heapq.heappop(self.pending)
            if self.opts.get('hit_mode') == 'none':
                continue
            if self.opts.get('hit_mode', 'all') == 'geom':
                lo, hi = skill_range(self.cfg, sid, self.facing())
                d = (self.x_dfd - self.x_att) * self.facing()
                if not (lo - self.opts.get('body_half', 30) <= d <= hi + self.opts.get('body_half', 30)):
                    continue
            hit_rate = self.dm.hit_rate(self.att, self.dfd, sid)
            if hit_rate < 1 and self.rng.val > hit_rate:
                continue                           # 命中判定用当前帧 _rand，不推进
            combo = self.combo_at(due) if self.passive == 1303110 else 0
            val = self.rng.advance()               # 暴击 roll 推进
            crit_rate = self.dm.crit_rate(self.att, self.dfd, sid)
            if self.passive == 1301010 and str(sid) == '1001050':
                crit_rate = 1.0                    # 重击：普攻第 5 段必暴
            elif self.passive == 1301110 and crit_rate < 1:
                crit_rate += self.dm.blood_add(self.att)[1]
            crit = val < crit_rate
            dmg = self.dm.cal_damage(self.att, self.dfd, sid, level, rnd=val,
                                     crit=crit, combo=combo,
                                     ratio_add=self._sd_add(due, sid))
            self.hp -= dmg
            self._hit_landed(due)
            if self.hp < 0: self.hp = 0        # 血量下限 0，后续命中只记伤害不扣血
            self.landed.append((due, sid, dmg))
            self.timeline.append((due, self.hp))
            if self.death_t is None and self.hp <= 0:
                self.death_t = due

    def run(self, events, frames):
        for f in range(frames):
            self.feed(f, events.get(f, []))
        return self


def simulate(att, dfd, ps, cfg, events, args, rng=None):
    """兼容旧调用：用 BattleSim 结算一场。"""
    opts = dict(att_len=args.attack_interval, skill_tail=getattr(args, 'skill_tail', 0.0),
                x_att=args.p1_x if att == 1 else args.p0_x,
                x_dfd=args.p1_x if dfd == 1 else args.p0_x,
                speed=args.speed, body_half=args.body_half,
                lock_movement=bool(args.lock_movement), hit_mode=args.hit_mode,
                summon_hits=getattr(args, 'summon_hits', 0),
                summon_life=getattr(args, 'summon_life', 5.0),
                burn_total=getattr(args, 'burn', 0.0) / 100.0)
    sim = BattleSim(cfg, ps[att], ps[dfd], opts)
    sim.run(events, args.frames)
    return dict(hp=sim.hp, timeline=sim.timeline, casts=sim.casts,
                all_hits=len(sim.landed), landed=sim.landed,
                potential=sim.potential, landed_dmg=sum(d for _t, _s, d in sim.landed),
                x_end=sim.x_att, death=sim.death_t, ring_procs=sim.ring_procs)

# ---------------- capture parsing ----------------
def load_capture(path):
    player_infos = None; frames = []; seed = None
    for line in open(path, encoding='utf-8'):
        r = json.loads(line)
        route = r.get('route')
        body = r.get('body') or {}
        if route == 'onCreateOnlineCopy':
            player_infos = body.get('playerInfos')
            seed = body.get('randomSeed')
        elif route == 'onSendFrame':
            frames += body.get('frames') or []
    if not player_infos:
        raise SystemExit('capture has no onCreateOnlineCopy: ' + path)
    return player_infos, frames, seed

def load_report(path):
    rep = json.load(open(path, encoding='utf-8'))
    infos = (rep.get('sceneInfo') or {}).get('playerInfo')
    if not infos:
        raise SystemExit('report has no sceneInfo.playerInfo: ' + path)
    return rep, infos

def key_events(frames, idx):
    ev = collections.defaultdict(list)
    for f in frames:
        for o in f.get('playerOper') or []:
            if o.get('playerIdIndex') == idx:
                for k in o.get('keys') or []:
                    ev[int(f.get('currFrame') or 0)].append(int(k))
    return ev

def attach_player_meta(cfg, ps, infos):
    for i, pl in enumerate(infos):
        ps[i]['skill_levels'] = pl.get('skill') or {}
        ps[i]['keyboard'] = pl.get('keyboard') or {}
        cid = int(num(pl.get('charId')))
        role = cfg.get('Role').get(str(raw_char_id(cid))) or {}
        combo = []
        for nm in COMBO_NAMES:
            sid = str(role.get(nm) or '0')
            if sid not in ('', '0', 'None'):
                combo.append(sid)
        ps[i]['attack_combo'] = combo or ['1001010']
        ps[i]['attack_skill'] = ps[i]['attack_combo'][0]
        ps[i]['jump_attack'] = str(role.get('jumpAttack') or '')
        ps[i]['run_attack'] = str(role.get('runAttack') or '')
        if ps[i]['jump_attack'] in ('', '0', 'None'): ps[i]['jump_attack'] = ''
        if ps[i]['run_attack'] in ('', '0', 'None'): ps[i]['run_attack'] = ''
        ps[i]['name'] = pl.get('name')
        ps[i]['passive'] = int(num((pl.get('keyboard') or {}).get('SkillPassive')))
        ps[i]['cheat'] = cheat_profiles(cfg, pl)
        ps[i]['ring'] = ring_profiles(cfg, pl)
        ps[i]['sd_buffs'] = secret_ratio_buffs(cfg, pl)

def main():
    ap = argparse.ArgumentParser(description='造梦西游5 PVP 本地战斗模拟')
    ap.add_argument('--capture'); ap.add_argument('--report')
    ap.add_argument('--cfg', default=DEFAULT_CFG)
    ap.add_argument('--me', type=int, default=None, help='自己所在 playerInfos 下标（默认按名字自动识别）')
    ap.add_argument('--frames', type=int, default=None, help='模拟帧数（默认 capture=1240，战报=最后帧+1）')
    ap.add_argument('--p0-x', type=float, default=150)
    ap.add_argument('--p1-x', type=float, default=1350)
    ap.add_argument('--speed', type=float, default=240)
    ap.add_argument('--body-half', type=float, default=30)
    ap.add_argument('--attack-interval', type=float, default=0.33, help='普攻每段动画时长')
    ap.add_argument('--skill-tail', type=float, default=0.0, help='技能动画在最后一次命中后的尾巴')
    ap.add_argument('--summon-hits', type=int, default=5, help='召唤物近似命中次数（0=不结算）')
    ap.add_argument('--summon-life', type=float, default=5.0)
    ap.add_argument('--burn', type=float, default=0.0,
                    help='焚天境灼烧总伤害（占最大生命百分比，帧204起360帧线性扣除）')
    ap.add_argument('--lock-movement', type=int, default=1)
    ap.add_argument('--hit-mode', choices=('geom','all','none','fraction'), default='all')
    ap.add_argument('--hit-fraction', type=float, default=0.3)
    ap.add_argument('--seed', type=int, default=20261107)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    if not args.capture and not args.report: ap.error('需要 --capture 或 --report')
    cfg = Config(args.cfg)
    if args.capture:
        infos, frames, seed = load_capture(args.capture)
        report = None
    else:
        report, infos = load_report(args.report)
        frames = (report.get('frames') or [])
        seed = None
    if args.me is None:
        me = 0
        for j, p in enumerate(infos):
            if '盒饭' in str(p.get('name')): me = j; break
    else:
        me = args.me
    if args.frames is None:
        if report:
            args.frames = max([int(f.get('currFrame') or 0) for f in frames] + [1239]) + 1
        else:
            args.frames = 1240
    ps, strong, weak = pvp_final(cfg, infos[0], infos[1], verbose=not args.json)
    attach_player_meta(cfg, ps, infos)
    opp = 1 - me
    events = key_events(frames, opp)
    rng = random.Random(args.seed if seed is None else str(seed))
    res = simulate(opp, me, ps, cfg, events, args, rng)
    gate = None; gate_frame = None
    if report:
        my_id = str(infos[me].get('playerId'))
        for pr in report.get('playerResult') or []:
            ei = pr.get('exitPlayerInfos') or {}
            for pi in (ei.get('playerInfo') or []):
                # 只取 gate 对我方的结算，且帧号取该条 playerResult 自己的
                if pi.get('from') != 'gate' or str(pi.get('playerId')) != my_id:
                    continue
                gate = (me, num(pi.get('hp')))
                gate_frame = int(ei.get('frameNum') or 0)
    out = dict(stats={i: {k: round(v, 2) if isinstance(v, (int, float)) else v for k, v in ps[i].items()
                                if k in ATTRS or k in RESIST_ATTRS or k in ('allatk','allphyDef','allhpMax','fightPower','level','name')} for i in range(2)},
               me=me, opp=opp, hp_max=ps[me]['allhpMax'], hp_end=res['hp'],
               damage=res['landed_dmg'], potential=res['potential'], casts=len(res['casts']),
               hits=len(res['landed']), gate=gate, gate_frame=gate_frame,
               ring={i: ps[i].get('ring') for i in range(2)},
               ring_procs=len(res['ring_procs']), death=None)
    # find death time from timeline
    death = None
    for t, hp in res['timeline']:
        if hp <= 0: death = t; break
    out['death'] = death
    tl = res['timeline']
    samples = []
    hp = ps[me]['allhpMax']; k = 0
    for sec in range(0, args.frames // 30 + 1):
        while k < len(tl) and tl[k][0] <= sec:
            hp = tl[k][1]; k += 1
        samples.append((sec, round(hp)))
    out['timeline'] = samples
    out['landed_damage'] = res['landed_dmg']
    out['x_end'] = res['x_end']
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print('=' * 72)
    print(f'我方={me} {infos[me].get("name")} 对手={opp} {infos[opp].get("name")}')
    for i in range(2):
        s = ps[i]
        print(f'  [{i}] lvl={s["level"]} hpMax={s["allhpMax"]:.0f} atk={s["allatk"]:.0f} def={s["allphyDef"]:.0f} '
              f'hit={s["allhit"]:.0f} dodge={s["alldodge"]:.0f} crit={s["allcritical"]:.0f} tough={s["alltoughness"]:.0f}')
        print('      抗性 ' + ' '.join(f'{a[:-6]}={s.get("all"+a, 0):.0f}' for a in RESIST_ATTRS))
        for r in (s.get('ring') or []):
            print(f'      戒指 {r["name"]}: 触发率 = 技能pvpRingDefault*{r["trigger"]*100:.0f}%')
    if res['ring_procs']:
        print(f'  戒指触发 {len(res["ring_procs"])} 次: ' +
              ', '.join(f'{n}@{t:.1f}s' for t, n in res['ring_procs'][:12]))
    dm = DamageModel(cfg, ps, rng)
    print(f'  命中率(对手打我方)={dm.hit_rate(ps[opp], ps[me]):.4f}  暴击率={dm.crit_rate(ps[opp], ps[me]):.4f} '
          f'暴击倍率={dm.crit_mult(ps[opp], ps[me]):.4f}')
    print(f'对手出招 {len(res["casts"])} 次，命中判定 {res["all_hits"]} 次，理论伤害上限 {res["potential"]:.0f}')
    print(f'模拟落地伤害 {res["landed_dmg"]:.0f}（{len(res["landed"])} 次命中），剩余 HP {res["hp"]:.0f} / {ps[me]["allhpMax"]:.0f}')
    if gate and gate[0] == me:
        hp_at_gate = ps[me]['allhpMax']
        for t, v in res['timeline']:
            if gate_frame and t <= gate_frame / FPS: hp_at_gate = v
        print(f'战报 gate: frame {gate_frame} 我方 hp={gate[1]:.0f}（模型 {hp_at_gate:.0f}，差值 {hp_at_gate-gate[1]:+.0f}）')
        if gate[1] <= 0 and death:
            print(f'  gate 判定归零帧 {gate_frame}，模型归零帧 {int(death*FPS)}（差 {int(death*FPS)-gate_frame:+d} 帧）')
    print('HP 时间线（每 30 帧 = 1 秒）：')
    for t, hp in out['timeline']:
        print(f'  {t:6.1f}s  {hp:>12.0f}')
    print('HP 归零: ' + (f'{death:.2f}s (frame {int(death*FPS)})' if death else '未归零（模拟结束时仍有 HP）'))
    if death:
        print(f'建议提交 battleExit(battleResult=4): 第 {int(death*FPS)} 帧（{death:.2f}s），判负不触发逃跑')
    else:
        print(f'建议: 本场预计不会自然死亡（窗口末剩余 {res["hp"]/ps[me]["allhpMax"]*100:.1f}%），'
              f'可直接在 {args.frames} 帧附近提交 battleExit(battleResult=4)')
    print(f'  对手出招 {len(res["casts"])} 次: ' + ', '.join(f'{s}@{t:.1f}s' for t, s, _l in res['casts'][:20]))

if __name__ == '__main__':
    main()
