"""Cookie persistence and expiry checking.

Extracted from killer.py:61-91.
"""

from __future__ import annotations

import json
import os
import logging
import datetime as dt
from typing import Optional, Dict, Any, List

logger = logging.getLogger("hdu_killer.seat.auth")

COOKIE_EXPIRY_DAYS = 20


class CookieStore:
    """Manages cookie persistence to local JSON file."""

    def __init__(self, cookie_path: str):
        self.cookie_path = cookie_path

    def save(self, cookies: List[Dict], uid: str, name: str):
        """Save cookies with metadata to local file."""
        data = {
            "saved_at": dt.datetime.now().isoformat(),
            "cookies": cookies,
            "uid": uid,
            "name": name,
        }
        os.makedirs(os.path.dirname(self.cookie_path), exist_ok=True)
        with open(self.cookie_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("Cookies saved to %s", self.cookie_path)

    def load(self) -> Optional[Dict[str, Any]]:
        """Load cookies from local file. Returns None if expired or missing."""
        if not os.path.exists(self.cookie_path):
            return None
        try:
            with open(self.cookie_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_at = dt.datetime.fromisoformat(data["saved_at"])
            if (dt.datetime.now() - saved_at).days >= COOKIE_EXPIRY_DAYS:
                logger.info("Cached cookies expired (saved %d days ago)", (dt.datetime.now() - saved_at).days)
                return None
            return data
        except Exception as e:
            logger.warning("Failed to load cookies: %s", e)
            return None

    def clear(self):
        """Delete the cookie file."""
        if os.path.exists(self.cookie_path):
            os.remove(self.cookie_path)
            logger.debug("Cookie file removed")
