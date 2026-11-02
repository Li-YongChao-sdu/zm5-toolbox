"""收集生产依赖，不复制账号、Cookie、测试日志与本机配置。"""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent/'app'
WORK=Path(__file__).resolve().parent/'build_exe_20261004'
OUT=Path(__file__).resolve().parent/'exe_20261004_verified'
STAGE=WORK/'source'
STAGE.mkdir(parents=True, exist_ok=True)
pending=['gui.py','exe_entry.py']
seen=set()
excluded={'gui_config.py','account.local.json','account.enc','accounts.pwd','文件清单.json'}
while pending:
    rel=pending.pop()
    if rel in seen or rel in excluded: continue
    source=ROOT/rel
    if not source.is_file():raise RuntimeError('Missing '+rel)
    seen.add(rel)
    if source.suffix=='.py':
        tree=ast.parse(source.read_text(encoding='utf-8-sig'))
        for n in ast.walk(tree):
            modules=[]
            if isinstance(n,ast.Import): modules=[x.name for x in n.names]
            elif isinstance(n,ast.ImportFrom) and n.module:modules=[n.module]
            for module in modules:
                candidate=module.replace('.','/')+'.py'
                if (ROOT/candidate).is_file():pending.append(candidate)
                folder=ROOT/module.split('.')[0]
                if (folder/'__init__.py').is_file():
                    pending.extend(p.relative_to(ROOT).as_posix() for p in folder.rglob('*.py') if '__pycache__' not in p.parts)
            if isinstance(n,ast.Constant) and isinstance(n.value,str):
                if n.value.endswith(('.py','.json','.js')) and n.value not in excluded and (ROOT/n.value).is_file():
                    pending.append(n.value)
    dest=STAGE/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
for p in (ROOT/'feature_config').glob('*.json'):
    dest=STAGE/'feature_config'/p.name;dest.parent.mkdir(exist_ok=True);shutil.copy2(p,dest)
assert not any(Path(p).name.startswith('_probe') for p in seen), 'Production depends on probe'
hidden=sorted(p[:-3].replace('/','.') for p in seen if p.endswith('.py') and not p.endswith('__init__.py'))
required={'new_player_daily.py','celebration_daily.py','new_player_rewards.py','supply_filter.py','nine_tower.py','ptlogin_login.py','feature_ui.py'}
assert required<=seen, required-seen
print('PRODUCTION',len(seen),'files; CONFIGS',len(list((STAGE/'feature_config').glob('*.json'))),flush=True)
cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--console',
     '--name','造五活动助手','--distpath',str(OUT),'--workpath',str(WORK/'pyinstaller'),
     '--specpath',str(WORK),'--paths',str(STAGE),
     '--collect-binaries','Crypto','--hidden-import','Crypto.Cipher.AES']
for module in hidden:cmd+=['--hidden-import',module]
cmd+=[str(STAGE/'exe_entry.py')]
build_env=os.environ.copy()
build_env['PYTHONPATH']=str(STAGE)
subprocess.run(cmd,check=True,cwd=STAGE,env=build_env)
package=OUT/'造五活动助手'
for p in STAGE.rglob('*'):
    if not p.is_file() or '__pycache__' in p.parts:continue
    dest=package/p.relative_to(STAGE);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
(package/'使用说明.txt').write_text('双击“造五活动助手.exe”启动，无需安装Python。\n请保留整个文件夹，不能只移动exe。\n首次启动后自行用账密或Cookie登录。账号、配置和logs日志保存在此文件夹内。\n新手任务位于抓宠后面；庆典每日任务位于活动副本。\n',encoding='utf-8')
manifest={p.relative_to(package).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
          for p in package.rglob('*') if p.is_file() and p.name!='文件清单.json'}
(package/'文件清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('PACKAGE',package,'FILES',len(manifest),flush=True)
