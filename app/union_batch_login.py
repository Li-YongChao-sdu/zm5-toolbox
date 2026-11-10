"""联盟窗口独立登录；密码不保存，临时账号只走进程环境。"""
import json,threading
import tkinter as tk
from tkinter import ttk,messagebox
from http.cookies import SimpleCookie

def cookie_account(username,text):
    text=text.strip()
    try:value=json.loads(text)
    except ValueError:value=None
    if isinstance(value,dict):cookies=value.get('cookies',value)
    else:
        if isinstance(value,str):text=value
        elif len(text)>=2 and text[0]==text[-1] and text[0] in ('"',"'"):text=text[1:-1].strip()
        if text.lower().startswith('cookie:'):text=text.split(':',1)[1].strip()
        cookies={}
        # 浏览器Cookie中统计字段可能不符合SimpleCookie语法；只解析登录所需字段。
        allowed={'Pauth','Uauth','Xauth','USESSIONID','Puser','Pnick','ck_accname'}
        for part in text.split(';'):
            key,sep,val=part.strip().partition('=')
            if sep and key in allowed:
                val=val.strip()
                if len(val)>=2 and val[0]==val[-1] and val[0] in ('"',"'"):val=val[1:-1]
                cookies[key]=val
    required=('Pauth','Uauth','Xauth','USESSIONID')
    if not isinstance(cookies,dict):raise ValueError('Cookie格式错误，请粘贴请求头或JSON对象')
    missing=[k for k in required if not isinstance(cookies.get(k),str) or not cookies[k]]
    if missing:raise ValueError('Cookie缺少登录字段：'+', '.join(missing))
    uid=cookies['Pauth'].split('|',1)[0]
    if not uid.isdecimal():raise ValueError('无法从Pauth确认UID')
    username=username.strip() or cookies.get('ck_accname','') or cookies.get('Puser','')
    if not username:raise ValueError('请填写登录账号')
    keep={k:v for k,v in cookies.items() if k in (*required,'Puser')}
    return {'uid':uid,'username':username,'cookies':keep}

def open_login(owner):
    if owner.proc is not None or owner.login_busy:return
    d=tk.Toplevel(owner.root);d.title('联盟多账号独立登录')
    username=tk.StringVar();password=tk.StringVar();mode=tk.StringVar(value='账密登录');remember=tk.BooleanVar(value=True)
    ttk.Label(d,text='登录方式').pack(anchor='w');ttk.Combobox(d,textvariable=mode,values=('账密登录','Cookie登录'),state='readonly').pack(fill='x')
    ttk.Label(d,text='登录账号').pack(anchor='w');ttk.Entry(d,textvariable=username,width=40).pack(fill='x')
    ttk.Label(d,text='密码（不保存）').pack(anchor='w');ttk.Entry(d,textvariable=password,show='*').pack(fill='x')
    ttk.Label(d,text='Cookie：粘贴Cookie请求头或Cookie JSON').pack(anchor='w');cookie=tk.Text(d,width=54,height=5);cookie.pack(fill='both',expand=True)
    ttk.Checkbutton(d,text='保存账号（取消则仅本次使用）',variable=remember).pack(anchor='w')
    status=tk.StringVar();ttk.Label(d,textvariable=status,wraplength=400).pack()
    def submit():
        user=username.get().strip();pwd=password.get();text=cookie.get('1.0','end').strip();method=mode.get();save=remember.get()
        password.set('');cookie.delete('1.0','end');owner.login_busy=True;button.configure(state='disabled');status.set('正在登录…')
        def done(account,error):
            owner.login_busy=False
            if not d.winfo_exists():return
            button.configure(state='normal')
            if error:status.set(error);return
            owner.accept_login(account,save);d.destroy()
        def work():
            try:
                if method=='账密登录':
                    from ptlogin_login import login_by_password
                    result=login_by_password(user,pwd,verbose=False)
                    if not result.get('ok'):
                        error='需要验证码，请使用Cookie登录或在主程序完成验证码后导入' if result.get('need_captcha') else '登录未成功（%s），请检查网络或账号信息'%result.get('status','unknown')
                        owner.messages.put(('callback',lambda:done(None,error)));return
                    account={'uid':str(result['uid']),'username':user,'cookies':result['cookies']}
                else:
                    account=cookie_account(user,text)
                    from pypomelo.login4399 import fetch_game_token
                    fetch_game_token(account['uid'],account['username'],account['cookies'])
                owner.messages.put(('callback',lambda:done(account,None)))
            except Exception as exc:
                error=(str(exc) if isinstance(exc,ValueError) and str(exc).startswith(('Cookie','无法从Pauth','请填写登录账号')) else '登录校验失败（%s），未保存，请检查输入及网络'%type(exc).__name__)
                owner.messages.put(('callback',lambda:done(None,error)))
        threading.Thread(target=work,daemon=True).start()
    button=ttk.Button(d,text='登录并添加',command=submit);button.pack(pady=8)
