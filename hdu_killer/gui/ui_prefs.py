"""GUI 偏好：主题、字号、向导状态."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from hdu_killer.paths import get_data_dir

_DEFAULT: dict[str, Any] = {
    "appearance_mode": "system",
    "color_theme": "blue",
    "wizard_completed": False,
    "ui_scale": 1.0,
    "window_width": 900,
    "window_height": 680,
}


def prefs_path() -> Path:
    return get_data_dir() / "gui_prefs.json"


def load_ui_prefs() -> dict[str, Any]:
    path = prefs_path()
    if not path.is_file():
        return deepcopy(_DEFAULT)
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        out = deepcopy(_DEFAULT)
        if isinstance(data, dict):
            out.update(data)
        return out
    except Exception:
        return deepcopy(_DEFAULT)


def save_ui_prefs(data: dict[str, Any]) -> None:
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = deepcopy(_DEFAULT)
    merged.update(data)
    with path.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
