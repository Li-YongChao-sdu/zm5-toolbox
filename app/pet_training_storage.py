"""Windows-safe JSON snapshots: unique temp files, serialized writes and bounded retry.

Only local disk writes are retried. A failed replacement leaves the previous
manifest intact and preserves a separate recovery snapshot for manual inspection.
"""
import json,os,tempfile,threading,time
from pathlib import Path

_locks={}
_guard=threading.Lock()
_DELAYS=(.05,.1,.2,.4,.8,1.,1.,1.)

def _lock(path):
    key=os.path.normcase(str(path.resolve()))
    with _guard:return _locks.setdefault(key,threading.RLock())

def _retryable(exc):
    return isinstance(exc,PermissionError) or getattr(exc,'winerror',None) in (5,32,33)

def atomic_json(path,data):
    path=Path(path)
    # Serialize before creating any temporary file; never truncate the destination.
    payload=json.dumps(data,ensure_ascii=False,indent=2)
    with _lock(path):
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',prefix='.'+path.stem+'.',suffix='.tmp',dir=path.parent,delete=False) as handle:
                temp=Path(handle.name);handle.write(payload)
            announced=False
            for attempt in range(len(_DELAYS)+1):
                try:
                    os.replace(temp,path)
                    return
                except OSError as exc:
                    if not _retryable(exc) or attempt==len(_DELAYS):raise
                    if not announced:
                        from pet_training_log import say
                        say('本地保存','%s暂时无法替换，正在重试本地保存；不会重发游戏请求'%path.name)
                        announced=True
                    time.sleep(_DELAYS[attempt])
        except OSError as exc:
            snapshot=str(temp) if temp is not None and temp.exists() else '未能创建恢复副本'
            raise OSError('本地记录保存失败：%s；原记录未主动删除；最新恢复副本：%s。请检查该目录写入权限、文件只读状态及占用程序。未重发游戏请求。原始错误：%s'%(path,snapshot,exc)) from exc
