"""Window management - graceful degradation on non-Windows platforms."""

from __future__ import annotations

import sys
import logging

logger = logging.getLogger("hdu_killer.seat.platform")


def maximize_window():
    """Maximize console window on Windows, no-op elsewhere."""
    if sys.platform == "win32":
        try:
            import win32gui
            import win32con
            hwnd = win32gui.GetForegroundWindow()
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        except ImportError:
            logger.debug("pywin32 not available, skipping window maximize")
        except Exception as e:
            logger.debug("Failed to maximize window: %s", e)


def hide_console():
    """Hide the console window (Windows GUI mode)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(
                ctypes.windll.kernel32.GetConsoleWindow(), 0  # SW_HIDE
            )
        except Exception:
            pass
