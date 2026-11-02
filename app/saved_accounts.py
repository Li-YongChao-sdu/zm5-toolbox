"""仅删除用户选定的本地账号记录，保留其他账号及密码密文。"""
import json
from pathlib import Path

def delete_saved_account(accounts_dir,name,password_file,current_file):
    root=Path(accounts_dir).resolve()
    if not name or '/' in name or '\\' in name:raise ValueError('账号名称无效')
    target=(root/(name+'.json')).resolve()
    if target.parent!=root:raise ValueError('账号路径无效')
    if not target.is_file():raise FileNotFoundError('选中的账号文件不存在')
    pwd=Path(password_file);current=Path(current_file)
    # Read before mutation so malformed data cannot erase unrelated credentials.
    passwords=json.loads(pwd.read_text(encoding='utf-8-sig')) if pwd.exists() else {}
    active=json.loads(current.read_text(encoding='utf-8-sig')) if current.exists() else {}
    if not isinstance(passwords,dict) or not isinstance(active,dict):raise ValueError('本地账号文件格式错误，未删除')
    if name in passwords:
        del passwords[name]
        temp=pwd.with_name(pwd.name+'.tmp')
        temp.write_text(json.dumps(passwords,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(pwd)
    if str(active.get('username',''))==name:current.unlink()
    target.unlink()
