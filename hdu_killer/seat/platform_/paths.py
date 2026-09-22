"""Cross-platform path resolution."""

from __future__ import annotations

import os
import sys


def get_app_dir() -> str:
    """Get application root directory (PyInstaller-compatible)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # hdu_killer/seat/platform_/paths.py -> project root is three levels up
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def get_config_path(filename: str = "config.yaml") -> str:
    """Get path to a config file."""
    return os.path.join(get_app_dir(), "data", "seat", filename)


def get_log_dir() -> str:
    """Get or create the log directory."""
    log_dir = os.path.join(get_app_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_data_dir() -> str:
    """Get or create the data directory for persistent state."""
    data_dir = os.path.join(get_app_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir
