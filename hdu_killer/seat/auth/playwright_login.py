"""Playwright 登录（备用）：处理 CAS 跳转与页面加载较慢的情况."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import logging
from typing import Optional, Tuple, List, Dict

from hdu_killer.seat.auth.urls import cas_login_entry

logger = logging.getLogger("hdu_killer.seat.auth")

LOGIN_ERR_NETWORK = "network"
LOGIN_ERR_AUTH = "auth"


def playwright_login(
    username: str,
    password: str,
    library_url: str,
    base_url: str,
) -> Tuple[bool, Optional[str], Optional[List[Dict]], Optional[str], Optional[str], str]:
    """Returns: success, err_type, cookies, uid, name, detail_message"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return (False, LOGIN_ERR_AUTH, None, "", "", "未安装 playwright")

    async def _launch_browser(p):
        candidates: list[dict] = []
        if sys.platform == "win32":
            candidates.extend([{"channel": "msedge"}, {"channel": "chrome"}])
        else:
            candidates.extend([{"channel": "chrome"}, {"channel": "msedge"}])
        candidates.append({})
        last_err: Exception | None = None
        for opts in candidates:
            try:
                return await p.chromium.launch(headless=True, **opts)
            except Exception as e:
                last_err = e
        raise RuntimeError("无法启动 Edge/Chrome") from last_err

    async def _fill_visible(page, selector: str, value: str) -> bool:
        loc = page.locator(selector)
        count = await loc.count()
        for i in range(count):
            item = loc.nth(i)
            if await item.is_visible():
                await item.fill(value)
                return True
        return False

    async def _login():
        async with async_playwright() as p:
            browser = await _launch_browser(p)
            context = await browser.new_context()
            page = await context.new_page()
            entry = cas_login_entry(base_url or library_url.rstrip("/"))
            logger.info("Playwright: 打开 CAS 入口 %s", entry)
            try:
                await page.goto(entry, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_url("**sso.hdu.edu.cn**", timeout=90000)
            except Exception as e:
                await browser.close()
                return False, LOGIN_ERR_NETWORK, None, "", "", f"无法打开统一认证: {e}"

            logger.info("Playwright: 当前页 %s", page.url[:80])

            if not await _fill_visible(page, 'input[name="username"]', str(username)):
                if not await _fill_visible(page, "input[formcontrolname=username]", str(username)):
                    await browser.close()
                    return False, LOGIN_ERR_AUTH, None, "", "", "找不到学号输入框（可能未连上校园网/VPN）"

            if not await _fill_visible(page, 'input[name="password"]', str(password)):
                if not await _fill_visible(page, "input[type=password]", str(password)):
                    await browser.close()
                    return False, LOGIN_ERR_AUTH, None, "", "", "找不到密码输入框"

            clicked = False
            for sel in ('button[type="submit"]', 'button:has-text("登录")', 'input[type="submit"]'):
                btn = page.locator(sel).first
                if await btn.count() and await btn.is_visible():
                    await btn.click()
                    clicked = True
                    break
            if not clicked:
                await browser.close()
                return False, LOGIN_ERR_AUTH, None, "", "", "找不到登录按钮"

            try:
                await page.wait_for_url("**/huitu.zhishulib.com/**", timeout=60000)
            except Exception:
                await asyncio.sleep(5)

            if "huitu.zhishulib.com" not in page.url:
                await browser.close()
                return False, LOGIN_ERR_AUTH, None, "", "", f"登录未成功，停留在: {page.url[:120]}"

            if "/Use" in page.url and "ticket=" in page.url:
                await browser.close()
                return (
                    False,
                    LOGIN_ERR_AUTH,
                    None,
                    "",
                    "",
                    "CAS 回调到了错误地址 /Use（请更新程序；应使用 /User/Index/hduCASLogin 登录）",
                )

            all_cookies = await context.cookies()
            lib_cookies = [c for c in all_cookies if "huitu.zhishulib.com" in c.get("domain", "")]
            uid, name = "", ""
            try:
                resp_text = await page.evaluate(
                    """async () => {
                    const resp = await fetch("/Seat/Index/searchSeats?space_category[category_id]=591&space_category[content_id]=3&LAB_JSON=1");
                    return await resp.text();
                }"""
                )
                data = json.loads(resp_text)
                if isinstance(data, dict) and data.get("data"):
                    uid = str(data["data"].get("uid", ""))
                    name = data["data"].get("uname", "")
            except Exception as e:
                logger.warning("Playwright 获取用户信息失败: %s", e)

            await browser.close()
            if not lib_cookies:
                return False, LOGIN_ERR_AUTH, None, "", "", "未获取到图书馆 Cookie"
            return True, None, lib_cookies, uid, name, ""

    try:
        result = asyncio.run(_login())
        return result
    except Exception as e:
        logger.exception("Playwright login")
        return False, LOGIN_ERR_NETWORK, None, "", "", str(e)
