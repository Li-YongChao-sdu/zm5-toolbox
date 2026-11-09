"""从 4399 资源服下载本周配置包并解包为 JSON 表。

版本规则：以 2026-10-26 为基准每 7 天递增，周内热更时文件名序号 1→2→3。
输出目录：cg_config_out_cg1_<日期>_<序号>
"""
import json,lzma,struct,urllib.request,zlib,re,tempfile
from datetime import date,timedelta
from pathlib import Path
from game_version import beijing_now

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
    return {'name':name,'folder':str(folder),'tables':len(names),'skipped':skipped}

def import_config(path,dest_root=None,log=print):
    path=Path(path)
    return install_config(path.read_bytes(),path.name,dest_root,log)

def sync(dest_root=None,log=print):
    """下载并解包本周最新配置，返回 {name,folder,tables,skipped}。"""
    item=discover()
    if not item:raise RuntimeError('未发现可用配置（已回溯 %d 周）'%8)
    log('最新配置：%s（%.1f MB）'%(item['name'],item['size']/1048576))
    data=fetch(item['name'])
    log('下载完成：%d 字节'%len(data))
    return install_config(data,item['name'],dest_root,log)


if __name__=='__main__':
    result=sync()
    print(json.dumps(result,ensure_ascii=False))
