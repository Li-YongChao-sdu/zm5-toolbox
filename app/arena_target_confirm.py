"""指定目标的临时查询/确认状态；不保存到界面配置。"""
import hashlib
import json


def identity(data, handler):
    base = {'rid': data['rid'], 'name': data['name']}
    if handler == 'petArena':
        base['charId'] = str(data.get('charId'))
        base['pets'] = [(str(p.get('entityId')), str(p.get('id')), p.get('nickName'),
                         p.get('level'), p.get('sex')) for p in data.get('pets') or []]
    else:
        base['index'] = int(data.get('index', 0))
        base['roles'] = [(key, str((data.get(key) or {}).get('charId')),
                          (data.get(key) or {}).get('name')) for key in ('p1', 'p2')]
    return hashlib.sha256(json.dumps(base, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


class Approval:
    def __init__(self):
        self.revision = 0
        self.result = None
        self.approved = None

    def invalidate(self):
        self.revision += 1
        self.result = None
        self.approved = None

    def receive(self, revision, binding, data, handler):
        if revision != self.revision:
            return False
        if binding.get('rid') and binding['rid'] != data.get('rid'):
            raise ValueError('查询返回的实际rid与输入不符，未确认')
        mapping = None
        if binding.get('target_input') == 'slot':
            mapping = data.get('_ui_slot_mapping')
            if (not isinstance(mapping, dict) or mapping.get('uid') != binding.get('target_uid')
                    or mapping.get('slot') != binding.get('target_slot') or mapping.get('rid') != data.get('rid')):
                raise ValueError('未查询到可靠的界面槽位映射，不允许猜测目标ID')
        self.result = dict(binding, identity=identity(data, handler), rid=data['rid'])
        if mapping:
            self.result['slot_mapping'] = dict(mapping)
        self.approved = None
        return True

    def confirm(self, binding):
        if self.result is None or any(self.result.get(k) != v for k, v in binding.items()):
            raise ValueError('请先查询当前账号和槽位下的指定对手')
        self.approved = dict(self.result)

    def require(self, binding):
        if self.approved is None or any(self.approved.get(k) != v for k, v in binding.items()):
            raise ValueError('指定对手尚未查询并确认，或目标/账号已变更')
        return dict(self.approved)


def validate(approval, flow, slot, rid, rounds, data, handler, battle_wait=22, round_wait=22):
    expected = {'actor_uid': str(flow.uid), 'actor_slot': int(slot), 'rid': rid,
                'rounds': int(rounds), 'handler': handler}
    if not isinstance(approval, dict) or any(approval.get(k) != v for k, v in expected.items()):
        raise RuntimeError('缺少与当前出战账号、槽位和目标一致的人工确认；未发起挑战')
    if approval.get('battle_wait', 22) != battle_wait or approval.get('round_wait', 22) != round_wait:
        raise RuntimeError('等待时间与确认时不同，请重新确认；未发起挑战')
    if approval.get('identity') != identity(data, handler):
        raise RuntimeError('对手身份或阵容与确认时不同，请重新查询并确认；未发起挑战')


def description(data, handler):
    lines = ['名字：' + data['name'], '存档 ID：' + data['rid']]
    if handler == 'petArena':
        for p in data.get('pets') or []:
            lines.append('%s（%s） 等级%s，战力%s' %
                         (p.get('nickName') or p.get('name'), p.get('name'),
                          p.get('level', '?'), p.get('fightPower', '?')))
        pets = data.get('pets') or []
        if pets and all(p.get('fightPower') is not None for p in pets):
            lines.append('宠物总战力：%s' % sum(float(p['fightPower']) for p in pets))
    else:
        selected = int(data.get('index', 0))
        for i, key in enumerate(('p1', 'p2')):
            p = data.get(key) or {}
            if p:
                lines.append('%s%s：等级%s，战力%s' %
                             ('【出战】' if i == selected else '', p.get('name') or p.get('charId'),
                              p.get('level', '?'), p.get('fightPower', '?')))
    return '\n'.join(lines)
