"""Course selection config (config.json)."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from hdu_killer.paths import get_course_config_path, get_course_data_dir, get_project_root

DEFAULT: dict[str, Any] = {
    "cas_login": {
        "username": "",
        "password": "",
        "dingDingQrLoginEnabled": "0",
        "level": "0",
    },
    "newjw_login": {"username": "", "password": "", "level": "1"},
    "user_agent": "",
    "cookies": {"JSESSIONID": "", "route": "", "enabled": "1"},
    "time": {"XueNian": "2025", "XueQi": "1"},
    "course": {},
    "wait_course": {"interval": 60, "enabled": "0"},
    "smtp_email": {
        "host": "smtp.qq.com",
        "username": "",
        "password": "",
        "to": "",
        "enabled": "0",
    },
    "start_time": "2025-09-01 12:00:00",
}


def _example_path() -> Path:
    p = get_project_root() / "data" / "course" / "config.example.json"
    if p.is_file():
        return p
    return get_course_config_path()


def ensure_config() -> Path:
    path = get_course_config_path()
    if not path.is_file():
        ex = _example_path()
        if ex.is_file():
            shutil.copy(ex, path)
        else:
            path.write_text(json.dumps(DEFAULT, indent=4, ensure_ascii=False), encoding="utf-8")
    return path


def load_config() -> dict[str, Any]:
    path = ensure_config()
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("course"), dict):
        data["course"] = {}
    return data


def save_config(data: dict[str, Any]) -> None:
    get_course_data_dir().mkdir(parents=True, exist_ok=True)
    with get_course_config_path().open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def course_items(data: dict[str, Any]) -> list[tuple[str, str]]:
    return list((data.get("course") or {}).items())


def set_course_items(data: dict[str, Any], items: list[tuple[str, str]]) -> dict[str, Any]:
    out = deepcopy(data)
    out["course"] = {k: v for k, v in items if k.strip()}
    return out


def validate_config(cfg: dict[str, Any]) -> None:
    cas = cfg.get("cas_login", {})
    nj = cfg.get("newjw_login", {})
    if not (
        (cas.get("username") and cas.get("password"))
        or (nj.get("username") and nj.get("password"))
    ):
        raise ValueError("请填写 CAS 或教务账号密码")
    tm = cfg.get("time", {})
    if not tm.get("XueNian") or not tm.get("XueQi"):
        raise ValueError("请填写学年、学期")
    if not cfg.get("course"):
        raise ValueError("课程列表不能为空")
