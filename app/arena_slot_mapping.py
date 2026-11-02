"""界面槽位不能拼接成r编号；从已登录目标存档读取真实ID。"""
import json
from pathlib import Path
import re


def parse_rid(value):
    text = str(value).strip()
    match = re.fullmatch(r'([0-9]+)_r([0-9]+)', text)
    if not match or int(match.group(1)) <= 0:
        raise ValueError('实际存档ID格式应为 游戏UID_r编号，例如1417112202_r11')
    return text


def number_rid(uid, number):
    uid, number = str(uid).strip(), str(number).strip()
    if not re.fullmatch(r'[0-9]+', uid) or int(uid) <= 0:
        raise ValueError('请填写正整数游戏UID，不是登录账号')
    if not re.fullmatch(r'[0-9]+', number):
        raise ValueError('r编号必须是非负整数，例如33；不是界面槽位')
    return '%s_r%d' % (uid, int(number))


def parse_ui_slot(uid, slot):
    uid, slot = str(uid).strip(), str(slot).strip()
    if not re.fullmatch(r'[0-9]+', uid) or int(uid) <= 0:
        raise ValueError('请填写正整数游戏UID，不是登录账号')
    if not re.fullmatch(r'[0-9]+', slot) or not 0 <= int(slot) <= 7:
        raise ValueError('界面槽位须为0～7；实际r编号请使用实际rid输入方式')
    return uid, int(slot)


def saved_account(actor, accounts_dir, uid):
    if str(actor.get('uid')) == uid:
        return dict(actor)
    for path in sorted(Path(accounts_dir).glob('*.json')):
        try:
            with path.open(encoding='utf-8') as stream:
                account = json.load(stream)
        except (OSError, ValueError):
            continue
        if str(account.get('uid')) == uid and account.get('cookies'):
            return account
    raise ValueError('该游戏UID没有已保存的登录资料，无法确认界面槽位映射。请先保存该账号，或改用实际rid；不会猜测r编号。')


def query_slot_target(actor, actor_slot, target, target_slot, handler, connect_fn=None):
    from arena_targets import checked, detail
    if connect_fn is None:
        from teacher_trial import connect as connect_fn
    uid, target_slot = parse_ui_slot(target['uid'], target_slot)
    if str(actor.get('uid')) == uid and int(actor_slot) == target_slot:
        raise ValueError('出战存档与目标存档相同；同账号可选择不同存档')
    flow = None
    try:
        flow, entry = connect_fn(target, target_slot)
        home = checked(flow.request('scene.%sHandler.getArenaInfo' % handler, {}), '读取目标槽位实际ID')
        rid = parse_rid((home.get('self') or {}).get('rid', ''))
        if rid.split('_r')[0] != uid:
            raise RuntimeError('目标槽位返回的游戏UID不符，未确认、未挑战')
        roles = [(entry.get(key) or {}).get('name') for key in ('p1', 'p2')
                 if (entry.get(key) or {}).get('name')]
        # 不能保持同账号的两条连接；关闭目标连接后再恢复出战A。
        flow.disconnect()
        flow = None
        flow, _ = connect_fn(actor, actor_slot)
        data = dict(detail(flow, handler, rid))
        data['_ui_slot_mapping'] = {'uid': uid, 'slot': target_slot, 'rid': rid, 'roles': roles}
        return data
    finally:
        if flow:
            flow.disconnect()


def confirmed_rid(approval, input_mode, uid, slot, explicit_rid):
    if not isinstance(approval, dict):
        raise RuntimeError('指定对手必须先查询实际ID并确认；未发起挑战')
    if approval.get('target_input') != input_mode:
        raise RuntimeError('对手输入方式与确认时不同，请重新查询确认')
    rid = parse_rid(approval.get('rid', ''))
    if input_mode == 'r_number':
        expected = number_rid(uid, slot)
        if rid != expected or approval.get('target_uid') != str(uid).strip() or approval.get('r_number') != int(str(slot).strip()):
            raise RuntimeError('UID或实际r编号与确认时不同，请重新查询确认')
    elif input_mode == 'slot':
        uid, slot = parse_ui_slot(uid, slot)
        if approval.get('target_uid') != uid or approval.get('target_slot') != slot:
            raise RuntimeError('UID或界面槽位与确认时不同，请重新查询确认')
        mapping = approval.get('slot_mapping')
        if not isinstance(mapping, dict) or mapping.get('uid') != uid or mapping.get('slot') != slot or mapping.get('rid') != rid:
            raise RuntimeError('缺少服务器查询到的槽位映射，不允许拼接目标ID')
        if rid.split('_r')[0] != uid:
            raise RuntimeError('映射的目标UID不符，停止')
    elif input_mode == 'rid':
        if rid != parse_rid(explicit_rid):
            raise RuntimeError('实际rid与确认时不同，请重新查询确认')
    else:
        raise ValueError('未知的指定对手输入方式')
    return rid
