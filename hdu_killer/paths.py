"""Unified application paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    p = get_project_root() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_seat_config_path() -> Path:
    d = get_data_dir() / "seat"
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.yaml"


def get_course_data_dir() -> Path:
    d = get_data_dir() / "course"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_course_config_path() -> Path:
    return get_course_data_dir() / "config.json"


def get_seat_manual_path() -> Path:
    return get_project_root() / "docs" / "图书馆抢座使用手册.txt"


def get_course_manual_path() -> Path:
    return get_project_root() / "docs" / "教务抢课使用手册.txt"


def setup_runtime() -> Path:
    root = get_project_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    try:
        os.chdir(root)
    except OSError:
        pass
    return root
