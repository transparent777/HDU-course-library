"""图书馆座位系统 API 路径。"""

from __future__ import annotations

from hdu_killer.seat.config.schema import API_ENDPOINTS


def library_login_url(base_url: str) -> str:
    return base_url.rstrip("/") + API_ENDPOINTS["login"]


def cas_login_entry(base_url: str) -> str:
    """已废弃（CAS）；保留仅供旧模块引用。"""
    return library_login_url(base_url)
