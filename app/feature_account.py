"""抓宠功能使用工具箱当前账号，导入时不连接服务器。"""
import daily_auto as da
from teacher_trial import connect as _connect

ACCT = dict(uid=da.UID, username=da.USERNAME, cookies=da.COOKIES,
            record_index=da.RECORD_INDEX)

def connect(account):
    return _connect(account, account['record_index'])[0]

def entry(flow, account):
    result = flow.request('connector.entryHandler.entry',
                          {'index': account['record_index'], 'userAgent': flow.user_agent})
    if result.get('code', 200) != 200 or result.get('error'):
        raise RuntimeError(str(result))
    return result.get('info', result)
