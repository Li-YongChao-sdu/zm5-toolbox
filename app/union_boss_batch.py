"""每个账号使用独立连接；一个账号异常不影响其他账号。"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def load_jobs(path):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("请至少添加一个账号")
    jobs, seen = [], set()
    for row in rows:
        slot = int(row["slot"])
        if not 0 <= slot <= 7:
            raise ValueError("存档须为0～7")
        account = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        uid = str(account["uid"])
        if uid in seen:
            raise ValueError("同一账号只能选择一个存档，避免互相挤下线")
        seen.add(uid)
        account['_garden_password'] = row.get('garden_password', '')
        jobs.append((account, slot))
    return jobs


def run_batch(options):
    from teacher_trial import connect, enter
    from union_boss import run
    jobs = load_jobs(options.batch_file)
    active={str(a['uid']) for a,s in jobs}
    active_lock=threading.Lock()
    def participant_count():
        with active_lock:return len(active)

    def worker(account, slot):
        label = "%s / 槽%s" % (account.get("username", account["uid"]), slot)
        try:
            if options.action == "garden":
                import copy
                from union_garden import run_garden
                garden_options = copy.copy(options)
                garden_options.garden_password = account.get('_garden_password', '')
                return run_garden(account, slot, label, garden_options)
            if getattr(options, "action", "boss") == "devote":
                return run_devote(account, slot, label)
            if options.action == "dog":
                return run_dog(account, slot, label)
            result = run(options.level, options.percent_per_minute,
                         options.max_seconds, options.expected_dps,
                         options.target_percent, options.idle_only,
                         not options.no_target, options.idle_mode,
                         connector=lambda: connect(account, slot)[0],
                         entry=lambda flow: enter(flow, slot), label=label,
                         finish_at_end=getattr(options,'finish_at_end',False),participant_count=participant_count,
                         finish_power=getattr(options,'finish_power',1),
                         real_damage=not getattr(options,'mock_damage',False))
            print("[%s] %s；奖励请在邮件中领取" %
                  (label, "服务器结算成功" if result else "未取得成功结算"), flush=True)
            return result
        except Exception as exc:
            # 不输出登录异常详情，防止第三方响应包含认证数据。
            print("[%s] 执行失败（%s），其他账号继续" %
                  (label, type(exc).__name__), flush=True)
            return False
        finally:
            with active_lock:active.discard(str(account['uid']))

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = [pool.submit(worker, account, slot) for account, slot in jobs]
        results = [future.result() for future in as_completed(futures)]
    print("[多账号%s] %s %s / %s" % ({'boss':'联盟Boss','devote':'联盟贡献','garden':'联盟药园','dog':'免费抽狗卡'}[options.action], '已完成核对（含次数用完跳过）' if options.action == 'dog' else '成功', sum(results), len(results)), flush=True)
    return all(results)


DOG_NAMES = ('博美汪', '斗牛汪', '蝴蝶汪', '杜宾汪', '金毛汪', '牧羊汪',
             '贵宾汪', '松狮汪', '秋田汪', '冠毛汪', '藏獒汪')


def run_dog(account, slot, label, *, flow=None):
    """每账号一次普通抽取；任何未确认的抽卡请求都不自动重发。"""
    from datetime import datetime
    from teacher_trial import connect, checked
    folder = Path('运行记录') / ('狗卡_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    folder.mkdir(parents=True, exist_ok=True)
    record = {'slot': slot, 'status': 'connecting'}
    def save():
        (folder / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    def counts(state):
        data = state.get('data')
        if not isinstance(data, dict):
            raise ValueError('服务器没有下发狗卡余额')
        return {f'dog_{i}': int(data.get(f'dog_{i}', 0)) for i in range(1, 12)}
    def wallet(flow):
        user = checked(flow.request('connector.roleHandler.getUserInfo', {}), '读取货币').get('user') or {}
        if 'ticket' not in user:
            raise ValueError('服务器没有下发点券，未继续抽取')
        return user['ticket']
    own_connection = flow is None
    try:
        print('[%s] 正在连接并读取狗卡库存' % label, flush=True)
        if own_connection:
            flow, _ = connect(account, slot)
        before = counts(checked(flow.request('scene.activityHandler.getDouble11Data', {}), '查询狗卡'))
        ticket = wallet(flow)
        record.update(before=before, ticket_before=ticket, status='pending', route='scene.activityHandler.double11Lottery', params={})
        save()
        print('[%s] 发送一次普通抽卡；跨槽共享，不自动重试' % label, flush=True)
        reply = flow.request('scene.activityHandler.double11Lottery', {})
        record.update(reply=reply, status='checking'); save()
        after = counts(checked(flow.request('scene.activityHandler.getDouble11Data', {}), '抽卡后查询'))
        ticket_after = wallet(flow)
        delta = {k: after[k] - before[k] for k in before if after[k] != before[k]}
        record.update(after=after, delta=delta, ticket_after=ticket_after)
        if ticket_after != ticket:
            raise RuntimeError('点券发生变化，请查阅记录')
        if not isinstance(reply, dict):
            raise RuntimeError('抽卡回复不完整')
        if reply.get('code') != 200 or reply.get('error'):
            error = str(reply.get('error') or reply.get('code'))
            skipped = error == '抽奖次数已用完' and not delta
            record['status'] = 'skipped' if skipped else 'rejected'; save()
            print('[%s] %s：%s；点券%s→%s；记录%s' % (label, '跳过' if skipped else '未成功', error, ticket, ticket_after, folder), flush=True)
            return skipped
        expected = {}
        for item in reply.get('give') or []:
            key = str(item.get('subType', ''))
            if item.get('type') == 'coin' and key in before:
                expected[key] = expected.get(key, 0) + int(item.get('count', 0))
        if not expected or any(v <= 0 for v in expected.values()) or delta != expected:
            raise RuntimeError('奖励回复与重新读取的狗卡余额不一致')
        record['status'] = 'verified'; save()
        rewards = '、'.join('%s×%s（%s→%s）' % (DOG_NAMES[int(k[4:])-1], v, before[k], after[k]) for k, v in expected.items())
        print('[%s] 到账已核对：%s；点券%s→%s；记录%s' % (label, rewards, ticket, ticket_after, folder), flush=True)
        return True
    except Exception as exc:
        # 已发出的请求不重放，保留pending/checking和余额供下次人工核对。
        record['failure_type'] = type(exc).__name__
        save()
        print('[%s] 狗卡未完成核对；不自动重发，请查看%s' % (label, folder), flush=True)
        return False
    finally:
        if flow and own_connection:
            flow.disconnect()


def run_devote(account, slot, label):
    from teacher_trial import connect, enter
    flow, info = connect(account, slot)
    try:
        if not (info.get("league") or {}).get("leagueId"):
            raise ValueError("未加入联盟")
        before = flow.request("connector.roleHandler.getUserInfo", {}).get("user") or {}
        if "ticket" not in before:
            raise ValueError("无法核对点券")
        # 配置第1档消耗1000灵魂，每日1次；第2档消耗500点券，不提供。
        reply = flow.request("scene.leagueHandler.leagueDevote", {"devoteId": 1})
        after = flow.request("connector.roleHandler.getUserInfo", {}).get("user") or {}
        if after.get("ticket") != before["ticket"]:
            raise RuntimeError("点券余额发生变化")
        if reply.get("code") != 200 or reply.get("error"):
            print("[%s] 贡献未执行：%s；点券不变" %
                  (label, reply.get("error") or reply.get("code")), flush=True)
            return False
        print("[%s] 灵魂贡献成功；奖励 %s；点券 %s→%s" %
              (label, reply.get("give"), before["ticket"], after["ticket"]), flush=True)
        return True
    finally:
        flow.disconnect()


if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="多账号联盟贡献 / 联盟Boss")
    parser.add_argument("--batch-file", required=True)
    parser.add_argument("--action", choices=["boss", "devote", "garden", "dog"], required=True)
    parser.add_argument("--garden-pick", action="store_true")
    parser.add_argument("--garden-uproot", action="store_true")
    parser.add_argument("--garden-plant", type=int, default=0)
    parser.add_argument("--garden-mode", choices=['direct','buy'], default='direct')
    parser.add_argument("--garden-count", type=int, default=1)
    parser.add_argument("--level", type=int, default=0)
    parser.add_argument("--percent-per-minute", type=float, default=0.2)
    parser.add_argument("--max-seconds", type=int, default=0)
    parser.add_argument("--expected-dps", type=float)
    parser.add_argument('--finish-at-end',action='store_true',help='按服务器结束前5秒目标动态分摊剩余血量')
    parser.add_argument('--finish-power',type=float,default=1,help='定时击杀曲线；2表示前低后高，超前则0伤害等待')
    parser.add_argument("--target-percent", type=float, default=0.2)
    parser.add_argument("--idle-only", action="store_true")
    parser.add_argument("--no-target", action="store_true")
    parser.add_argument("--idle-mode", action="store_true")
    parser.add_argument("--idle-after-02", action="store_true",
                        help="服务器累计伤害达到最大血量0.2%%后挂机")
    options = parser.parse_args()
    if options.idle_after_02:
        options.target_percent = 0.2
        options.idle_mode = True
        options.no_target = False
        options.idle_only = False
    sys.exit(0 if run_batch(options) else 1)
