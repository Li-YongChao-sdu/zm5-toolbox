"""我的日常：共享连接逐项执行、失败隔离与结果汇总。"""
import argparse
import json
import contextlib
import sys
from datetime import datetime
from pathlib import Path
from my_daily_execution import TaskFlow, BatchFatal, FATAL_EXIT, load_shops, run_tasks, is_expected_skip


def run_selected(da, keys, tasks, jobs=(), *, login=None, report_dir=None, plan_errors=None):
    from my_daily_policy import configure
    from my_daily_catalog import BY_KEY, DEFINITIONS
    from activity_availability import disabled_reason
    folder = Path(report_dir) if report_dir else Path(__file__).resolve().parent / 'my_daily_reports'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json')
    labels = {r[1]: r[0] for r in tasks}
    plan_errors = dict(plan_errors or {})
    job_map = {}
    for row in DEFINITIONS:
        matches = [job for job in jobs if job.get('kind') == row[2] and job.get('label') == row[1]]
        if len(matches) == 1:job_map[row[0]] = matches[0]
    original_login = da.login
    source_login = login or original_login
    guard = None
    bound_rid = None
    identity = (str(da.UID), int(da.RECORD_INDEX))

    def save(report):
        payload = dict(report, uid=identity[0], slot=identity[1])
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    def shared_login(*args, **kwargs):
        nonlocal guard, bound_rid
        if (str(da.UID), int(da.RECORD_INDEX)) != identity:
            raise BatchFatal('账号或存档设置发生变化')
        for attempt in range(2):
            if guard is None:
                shops = load_shops()
                try:
                    raw, _ = source_login(*args, **kwargs)
                except (Exception, SystemExit) as exc:
                    raise BatchFatal('登录失败，未执行后续项目：' + str(exc)) from exc
                guard = TaskFlow(raw, shops, identity[0])
            try:
                reply = guard.request('connector.entryHandler.entry', {'index': identity[1], 'userAgent': guard.user_agent})
                if reply.get('error') or reply.get('code', 200) != 200 or not isinstance(reply.get('info'), dict):
                    raise RuntimeError('当前存档刷新失败')
                current_rid = reply['info'].get('_id') or reply['info'].get('rid')
                if bound_rid is not None and bound_rid != current_rid:
                    guard.halted = True
                    raise BatchFatal('重连后的实际存档发生变化')
                bound_rid = current_rid
                return guard, reply['info']
            except BatchFatal:
                raise
            except Exception:
                if guard.halted or attempt:
                    raise
                guard.close()
                guard = None
                print('[我的日常] 只读刷新失败，重连一次；不重发变更或结算请求。', flush=True)

    class TaskOutput:
        def __init__(self, stream):
            self.stream = stream
            self.tail = ''
        def write(self, value):
            self.tail = (self.tail + value)[-16384:]
            return self.stream.write(value)
        def flush(self):
            return self.stream.flush()
        def __getattr__(self, name):
            return getattr(self.stream, name)

    def execute(key):
        if key in plan_errors or (key in BY_KEY and key not in job_map):
            reason = plan_errors.get(key, '原页面未设置或未确认当前存档的目标')
            print('[我的日常] 设置不足，跳过本项：' + labels.get(key,key) + '：' + reason, flush=True)
            return {'status':'skipped','message':reason}
        reason = disabled_reason(key)
        if reason:
            print('[我的日常] 跳过：' + reason, flush=True)
            return {'status': 'skipped', 'message': reason}
        configure(da, [key], tasks)
        da.MAIN_CUSTOM_MID = 0
        da.MAIN_CUSTOM_TIMES = 0
        da.MY_DAILY_FUN_JOBS = [job_map[key]] if key in job_map else []
        da.RUN_MY_DAILY_FUN = bool(da.MY_DAILY_FUN_JOBS)
        if guard is not None:
            guard.begin_task()
        print('[我的日常] 执行：' + labels.get(key, key), flush=True)
        output = TaskOutput(sys.stdout)
        with contextlib.redirect_stdout(output):
            da.main()
        if guard is not None and guard.halted:
            raise BatchFatal('请求未确认或触发付费保护')
        if guard is not None and guard.errors:
            return {'status': 'failed', 'message': '；'.join(guard.errors)}
        failures = ('操作异常', '执行失败', '异常停止', '异常跳过', '已停止本轮日常', '本项停止', '入场失败', '结算失败', '失败：', '失败:')
        reasons = []
        for line in output.tail.splitlines():
            text = line.strip()
            if any(marker in text for marker in failures) and not is_expected_skip(text) and text not in reasons:
                reasons.append(text)
        if reasons:
            return {'status': 'failed', 'message': '；'.join(reasons[-3:])[:400]}
        return {'status': 'complete' if guard is not None and guard.writes else 'skipped',
                'message': '' if guard is not None and guard.writes else '无需变更：已完成、次数已用尽或条件未满足'}

    da.login = shared_login
    try:
        report = run_tasks(keys, execute, halted=lambda: guard is not None and guard.halted, save=save)
        counts = {name: sum(r['status'] == name for r in report['tasks']) for name in ('complete', 'skipped', 'failed', 'fatal')}
        print('[我的日常汇总] 成功{complete}、跳过{skipped}、失败{failed}、中止{fatal}；未执行{n}项。记录：{path}'.format(**counts, n=len(report['unexecuted']), path=path), flush=True)
        problems = [r for r in report['tasks'] if r['status'] in ('failed', 'fatal')]
        if problems or report['unexecuted']:
            print('[我的日常] 以下项目未完成，请补提交后再运行：', flush=True)
            for row in problems:
                print('  - %s（%s）：%s' % (labels.get(row.get('key'), row.get('key')), '失败' if row['status'] == 'failed' else '中止', row.get('message') or '无详细信息'), flush=True)
            for key in report['unexecuted']:
                print('  - %s（未执行）：上一项中止后未执行' % labels.get(key, key), flush=True)
        else:
            print('[我的日常] 所有项目已完成或正常跳过，无需补提交。', flush=True)
        return report
    finally:
        da.login = original_login
        if guard is not None:
            guard.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--tasks', required=True)
    p.add_argument('--fun-plan')
    a = p.parse_args()
    import daily_auto as da
    from gui import TASKS
    from my_daily_catalog import catalog, prepare_plan
    from my_daily_policy import configure
    keys = json.loads(a.tasks)
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        raise ValueError('任务列表无效')
    tasks = catalog(TASKS)
    jobs, errors = prepare_plan(set(keys), json.loads(a.fun_plan) if a.fun_plan else None, da.UID, da.RECORD_INDEX)
    configure(da, keys, tasks)
    report = run_selected(da, keys, tasks, jobs, plan_errors=errors)
    return FATAL_EXIT if report['status'] == 'stopped' else (1 if report['status'] == 'complete_with_failures' else 0)

if __name__ == '__main__':
    raise SystemExit(main())
