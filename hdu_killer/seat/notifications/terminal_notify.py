"""Terminal notification: colored output + beep."""

from __future__ import annotations

import sys

from hdu_killer.seat.notifications.base import Notification
from hdu_killer.seat.ui.display import colorize, Color, print_success, print_error


class TerminalNotification(Notification):
    """Terminal-based notification with colored output and optional beep."""

    def notify(self, title: str, message: str, sound: bool = True):
        """Print a colored notification to the terminal."""
        if "成功" in title or "成功" in message:
            print_success(f"{title}: {message}")
        elif "失败" in title or "错误" in title or "失败" in message:
            print_error(f"{title}: {message}")
        else:
            print(f"{colorize(title, Color.BOLD)}: {message}")

        if sound:
            self._beep()

    def is_available(self) -> bool:
        return True  # Terminal is always available

    def _beep(self):
        """Produce a terminal bell character."""
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass
