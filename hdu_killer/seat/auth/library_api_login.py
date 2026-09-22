"""图书馆座位系统账号密码登录。"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import requests

from hdu_killer.seat.config.schema import API_ENDPOINTS

logger = logging.getLogger("hdu_killer.seat.auth")

LOGIN_ERR_NETWORK = "network"
LOGIN_ERR_AUTH = "auth"


def login_via_library_api(
    session: requests.Session,
    user_info: Dict[str, str],
    base_url: str,
) -> Tuple[bool, Optional[str], str, str, str]:
    """返回 (成功, 错误类型, uid, name, 用户可见说明)."""
    login_name = user_info.get("login_name", "").strip()
    password = user_info.get("password", "")
    if not login_name or not password:
        return False, LOGIN_ERR_AUTH, "", "", "请填写学号与图书馆登录密码"

    url = base_url.rstrip("/") + API_ENDPOINTS["login"]
    payload = {
        "login_name": login_name,
        "password": password,
        "org_id": user_info.get("org_id", "104"),
    }
    try:
        logger.info("图书馆 API 登录: %s", url)
        resp = session.post(url=url, data=payload, timeout=30)
        data: Dict[str, Any] = resp.json()
        if data.get("CODE") == "ok":
            uid = str(data["DATA"]["uid"])
            name = data["DATA"]["user_info"]["name"]
            logger.info("图书馆 API 登录成功 uid=%s name=%s", uid, name)
            return True, None, uid, name, ""
        message = data.get("MESSAGE") or data.get("message") or "账号或密码错误"
        logger.warning("图书馆 API 登录失败: %s", message)
        return False, LOGIN_ERR_AUTH, "", "", str(message)
    except (ConnectionResetError, ConnectionError, requests.exceptions.ConnectionError) as e:
        logger.error("图书馆 API 网络错误: %s", e)
        return False, LOGIN_ERR_NETWORK, "", "", "无法连接图书馆服务器，请检查校园网/VPN"
    except requests.exceptions.Timeout:
        return False, LOGIN_ERR_NETWORK, "", "", "连接图书馆超时，请检查网络"
    except Exception as e:
        logger.exception("图书馆 API 登录异常")
        return False, LOGIN_ERR_AUTH, "", "", str(e)
