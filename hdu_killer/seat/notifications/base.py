"""Notification interface definition."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Notification(ABC):
    """Base class for notifications."""

    @abstractmethod
    def notify(self, title: str, message: str, sound: bool = True):
        """Send a notification."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this notification method is available."""
        pass
