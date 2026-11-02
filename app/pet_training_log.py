"""纯本地进度反馈；等待服务器时也持续输出，不发查询请求。"""
import json,threading,time
from datetime import datetime
from functools import lru_cache
from pathlib import Path

def say(stage,message):print('[%s][%s] %s'%(datetime.now().strftime('%H:%M:%S'),stage,message),flush=True)
def duration(seconds):
    seconds=max(0,int(seconds));return '%d分%02d秒'%(seconds//60,seconds%60)
@lru_cache(maxsize=1)
def names():
    try:
        p=Path(__file__).resolve().parent/'cg_config_out_cg1_20261012_1/PetSkill.json'
        return {str(k):v.get('name',str(k)) for k,v in json.loads(p.read_text(encoding='utf-8-sig')).items()}
    except (OSError,ValueError):return {}
def potentials(pet):
    values=(pet.get('skill') or {}).get('passivity') or {}
    return '、'.join('%s%s级'%(names().get(str(k),str(k)),v) for k,v in values.items()) or '暂无潜能'

class Feedback:
    def __init__(self,stage,message,interval=10):
        self.stage=stage;self.message=message;self.interval=interval
        self.started=time.monotonic();self.updated=self.started;self.stop=threading.Event();self.lock=threading.Lock()
        self.thread=threading.Thread(target=self._loop,daemon=True)
    def __enter__(self):
        say(self.stage,self.message);self.thread.start();return self
    def set(self,message):
        with self.lock:self.message=message;self.updated=time.monotonic()
    def _loop(self):
        while not self.stop.wait(self.interval):
            with self.lock:message=self.message;updated=self.updated
            now=time.monotonic();say(self.stage,'%s；阶段耗时%s；此步骤已等待%s'%(message,duration(now-self.started),duration(now-updated)))
            if now-updated>=30:
                say('等待提示','服务器回复较慢，可能网络不稳定；尚未确认断线，请勿重复启动。若最终超时，将保留记录并提示重新登录。')
    def __exit__(self,*args):self.stop.set();self.thread.join(timeout=1)


def connection_notice(error, manifest=None):
    """只输出连接恢复指引，不重发可能已生效的游戏请求。"""
    text=str(error)
    network=isinstance(error,(ConnectionError,TimeoutError)) or any(word in text.lower() for word in
        ('timeout','timed out','socket','connection','closed','disconnect','断线','断开','超时','连接','10054','10060'))
    pending=any(word in text for word in ('pending','未确认'))
    if network:
        say('连接异常','连接已中断或请求超时，本次流程已停止；请检查网络，并确认账号未在其他窗口登录。')
    elif pending:
        say('恢复提示','检测到上次未确认的操作，需要先重新登录并核对服务器实际进度。')
    elif '消息错误' in text:
        say('服务器拒绝','服务器返回“消息错误”，不等于断线；需核对角色及副本状态，不自动连续重试。')
    else:
        return False
    if manifest:say('现场记录','本批清单：'+str(manifest))
    say('重连提示','网络恢复后可重新登录；本程序不会自动重发未确认的建房、结算、购买、遗忘或放生请求。')
    say('续跑提示','若提示“上次有未确认战斗”，请保留manifest.json及日志，核对宠物实际等级和经验后恢复；不要删除pending或重复新建批次。')
    return True


def is_connection_error(error):
    text=str(error).lower()
    return isinstance(error,(ConnectionError,TimeoutError)) or any(w in text for w in
        ('timed out','timeout','socket closed','connection closed','connection reset','connection aborted','connection refused','disconnected','broken pipe','10054','10060','断线','连接已断','连接关闭','请求超时'))
