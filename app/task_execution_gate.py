"""所有GUI入口共用的进程占用锁，直到工作进程退出才释放。"""
import threading
import itertools

class ExecutionGate:
    def __init__(self):
        self._lock=threading.Lock();self._ids=itertools.count(1);self.owner=None
    def acquire(self):
        if not self._lock.acquire(blocking=False):return None
        self.owner=next(self._ids);return self.owner
    def release(self,token):
        if self.owner is None or token!=self.owner:return False
        self.owner=None;self._lock.release();return True
    @property
    def busy(self):return self.owner is not None
