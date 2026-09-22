"""Sound notification: cross-platform beep."""

from __future__ import annotations

import sys
import logging

from hdu_killer.seat.notifications.base import Notification

logger = logging.getLogger("hdu_killer.seat.notifications")


class SoundNotification(Notification):
    """Sound notification using platform-native methods."""

    def notify(self, title: str, message: str, sound: bool = True):
        """Play a notification sound."""
        if sound:
            self._play_sound()

    def is_available(self) -> bool:
        return True

    def _play_sound(self):
        """Play a system beep sound."""
        try:
            if sys.platform == "win32":
                import winsound
                winsound.Beep(1000, 500)  # 1000Hz for 500ms
            else:
                # Terminal bell as fallback
                sys.stdout.write("\a")
                sys.stdout.flush()
        except Exception as e:
            logger.debug("Sound notification failed: %s", e)
