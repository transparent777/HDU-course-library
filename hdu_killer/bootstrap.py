"""Startup dependency checks."""

from __future__ import annotations

import sys
from importlib import import_module

from hdu_killer.paths import get_project_root, setup_runtime

_REQUIRED = (
    ("yaml", "PyYAML"),
    ("requests", "requests"),
    ("bs4", "beautifulsoup4"),
    ("Crypto", "pycryptodome"),
    ("customtkinter", "customtkinter"),
    ("PIL", "Pillow"),
)


def missing_dependencies() -> list[tuple[str, str]]:
    missing: list[tuple[str, str]] = []
    for mod, pip_name in _REQUIRED:
        try:
            import_module(mod)
        except ImportError:
            missing.append((mod, pip_name))
    return missing


def format_missing_message(missing: list[tuple[str, str]]) -> str:
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    root = get_project_root()
    return (
        f"缺少依赖（当前 Python {py}）：\n"
        + "\n".join(f"  - {pip}" for _, pip in missing)
        + f"\n\n请在项目目录执行：\n"
        f'  "{sys.executable}" -m pip install -r requirements.txt\n\n'
        f"图书馆抢座使用 API 登录，无需浏览器驱动。\n\n"
        f"项目路径：{root}"
    )


def prepare() -> None:
    setup_runtime()
