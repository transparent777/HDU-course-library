"""图书馆登录：杭电 CAS 统一认证（requests，无需 Playwright 浏览器包体）."""

from __future__ import annotations

import logging
from typing import List, Dict, Tuple, Optional

import requests
from bs4 import BeautifulSoup

from hdu_killer.course.crypto import aes_encrypt_cas
from hdu_killer.seat.auth.urls import cas_login_entry

logger = logging.getLogger("hdu_killer.seat.auth")

LOGIN_ERR_NETWORK = "network"
LOGIN_ERR_AUTH = "auth"

SSO_LOGIN = "https://sso.hdu.edu.cn/login"


def _parse_cas_form(html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    execution = soup.find("input", {"name": "execution"})
    croypto = soup.find("input", {"name": "croypto"})
    if not execution or not croypto:
        raise RuntimeError("CAS 页面缺少 execution/croypto，可能未跳转到统一认证")
    return execution.get("value", ""), croypto.get("value", "")


def login_via_cas(
    session: requests.Session,
    username: str,
    password: str,
    library_base: str,
) -> Tuple[bool, Optional[str], List[Dict], str, str]:
    """
    Returns: success, err_type, cookies(list for cookie_store), uid, name
    """
    session.verify = False
    session.headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    try:
        entry = cas_login_entry(library_base)
        logger.info("CAS: 打开登录入口 %s", entry)
        r = session.get(entry, timeout=60, allow_redirects=True)

        if "sso.hdu.edu.cn" not in r.url and "croypto" not in r.text:
            logger.info("HTTP 无法进入 CAS 页（需浏览器跳转），将尝试 Playwright")
            return False, LOGIN_ERR_AUTH, [], "", ""

        if "sso.hdu.edu.cn" in r.url or "croypto" in r.text:
            execution, croypto = _parse_cas_form(r.text)
            enc_pwd = aes_encrypt_cas(croypto, password)
            post_url = r.url if "sso.hdu.edu.cn" in r.url else SSO_LOGIN
            logger.info("CAS: 提交学号密码…")
            r = session.post(
                post_url,
                data={
                    "username": username,
                    "type": "UsernamePassword",
                    "_eventId": "submit",
                    "geolocation": "",
                    "execution": execution,
                    "captcha_code": "",
                    "croypto": croypto,
                    "password": enc_pwd,
                },
                timeout=60,
                allow_redirects=True,
            )

        if "huitu.zhishulib.com" not in r.url and not any(
            c.domain and "huitu.zhishulib.com" in c.domain for c in session.cookies
        ):
            if "统一身份认证" in r.text and "密码" in r.text:
                return False, LOGIN_ERR_AUTH, [], "", ""
            logger.error("CAS 登录后未回到图书馆，URL=%s", r.url)
            return False, LOGIN_ERR_AUTH, [], "", ""

        uid, name = _fetch_user(session, library_base)
        cookies = _cookies_for_store(session)
        if not uid or not cookies:
            return False, LOGIN_ERR_AUTH, [], "", ""
        logger.info("CAS 登录成功 uid=%s name=%s", uid, name)
        return True, None, cookies, uid, name

    except (requests.RequestException, ConnectionError, TimeoutError) as e:
        logger.error("CAS 网络错误: %s", e)
        return False, LOGIN_ERR_NETWORK, [], "", ""
    except Exception as e:
        logger.error("CAS 登录失败: %s", e)
        return False, LOGIN_ERR_AUTH, [], "", ""


def _fetch_user(session: requests.Session, library_base: str) -> Tuple[str, str]:
    url = library_base.rstrip("/") + "/Seat/Index/searchSeats"
    params = {
        "space_category[category_id]": "591",
        "space_category[content_id]": "3",
        "LAB_JSON": "1",
    }
    session.cookies.set("org_id", "104", domain=".huitu.zhishulib.com")
    resp = session.get(url, params=params, timeout=30)
    data = resp.json()
    if isinstance(data, dict) and data.get("data"):
        d = data["data"]
        return str(d.get("uid", "")), d.get("uname", "") or ""
    return "", ""


def _cookies_for_store(session: requests.Session) -> List[Dict]:
    out: List[Dict] = []
    for c in session.cookies:
        if c.domain and "huitu.zhishulib.com" in c.domain:
            out.append(
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path or "/",
                }
            )
    return out
