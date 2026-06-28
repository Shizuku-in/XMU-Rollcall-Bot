"""
XMULogin - 厦门大学统一身份认证登录模块
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

提供厦门大学统一身份认证系统的登录功能。
集成自 xmulogin 1.0.1，不再需要外部依赖。

基本用法:
    >>> from xmulogin import xmulogin
    >>> session = xmulogin(type=1, username="your_username", password="your_password")
    >>> if session:
    ...     print("登录成功")
    ... else:
    ...     print("登录失败")
"""

import requests
import base64
import random
import re
from Crypto.Cipher import AES
from typing import Optional


# 常量定义
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/149.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://ids.xmu.edu.cn/authserver/login",
}

COOKIES = {
    'org.springframework.web.servlet.i18n.CookieLocaleResolver.LOCALE': 'zh_CN'
}

LOGIN_URL = "https://ids.xmu.edu.cn/authserver/login"
AES_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"


# 工具函数
def _random_string(n: int) -> str:
    """生成指定长度的随机字符串"""
    return ''.join(random.choice(AES_CHARS) for _ in range(n))


def _pad(data: str) -> str:
    """PKCS7填充"""
    pad_len = 16 - (len(data) % 16)
    return data + chr(pad_len) * pad_len


def _encrypt_password(password: str, salt: str) -> str:
    """使用AES加密密码"""
    plaintext = _random_string(64) + password
    key = salt.encode()
    iv = _random_string(16).encode()
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(_pad(plaintext).encode())
    return base64.b64encode(encrypted).decode()


# 核心登录函数
def _login_ids(username: str, password: str) -> Optional[requests.Session]:
    """
    登录厦门大学统一身份认证系统

    Args:
        username: 学号或工号
        password: 密码

    Returns:
        成功返回已登录的Session对象，失败返回None
    """
    s = requests.Session()

    try:
        res = s.post(LOGIN_URL, headers=HEADERS)
        html = res.text

        # 提取salt和execution
        salt = re.search(r'id="pwdEncryptSalt"\s+value="([^"]+)"', html).group(1)
        execution = re.search(r'name="execution"\s+value="([^"]+)"', html).group(1)

        # 加密密码
        enc = _encrypt_password(password, salt)

        # 提交登录表单
        data = {
            "username": username,
            "password": enc,
            "captcha": '',
            "_eventId": "submit",
            "cllt": "userNameLogin",
            "dllt": "generalLogin",
            "lt": '',
            "execution": execution
        }

        res2 = s.post(LOGIN_URL, headers=HEADERS, data=data, cookies=COOKIES, allow_redirects=False)

        if res2.status_code == 302:
            return s
        else:
            return None

    except Exception as e:
        print(f"统一身份认证登录失败: {e}")
        return None


def _login_jw(username: str, password: str) -> Optional[requests.Session]:
    """
    通过统一身份认证登录厦门大学教务系统

    Args:
        username: 学号或工号
        password: 密码

    Returns:
        成功返回已登录的Session对象，失败返回None
    """
    s = requests.Session()
    jw_param = {
        'service': 'https://jw.xmu.edu.cn/new/index.html'
    }

    try:
        res = s.post(LOGIN_URL, headers=HEADERS)
        html = res.text

        # 提取salt和execution
        salt = re.search(r'id="pwdEncryptSalt"\s+value="([^"]+)"', html).group(1)
        execution = re.search(r'name="execution"\s+value="([^"]+)"', html).group(1)

        # 加密密码
        enc = _encrypt_password(password, salt)

        # 提交登录表单
        data = {
            "username": username,
            "password": enc,
            "captcha": '',
            "_eventId": "submit",
            "cllt": "userNameLogin",
            "dllt": "generalLogin",
            "lt": '',
            "execution": execution
        }

        res2 = s.post(LOGIN_URL, headers=HEADERS, data=data, cookies=COOKIES,
                     allow_redirects=False, params=jw_param)

        if res2.status_code == 302:
            headers_2 = res2.headers
            location = headers_2['location']
            res3 = s.get(location, headers=HEADERS, allow_redirects=False)
            if res3.status_code == 302:
                return s

        return None

    except Exception as e:
        print(f"教务系统登录失败: {e}")
        return None


def _login_tronclass(username: str, password: str) -> Optional[requests.Session]:
    """
    通过统一身份认证登录厦门大学数字化教学平台(TronClass)

    Args:
        username: 学号或工号
        password: 密码

    Returns:
        成功返回已登录的Session对象，失败返回None
    """
    try:
        s = requests.Session()
        s.headers.update(HEADERS)
        s.cookies.update(COOKIES)

        login_page = s.get('https://lnt.xmu.edu.cn/login', allow_redirects=True, timeout=20)
        if login_page.status_code != 200:
            raise RuntimeError(f"无法打开统一身份认证页面，HTTP {login_page.status_code}")

        html = login_page.text
        salt_match = re.search(r'id="pwdEncryptSalt"\s+value="([^"]+)"', html)
        execution_match = re.search(r'name="execution"\s+value="([^"]+)"', html)
        if not salt_match or not execution_match:
            raise RuntimeError("无法从统一身份认证页面提取登录参数")

        salt = salt_match.group(1)
        execution = execution_match.group(1)
        enc = _encrypt_password(password, salt)
        # 提交登录表单
        data = {
            "username": username,
            "password": enc,
            "captcha": '',
            "_eventId": "submit",
            "cllt": "userNameLogin",
            "dllt": "generalLogin",
            "lt": '',
            "execution": execution
        }

        post_headers = HEADERS.copy()
        post_headers["Referer"] = login_page.url
        login_result = s.post(
            login_page.url,
            data=data,
            headers=post_headers,
            allow_redirects=True,
            timeout=20
        )
        if login_result.status_code >= 400:
            raise RuntimeError(f"登录跳转失败，HTTP {login_result.status_code}")

        profile = s.get("https://lnt.xmu.edu.cn/api/profile", headers=HEADERS, timeout=20)
        if profile.status_code == 200:
            try:
                profile_data = profile.json()
            except ValueError:
                profile_data = {}
            if isinstance(profile_data, dict) and "name" in profile_data:
                return s

        raise RuntimeError("登录未通过，账号密码可能错误，或统一身份认证需要验证码/二次验证")

    except Exception as e:
        print(f"数字化教学平台登录失败: {e}")
        return None


def xmulogin(type: int, username: str, password: str) -> Optional[requests.Session]:
    """
    厦门大学统一登录接口

    Args:
        type: 登录类型
            1 - 统一身份认证系统
            2 - 教务系统
            3 - 数字化教学平台(TronClass)
        username: 学号或工号
        password: 密码

    Returns:
        成功返回已登录的Session对象，失败返回None

    Raises:
        ValueError: 当type参数不在有效范围内时

    Example:
        >>> session = xmulogin(type=1, username="your_username", password="your_password")
        >>> if session:
        ...     # 使用session进行后续操作
        ...     response = session.get("https://ids.xmu.edu.cn/authserver/index.do")
        ...     print("登录成功")
        ... else:
        ...     print("登录失败")
    """
    if type == 1:
        return _login_ids(username, password)
    elif type == 2:
        return _login_jw(username, password)
    elif type == 3:
        return _login_tronclass(username, password)
    else:
        raise ValueError(f"无效的type参数: {type}。type必须为1(统一身份认证)、2(教务系统)或3(数字化教学平台)")
