"""从 4399 资源服下载本周配置包并解包为 JSON 表。

版本规则：以 2026-10-26 为基准每 7 天递增，周内热更时文件名序号 1→2→3。
输出目录：cg_config_out_cg1_<日期>_<序号>
"""
import json,lzma,struct,urllib.request,zlib,re,tempfile,os
from datetime import date,datetime,timedelta
from pathlib import Path
from game_version import beijing_now,latest_config_folder,config_is_stale,BEIJING

ROOT=Path(__file__).resolve().parent
BASE='https://sda.4399.com/4399swf/upload_swf/ftp22/csya/20170622/1/assets/data/'
ANCHOR=date(2026,10,26);STEP=7
HEADERS={'User-Agent':'Mozilla/5.0','Referer':'https://www.4399.com/flash/zmhj.htm?g=5'}
KEY_TABLES=('Pet','Shop','Dungeon','Activity','Prop')
SWF_PREFIX='CG_CONFIG_SWF'


class AMF:
    def __init__(self,data):self.data=data;self.pos=0;self.strings=[];self.objects=[];self.traits=[]
    def take(self,n):b=self.data[self.pos:self.pos+n];assert len(b)==n;self.pos+=n;return b
    def u29(self):
        v=0
        for i in range(4):
            b=self.take(1)[0]
            if i==3:return (v<<8)|b
            v=(v<<7)|(b&127)
            if b<128:return v
    def string(self):
        n=self.u29()
        if not n&1:return self.strings[n>>1]
        if n>>1==0:return ''
        s=self.take(n>>1).decode('utf-8');self.strings.append(s);return s
    def read(self):
        t=self.take(1)[0]
        if t in (0,1):return None
        if t in (2,3):return t==3
        if t==4:
            v=self.u29();return v-0x20000000 if v&0x10000000 else v
        if t==5:return struct.unpack('>d',self.take(8))[0]
        if t==6:return self.string()
        if t==12:
            n=self.u29()
            if not n&1:return self.objects[n>>1]
            b=self.take(n>>1);self.objects.append(b);return b
        if t==9:
            n=self.u29()
            if not n&1:return self.objects[n>>1]
            a={};idx=len(self.objects);self.objects.append(a)
            while True:
                k=self.string()
                if not k:break
                a[k]=self.read()
            values=[self.read() for _ in range(n>>1)]
            if a:
                a.update({str(i):v for i,v in enumerate(values)});return a
            self.objects[idx]=values;return values
        if t==10:
            n=self.u29()
            if not n&1:return self.objects[n>>1]
            if not n&2:trait=self.traits[n>>2]
            else:
                assert not n&4,'externalizable'
                trait=(self.string(),bool(n&8),[self.string() for _ in range(n>>4)]);self.traits.append(trait)
            a={};self.objects.append(a)
            for k in trait[2]:a[k]=self.read()
            if trait[1]:
                while True:
                    k=self.string()
                    if not k:break
                    a[k]=self.read()
            return a
        if t==17:
            n=self.u29()
            if not n&1:return self.objects[n>>1]
            self.take(1);a={};self.objects.append(a)
            for _ in range(n>>1):k=self.read();a[str(k)]=self.read()
            return a
        raise ValueError('AMF marker '+str(t)+' at '+str(self.pos))


def head(name,timeout=8):
    try:
        r=urllib.request.urlopen(urllib.request.Request(BASE+name,method='HEAD',headers=HEADERS),timeout=timeout)
        size=int(r.headers.get('Content-Length') or 0)
        return r.status,size
    except Exception:
        return None,0


def discover(today=None,weeks=8):
    """返回本周最新配置文件名；候选日期不早于基准日，最多回溯 weeks 周。"""
    today=today or beijing_now().date()
    d=ANCHOR
    while d+timedelta(days=STEP)<=today:d+=timedelta(days=STEP)
    for _ in range(weeks):
        if d>=ANCHOR:
            best=None
            for idx in range(1,8):
                name='cg1_%s_%d.swf'%(d.strftime('%Y%m%d'),idx)
                status,size=head(name)
                if status!=200:break
                best={'name':name,'size':size,'date':d,'index':idx}
            if best:return best
        d-=timedelta(days=STEP)
    return None


def fetch(name,timeout=90):
    r=urllib.request.urlopen(urllib.request.Request(BASE+name,headers=HEADERS),timeout=timeout)
    return r.read()


def unpack(data,out):
    out=Path(out);out.mkdir(exist_ok=True)
    reader=AMF(data);header=reader.read();names=[];skipped=[]
    for _ in range(header['fn']):
        meta=AMF(zlib.decompress(reader.read(),-15)).read()
        payload=lzma.decompress(meta['data']) if meta['ver']==2 else zlib.decompress(meta['data'])
        value=AMF(payload).read() if meta['ver']==2 else json.loads(payload)
        name=meta['prefixName'];assert '/' not in name and '\\' not in name
        try:
            (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
            names.append(name)
        except ValueError:
            skipped.append(name)
    return header,names,skipped


PAUSE_FILE='config_sync_pause.json'


def _config_key(name):
    """从 cg1_日期_序号.swf 或配置目录名提取 (日期, 序号)。"""
    match=re.search(r'(\d{8})_(\d+)',Path(name).name)
    return (match.group(1),int(match.group(2))) if match else None


def _pause_path(dest_root=None):
    return Path(dest_root or ROOT)/PAUSE_FILE


def paused_until(dest_root=None):
    """返回本周暂停检查的截止时间；未暂停或已到期返回 None。"""
    try:
        data=json.loads(_pause_path(dest_root).read_text(encoding='utf-8'))
        until=datetime.fromisoformat(data['until'])
    except (OSError,ValueError,KeyError,TypeError):
        return None
    if until.tzinfo is None:
        until=until.replace(tzinfo=BEIJING)
    return until if beijing_now()<until else None


def _clear_pause(dest_root=None):
    try:
        _pause_path(dest_root).unlink()
    except OSError:
        pass


def _next_check(item,local):
    """服务器没有新包时，等到下一个配置日中午 12 点再检查。"""
    today=beijing_now().date()
    dates=[]
    for name in (item.get('name'),local.name):
        key=_config_key(name)
        if key:
            dates.append(datetime.strptime(key[0],'%Y%m%d').date())
    base=max(dates) if dates else today
    check=ANCHOR
    while check<=base:
        check+=timedelta(days=STEP)
    while check<today:
        check+=timedelta(days=STEP)
    until=datetime(check.year,check.month,check.day,12,tzinfo=BEIJING)
    while until<=beijing_now():
        until+=timedelta(days=STEP)
    return until


def _write_pause(dest_root,until,item,local):
    data={'until':until.isoformat(),'checked_at':beijing_now().isoformat(),
          'server':item['name'],'local':local.name}
    try:
        _pause_path(dest_root).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    except OSError:
        pass


def install_config(data,name,dest_root=None,log=print):
    """完整解包和校验后才发布目录，失败不破坏已有可用配置。"""
    if not re.fullmatch(r'cg1_\d{8}_[1-9]\d*\.swf',name):
        raise ValueError('请选择原名为 cg1_日期_序号.swf 的配置文件')
    root=Path(dest_root or ROOT);root.mkdir(parents=True,exist_ok=True)
    folder=root/('cg_config_out_'+name[:-4])
    with tempfile.TemporaryDirectory(prefix='.cg1_unpack_',dir=root) as tmp:
        stage=Path(tmp)/'tables'
        header,names,skipped=unpack(data,stage)
        missing=[k for k in KEY_TABLES if not (stage/(k+'.json')).is_file()]
        if missing:raise RuntimeError('关键表缺失：'+'、'.join(missing))
        for key in KEY_TABLES:
            value=json.loads((stage/(key+'.json')).read_text(encoding='utf-8-sig'))
            if not isinstance(value,dict) or not value:
                raise RuntimeError('关键表无效：'+key)
        if folder.exists():
            # 同名版本不原地覆盖，防止运行中读到半写入的配置。
            old={p.name:p.read_bytes() for p in folder.glob('*.json')}
            new={p.name:p.read_bytes() for p in stage.glob('*.json')}
            if old!=new:raise RuntimeError('同名配置内容不同，保留原目录；请核实热更序号')
        else:
            stage.rename(folder)
    log('解包完成：%d 张表（跳过非 JSON %d 张）→ %s'%(len(names),len(skipped),folder))
    log('关键表校验通过：'+'/'.join(KEY_TABLES))
    _clear_pause(root)
    return {'name':name,'folder':str(folder),'tables':len(names),'skipped':skipped}

def import_config(path,dest_root=None,log=print):
    path=Path(path)
    return install_config(path.read_bytes(),path.name,dest_root,log)

def sync(dest_root=None,log=print):
    """下载并解包本周最新配置；服务器没有新包时暂停到下周再检查。"""
    item=discover()
    if not item:raise RuntimeError('未发现可用配置（已回溯 %d 周）'%8)
    root=Path(dest_root or ROOT)
    local=latest_config_folder(root)
    if local is not None:
        server_key=_config_key(item['name']);local_key=_config_key(local.name)
        if server_key and local_key and server_key<=local_key:
            until=_next_check(item,local)
            _write_pause(root,until,item,local)
            log('服务器最新仍为 %s，本地已是 %s；本周暂停检查，下次 %s'
                %(item['name'],local.name,until.strftime('%m-%d %H:%M')))
            return {'name':item['name'],'folder':str(local),'tables':0,'skipped':[],
                    'up_to_date':True,'paused_until':until.isoformat()}
    _clear_pause(root)
    log('最新配置：%s（%.1f MB）'%(item['name'],item['size']/1048576))
    data=fetch(item['name'])
    log('下载完成：%d 字节'%len(data))
    return install_config(data,item['name'],dest_root,log)


def _startup_log(text):
    try:print(text,flush=True)
    except Exception:pass


def ensure_config():
    """GUI 启动前确保配置表存在且未过期；失败时继续，由界面后台重试。"""
    if os.environ.get('ZM5_CONFIG_PREFLIGHT_DONE')=='1':return
    os.environ['ZM5_CONFIG_PREFLIGHT_DONE']='1'
    local=latest_config_folder()
    if local is not None and not config_is_stale(local):return
    if local is not None and paused_until() is not None:
        _startup_log('配置表本周已检查，服务器暂无新包，直接启动。')
        os.environ['ZM5_CONFIG_PREFLIGHT']='1'
        return
    _startup_log('正在检查并更新配置表，请稍候...')
    try:
        result=sync(log=_startup_log)
    except Exception as exc:
        _startup_log('配置表更新失败：%s'%exc)
        _startup_log('继续启动，界面会在后台重试。')
        return
    os.environ['ZM5_CONFIG_PREFLIGHT']='1'
    if result.get('up_to_date'):
        _startup_log('服务器暂无新包，使用本地配置启动。')
    else:
        _startup_log('配置表已更新到 %s，启动程序。'%result['name'])


if __name__=='__main__':
    result=sync()
    print(json.dumps(result,ensure_ascii=False))
