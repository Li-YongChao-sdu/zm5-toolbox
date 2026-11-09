"""日常逐项执行：普通失败继续，未知消耗与账号变化停止。"""
import json
from pathlib import Path
from my_daily_policy import FreeDailyFlow, is_readonly_route

FATAL_EXIT = 20
PREPARE = ('RUN_FLUSHOU', 'RUN_GROWTH_BUFF', 'RUN_WEEKEND_BUFF')
FINISH = ('RUN_CELEBRATION', 'RUN_CELEBRATION_ONLINE', 'RUN_WEEKEND_ONLINE',
          'RUN_PERMANENT_FASHION', 'RUN_WHITE_DRAGON', 'RUN_LIVENESS')

def is_expected_skip(message):
    return any(text in str(message) for text in (
        '未完成', '没有完成', '已领取', '已经领取', '已领过', '任务已接受',
        '次数已', '次数用完', '次数不足', '次数超', '已用尽', '已达上限',
        '达到上限', '已达每日贡献次数上限', '尚未', '未到', '不满足', '未达', '条件不足', '等级不足',
        '任务不存在', '不存在该任务', '没有该任务', '未接受', '未接取',
        '不能接取', '未开启', '暂未开放', '灵魂不足', '材料不足',
        '活跃点数不足', '战力不足',
        '背包已满', '背包空间不足', '背包不足', '仓库已满',
        '背包格子', '需各预留', '预留1个', '预留一个', '格子数必须大于'))


class BatchFatal(RuntimeError):
    pass


def ordered_tasks(keys):
    keys = list(dict.fromkeys(keys))
    pinned = set(PREPARE + FINISH)
    return ([k for k in PREPARE if k in keys]
            + [k for k in keys if k not in pinned]
            + [k for k in FINISH if k in keys])


def load_shops():
    from game_version import latest_config_folder
    root = latest_config_folder()
    path = (root if root is not None else Path(__file__).resolve().parent / 'feature_config') / 'Shop.json'
    return json.loads(path.read_text(encoding='utf-8-sig'))


class TaskFlow(FreeDailyFlow):
    def __init__(self, flow, shops, uid):
        super().__init__(flow, shops)
        self.uid = str(uid)
        self.rid = None
        self.begin_task()

    def begin_task(self):
        self.errors = []
        self.skips = []
        self.writes = 0

    def disconnect(self):
        # daily_auto.main每项都会断开；真正关闭由批量执行器统一负责。
        pass

    def close(self):
        self.flow.disconnect()

    def request(self, route, params=None, *args, **kwargs):
        readonly = is_readonly_route(route)
        try:
            reply = super().request(route, params, *args, **kwargs)
        except Exception as exc:
            if self.halted:
                raise BatchFatal(str(exc)) from exc
            self.errors.append(str(exc))
            raise
        if not isinstance(reply, dict):
            if not readonly:
                self.halted = True
                raise BatchFatal('变更请求返回格式不明：' + route)
            raise RuntimeError('查询回包无效：' + route)
        if reply.get('error') or reply.get('code', 200) not in (None, 200):
            message = str(reply.get('error') or reply.get('code'))
            (self.skips if is_expected_skip(message) else self.errors).append(message)
        elif not readonly:
            self.writes += 1
        if route == 'connector.entryHandler.entry' and not reply.get('error') and reply.get('code', 200) == 200:
            info = reply.get('info') or {}
            rid = info.get('_id') or info.get('rid')
            if str(info.get('uid')) != self.uid or not rid or (self.rid is not None and self.rid != rid):
                self.halted = True
                raise BatchFatal('账号或实际存档已变化')
            self.rid = rid
        return reply


def run_tasks(keys, execute, *, halted=lambda: False, save=lambda report: None, log=print):
    report = {'status': 'running', 'tasks': [], 'unexecuted': []}
    keys = ordered_tasks(keys)
    for index, key in enumerate(keys):
        row = {'key': key, 'status': 'running'}
        report['tasks'].append(row)
        save(report)
        try:
            if halted():
                raise BatchFatal('上一操作结果不明，停止后续项目')
            result = execute(key) or {}
            if halted():
                raise BatchFatal('本项存在未确认请求或付费拦截')
            row.update(result)
            row.setdefault('message', '')
            if row['status'] == 'running':
                row['status'] = 'complete'
        except BatchFatal as exc:
            row.update(status='fatal', message=str(exc))
            report.update(status='stopped', unexecuted=keys[index + 1:])
            log('[我的日常] 必须停止：' + str(exc))
            save(report)
            return report
        except Exception as exc:
            row.update(status='failed', message=str(exc))
            log('[我的日常] 本项失败，继续后续：' + key + '：' + str(exc))
        save(report)
    report['status'] = 'complete_with_failures' if any(r['status'] == 'failed' for r in report['tasks']) else 'complete'
    save(report)
    return report
