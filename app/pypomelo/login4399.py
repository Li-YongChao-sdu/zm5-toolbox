"""4399 平台：拿浏览器会话换游戏 token。

对应 AS: models/managers/PlatformManager.as
    tokeUrl = "https://save.api.4399.com/?ac=user_auth"
    POST  gameId=100051601  userId=<uid>  userName=<name>
    响应体(纯文本) = 游戏 token 字符串, 形如:
        99181269|99181269|991|1766803885575|c10fefe25e008af75cb3c3ee50af2093

注意:
- 这个请求必须带着已登录的 4399 cookie(至少 USESSIONID, 通常还有 Uauth/Pauth/Xauth)。
- cookie 从哪来: 正常浏览器登录一次后, 从开发者工具复制 cookie。
  本模块只负责"拿着 cookie 换游戏 token", 不做 ptlogin 账号密码登录。
- 参数(已实测, 2026-09):
    userId   = 数字 uid, 取自 cookie Pauth 第一段, 如 "266089266"
    userName = 登录账号(不是昵称!), 如 "xyh13416626694"
  传错会返回 "Error: user id error." / "Error: auth error."
- 返回 token 格式: uid|账号|昵称|毫秒时间戳|md5hex, 后续 pomelo auth 原样使用。
"""

import http.cookiejar
import urllib.parse
import urllib.request

USER_AUTH_URL = "https://save.api.4399.com/?ac=user_auth"
GAME_ID = "100051601"
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/53.0.2785.101 Safari/537.36")


def fetch_game_token(uid: str,
                     name: str,
                     cookies: dict,
                     game_id: str = GAME_ID,
                     referer: str = "https://sda.4399.com/4399swf/upload_swf/ftp22/csya/20170622/1/v4720g.htm",
                     timeout: float = 10.0) -> str:
    """带 4399 登录 cookie 换游戏 token。

    :param uid:    4399 用户 id(对应 cookie 里的 Puser)
    :param name:   用户名/昵称(对应 cookie 里的 Pnick)
    :param cookies:dict, 例如 {"USESSIONID": "...", "Puser": "...", "Pnick": "..."}
    :return:       游戏 token 原文(uid|...|ts|md5)
    """
    data = urllib.parse.urlencode({
        "gameId": game_id,
        "userId": uid,
        "userName": name,
    }).encode("utf-8")

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    req = urllib.request.Request(USER_AUTH_URL, data=data, method="POST")
    req.add_header("User-Agent", DEFAULT_UA)
    req.add_header("Referer", referer)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    # 直接把调用方 cookie 塞进请求头(跨域/简单起见, 不依赖 cookie jar 自动携带)
    req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()))

    with opener.open(req, timeout=timeout) as resp:
        token = resp.read().decode("utf-8", "replace").strip()

    # 对应 AS connectServer() 的合法性检查: 必须含 "|" 且长度 >=6
    if "|" not in token or len(token) < 6:
        raise RuntimeError("4399 user_auth 返回异常(可能 cookie 已失效): %r" % token)
    return token
