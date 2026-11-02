# -*- coding: utf-8 -*-
"""4399 账密直登: 输入 账号/密码 -> 自动登录 ptlogin -> 提取游戏需要的 5 个 cookie。
密码加密复刻自 ptlogin 官方 validation.js:
    CryptoJS.AES.encrypt(明文密码, 'lzYW5qaXVqa').toString()
即 OpenSSL 兼容: 随机8字节salt + EVP_BytesToKey(MD5) 派生 key/iv + AES-256-CBC,
输出 Base64("Salted__"+salt+密文), 形如 U2FsdGVkX1...
"""
import os, base64, hashlib, re, sys, html

CIPHER = b"lzYW5qaXVqa"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/53.0.2785.101 Safari/537.36")

LOGIN_URL = "https://ptlogin.4399.com/ptlogin/login.do?v=1"
VERIFY_URL = "https://ptlogin.4399.com/ptlogin/verify.do"


def _evp_bytes_to_key(password: bytes, salt: bytes, key_len=32, iv_len=16):
    """OpenSSL EVP_BytesToKey (MD5), 与 CryptoJS 默认一致。"""
    d = b""; out = b""
    while len(out) < key_len + iv_len:
        d = hashlib.md5(d + password + salt).digest()
        out += d
    return out[:key_len], out[key_len:key_len + iv_len]


def encrypt_password(plain: str) -> str:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key(CIPHER, salt)
    ct = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(plain.encode("utf-8"), 16))
    return base64.b64encode(b"Salted__" + salt + ct).decode()


def _jar_cookies(cj):
    """把 requests CookieJar 扁平成 {name: value}。"""
    out = {}
    for c in cj:
        out[c.name] = c.value
    return out


def login_by_password(username: str, password: str, session_id: str = "", captcha: str = "", verbose=True, progress=None, captcha_prompt=None):
    """账密登录。返回 dict:
      成功: {"ok":True, "cookies":{USESSIONID,Uauth,Pauth,Xauth,Puser,...}, "raw":{...}}
      需验证码: {"need_captcha": True}
      失败: {"ok":False, "error": "..."}
    """
    import requests
    s = requests.Session()
    try:
        s.headers.update({"User-Agent": UA,
                           "Referer": "https://ptlogin.4399.com/ptlogin/loginFrame.do?appId=dev4399&v=1"})

        def precheck_progress(message):
            if verbose:
                print('[验证码预检查] ' + message, flush=True)
            if progress:
                progress(message)
        server_challenged=False
        while True:
            verification = check_verify(username, session=s, progress=precheck_progress)
            if verbose:
                print('[账密登录] 验证码预检查：' + verification['message'])
            if verification.get('need') is None:
                return {'ok':False, 'status':'verify_error', 'error':verification['message'], 'verification':verification}
            if server_challenged and verification.get('need') is False:
                return {'ok':False,'status':'captcha_required','need_captcha':True,
                        'error':'服务器要求验证码，但未取得有效图片，请重新登录','verification':verification}
            if verification.get('need') and not captcha:
                if captcha_prompt is None:
                    return {'ok':False, 'status':'captcha_required', 'need_captcha':True,
                            'error':'需要手动输入图片验证码', 'verification':verification}
                try:
                    answer = captcha_prompt(verification, lambda: download_captcha_image(verification['img_url'], session=s))
                except requests.RequestException as exc:
                    return {'ok':False, 'status':'network_error', 'error':'验证码图片获取失败（%s）'%type(exc).__name__}
                if not answer:
                    return {'ok':False, 'status':'cancelled', 'error':'已取消验证码登录'}
                captcha = str(answer).strip()
                session_id = verification['session_id']
            enc = encrypt_password(password)

            data = {
                "loginFrom": "uframe", "postLoginHandler": "refreshParent", "layoutSelfAdapting": "true",
                "externalLogin": "", "displayMode": "popup", "layout": "vertical", "bizId": "1202010640",
                "appId": "dev4399", "gameId": "", "css": "", "redirectUrl": "",
                "sessionId": "", "mainDivId": "popup_login_div", "includeFcmInfo": "false",
                "level": "4", "regLevel": "4", "sec": "1", "password": enc,
                "iframeId": "popup_login_frame", "username": username, "autoLogin": "true",
                "sessionId": session_id, "captcha": captcha,
            }
            if captcha:
                data['sessionId'] = session_id or verification.get('session_id', '')
                data['inputCaptcha'] = captcha
            try:
                r = s.post(LOGIN_URL, data=data, allow_redirects=True, timeout=20)
                r.raise_for_status()
            except requests.RequestException as exc:
                return {'ok':False, 'status':'network_error', 'error':'登录请求失败（%s）'%type(exc).__name__, 'verification':verification}
            text = r.text or ""
            cks = _jar_cookies(s.cookies)

            required = ('USESSIONID','Uauth','Pauth','Xauth')
            uid = str(cks.get('Pauth','')).split('|',1)[0]
            if all(cks.get(k) for k in required) and uid.isdigit():
                return {'ok':True, 'status':'success', 'uid':uid,
                        'cookies':{k:cks.get(k,'') for k in (*required,'Puser')}, 'raw':cks,
                        'verification':verification}
            status, message = classify_login_error(text)
            if status=='captcha_required' and captcha_prompt is not None:
                captcha='';session_id='';server_challenged=True
                precheck_progress('验证码错误或已失效，请输入新的验证码')
                continue
            return {'ok':False, 'status':status, 'error':message,
                    'need_captcha':status=='captcha_required', 'verification':verification}
    finally:
        s.close()


def classify_login_error(text):
    text = re.sub(r'<script\b[^>]*>.*?</script>', '', text or '', flags=re.I|re.S)
    text = html.unescape(re.sub(r'<[^>]+>', ' ', text))
    text = re.sub(r'\s+', ' ', text).strip()
    if re.search(r'(验证码|校验码).{0,12}(错误|不正确|不能为空|失效|过期)|请输入.{0,4}(验证码|校验码)|captcha\s*(error|invalid|required)',text,re.I):
        return 'captcha_required','服务器要求验证码或验证码已失效'
    if re.search(r'(账号|帐号|用户名|密码).{0,12}(错误|不正确|不存在)|密码不匹配',text):
        return 'credentials_error','服务器提示账号或密码错误'
    if re.search(r'请稍后再试|频繁|异地|安全验证|短信|手机验证|冻结|封禁|限制',text):
        return 'login_restricted','服务器限制登录或要求其他验证；不能据此认定为图片验证码'
    return 'unknown_error','服务器未返回完整登录票据，原因未确认'


def check_verify(username: str, app_id: str = 'dev4399', session=None, progress=None):
    """need为None表示查询失败或未知，不能当作无需验证码。"""
    import requests, time
    owned = session is None
    s = session or requests.Session()
    page_url='https://ptlogin.4399.com/ptlogin/loginFrame.do?appId=%s&v=1'%app_id
    s.headers.update({'User-Agent':UA,'Referer':page_url})
    phase = '登录页面'
    attempts = {}
    def get(url, label, **kwargs):
        nonlocal phase
        phase = label
        for attempt in range(1, 3):
            attempts[label] = attempt
            if progress:
                progress('%s：第%d/2次请求' % (label, attempt))
            try:
                reply = s.get(url, timeout=(8, 20), **kwargs)
                reply.raise_for_status()
                return reply
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == 2:
                    raise
                if progress:
                    progress('%s出现%s，1秒后重试一次' % (label, type(exc).__name__))
                time.sleep(1)
    try:
        get(page_url, '登录页面')
        reply = get(VERIFY_URL, '验证码接口', params={'username':username,'appId':app_id,
                    't':str(int(time.time()*1000)),'inputWidth':'iptw2'})
        fragment=html.unescape(reply.text or '').strip()
        if fragment=='0':
            return {'need':False,'status':'not_required','message':'当前不要求图片验证码'}
        match=re.search(r"captchaId=([^\"'&\s>]+)",fragment)
        if match:
            captcha_id=match.group(1)
            return {'need':True,'status':'required','session_id':captcha_id,
                    'img_url':'https://ptlogin.4399.com/ptlogin/captcha.do?captchaId='+requests.utils.quote(captcha_id,safe=''),
                    'message':'已检测到图片验证码'}
        return {'need':None,'status':'unknown','message':'验证码查询返回无法识别，停止自动登录'}
    except requests.RequestException as exc:
        return {'need':None,'status':'query_failed','phase':phase,'attempts':attempts.get(phase, 1),
                'message':'%s查询失败（%s，已请求%d次），验证码状态未知，停止自动登录' %
                          (phase, type(exc).__name__, attempts.get(phase, 1))}
    finally:
        if owned:s.close()


def download_captcha_image(img_url: str, session=None) -> bytes:
    """图片与验证码提交复用同一Session；独立调用时关闭临时Session。"""
    import requests,time
    owned=session is None
    s=session or requests.Session()
    try:
        r=s.get(img_url, params={'_':str(time.time_ns())},
                headers={'User-Agent':UA,'Referer':'https://ptlogin.4399.com/'},timeout=(8,15))
        r.raise_for_status()
        if not r.content:raise requests.RequestException('验证码图片为空')
        return r.content
    finally:
        if owned:s.close()


if __name__ == "__main__":
    # 自测: 只验证加密输出格式, 不碰真实账号
    sample = encrypt_password("test123")
    print("加密样例:", sample)
    assert sample.startswith("U2FsdGVkX1"), "AES 输出不是 OpenSSL Salted 格式!"
    print("格式校验通过: U2FsdGVkX1... = OpenSSL AES(与CryptoJS一致)")
