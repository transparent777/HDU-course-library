"""Session manager: login orchestration and cookie auto-refresh."""

from __future__ import annotations

import logging
from typing import Optional, Tuple, Dict, List

import requests

from hdu_killer.seat.auth.cookie_store import CookieStore
from hdu_killer.seat.auth.library_api_login import (
    login_via_library_api,
    LOGIN_ERR_NETWORK,
)
from hdu_killer.seat.config.manager import ConfigManager
from hdu_killer.seat.platform_.paths import get_config_path

logger = logging.getLogger("hdu_killer.seat.auth")


def _session_cookies_as_list(session: requests.Session) -> List[Dict]:
    out: List[Dict] = []
    for c in session.cookies:
        out.append(
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path or "/",
            }
        )
    return out


class SessionManager:
    """Manages HTTP sessions with automatic login and cookie refresh."""

    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        self.session: Optional[requests.Session] = None
        self.cookie_store = CookieStore(get_config_path("session.json"))
        self.uid: str = ""
        self.name: str = ""
        self._cookie_login_network_err = False
        self.last_login_detail: str = ""

    @property
    def base_url(self) -> str:
        return self.config.get_api_base_url()

    @property
    def user_info(self) -> Dict[str, str]:
        return self.config.get_user_info()

    def init_session(self):
        """Initialize the requests session with configured headers."""
        import urllib3
        urllib3.disable_warnings()

        session_cfg = self.config.get_session_config()
        self.session = requests.Session()
        self.session.headers.clear()
        self.session.headers = session_cfg.get("headers", {})
        self.session.trust_env = session_cfg.get("trust_env", True)
        self.session.verify = session_cfg.get("verify", False)
        self.session.params = session_cfg.get("params", {})
        self.session.cookies.update({"org_id": self.config.get_user_info().get("org_id", "104")})

    def login(self) -> Tuple[bool, Optional[str]]:
        self._cookie_login_network_err = False
        self.last_login_detail = ""

        if self._login_with_cookies():
            return (True, None)

        if self._cookie_login_network_err:
            return (False, LOGIN_ERR_NETWORK)

        return self._login_with_library_api()

    def relogin(self) -> Tuple[bool, Optional[str]]:
        self.cookie_store.clear()
        self.last_login_detail = ""
        self.session.cookies.clear()
        self.session.cookies.update({"org_id": self.user_info.get("org_id", "104")})
        return self._login_with_library_api()

    def _apply_session_identity(self, uid: str, name: str) -> None:
        self.uid = uid or ""
        self.name = name or ""
        if not self.uid:
            self._fetch_user_info_from_api()
        self.cookie_store.save(_session_cookies_as_list(self.session), self.uid, self.name)

    def _login_with_library_api(self) -> Tuple[bool, Optional[str]]:
        success, err_type, uid, name, detail = login_via_library_api(
            self.session,
            self.user_info,
            self.base_url,
        )
        if not success:
            self.last_login_detail = detail or "图书馆账号或密码错误"
            return False, err_type
        self._apply_session_identity(uid, name)
        return True, None

    def _login_with_cookies(self) -> bool:
        cached = self.cookie_store.load()
        if not cached:
            return False

        logger.info("Found cached cookies, attempting to use...")
        cookie_dict = {c["name"]: c["value"] for c in cached["cookies"]}
        self.session.cookies.update(cookie_dict)
        self.uid = str(cached.get("uid", ""))
        self.name = cached.get("name", "")

        try:
            params = {
                "space_category[category_id]": "591",
                "space_category[content_id]": "3",
            }
            url = self.base_url + "/Seat/Index/searchSeats"
            resp = self.session.get(url=url, params=params, timeout=15)
            data = resp.json()
            if isinstance(data, dict) and data.get("data") and data["data"].get("uid"):
                self.uid = str(data["data"]["uid"])
                self.name = data["data"].get("uname", "")
                self.session.cookies.update({"org_id": "104"})
                logger.info("Cookie login successful: uid=%s, name=%s", self.uid, self.name)
                return True
            logger.info("Cookie validation failed, server returned: %s", json_dumps_truncate(data, 200))
        except (ConnectionResetError, ConnectionError, requests.exceptions.ConnectionError) as e:
            logger.warning("Cookie validation network error: %s", e)
            self._cookie_login_network_err = True
            return False
        except Exception as e:
            logger.warning("Cookie validation error: %s", e)

        logger.info("Cached cookies are invalid")
        return False

    def _fetch_user_info_from_api(self):
        try:
            params = {
                "space_category[category_id]": "591",
                "space_category[content_id]": "3",
            }
            url = self.base_url + "/Seat/Index/searchSeats"
            resp = self.session.get(url=url, params=params, timeout=15)
            data = resp.json()
            if isinstance(data, dict) and data.get("data"):
                self.uid = str(data["data"].get("uid", ""))
                self.name = data["data"].get("uname", "")
        except Exception:
            pass


def json_dumps_truncate(data, max_len=200):
    import json
    s = json.dumps(data, ensure_ascii=False)
    return s[:max_len] + "..." if len(s) > max_len else s
