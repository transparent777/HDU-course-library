from __future__ import annotations

import unittest
from unittest.mock import patch

from hdu_killer.course.jw_client import JwClient


def config(*, cookies_enabled: bool = False) -> dict:
    return {
        "cas_login": {
            "username": "student",
            "password": "secret",
            "dingDingQrLoginEnabled": "0",
            "level": "0",
        },
        "newjw_login": {
            "username": "student",
            "password": "secret",
            "level": "1",
        },
        "cookies": {
            "JSESSIONID": "saved-session" if cookies_enabled else "",
            "route": "saved-route" if cookies_enabled else "",
            "enabled": "1" if cookies_enabled else "0",
        },
    }


class CourseLoginBaselineTests(unittest.TestCase):
    def test_requests_session_keeps_default_network_behavior(self) -> None:
        client = JwClient()

        self.assertTrue(client.session.trust_env)
        self.assertTrue(client.session.verify)

    def test_valid_saved_cookies_are_verified_on_selection_page(self) -> None:
        client = JwClient()
        cfg = config(cookies_enabled=True)

        with (
            patch.object(client, "fetch_body_config") as verify_cookie,
            patch.object(client, "cas_login_password") as cas_login,
            patch.object(client, "newjw_login") as direct_login,
        ):
            client.login_flow(cfg)

        verify_cookie.assert_called_once_with()
        cas_login.assert_not_called()
        direct_login.assert_not_called()

    def test_expired_cookie_falls_back_to_original_cas_flow(self) -> None:
        client = JwClient()
        cfg = config(cookies_enabled=True)

        with (
            patch.object(
                client,
                "fetch_body_config",
                side_effect=RuntimeError("可能登录过期"),
            ),
            patch.object(client, "cas_login_password") as cas_login,
            patch.object(
                client,
                "cas_login_newjw",
                return_value="杭州电子科技大学本科教学管理服务平台",
            ) as cas_newjw,
            patch.object(client, "newjw_login") as direct_login,
        ):
            client.login_flow(cfg)

        cas_login.assert_called_once_with("student", "secret")
        cas_newjw.assert_called_once_with()
        direct_login.assert_not_called()

    def test_non_expiry_cookie_error_is_not_hidden(self) -> None:
        client = JwClient()
        cfg = config(cookies_enabled=True)

        with patch.object(
            client,
            "fetch_body_config",
            side_effect=RuntimeError("当前不属于选课阶段"),
        ):
            with self.assertRaisesRegex(RuntimeError, "当前不属于选课阶段"):
                client.login_flow(cfg)


if __name__ == "__main__":
    unittest.main()
