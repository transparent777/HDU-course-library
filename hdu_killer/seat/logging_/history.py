"""Booking history logging in JSONL format."""

from __future__ import annotations

import json
import os
from datetime import datetime

from hdu_killer.seat.models.booking_result import BookingResult
from hdu_killer.seat.platform_.paths import get_log_dir


class HistoryLogger:
    """Logs booking results to a JSONL file (one JSON object per line)."""

    def __init__(self, log_dir: str = None):
        if log_dir is None:
            log_dir = get_log_dir()
        self.log_path = os.path.join(log_dir, "history.jsonl")

    def log(self, result: BookingResult):
        """Append a booking result to the history file."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "success": result.success,
            "code": result.code,
            "message": result.message,
            "plan_id": result.plan_id,
            "seat_num": result.seat_num,
            "room_name": result.room_name,
            "target_date": result.target_date,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def query(self, limit: int = 20, success_only: bool = False) -> list:
        """Read recent history entries.

        Args:
            limit: Maximum number of entries to return.
            success_only: Only return successful bookings.

        Returns:
            List of entry dicts, most recent first.
        """
        if not os.path.exists(self.log_path):
            return []

        entries = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if success_only and not entry.get("success"):
                        continue
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue

        return entries[-limit:][::-1]  # Most recent first
