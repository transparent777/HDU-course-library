"""Schedule data model - defines 'when to execute which plans'."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any

BOOKING_ADVANCE_DAYS = 2  # Seat for date X opens at (X-2) 20:00


@dataclass
class DateMapping:
    """A single date-to-plans mapping for 'dates' mode schedules."""
    target_date: str  # YYYY-MM-DD
    plan_ids: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {"target_date": self.target_date, "plan_ids": self.plan_ids}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DateMapping":
        return cls(
            target_date=data["target_date"],
            plan_ids=list(data["plan_ids"]),
        )


@dataclass
class Schedule:
    """A schedule that defines when plans should be executed.

    Two modes:
    - weekdays: Recurring on specific weekdays (1=Mon, 7=Sun)
    - dates: One-shot on specific dates with per-date plan bindings
    """
    mode: str  # "weekdays" or "dates"
    enabled: bool = True
    target_weekdays: List[int] = field(default_factory=list)  # 1-7 for weekdays mode
    plan_ids: List[str] = field(default_factory=list)  # For weekdays mode
    mappings: List[DateMapping] = field(default_factory=list)  # For dates mode

    def __post_init__(self):
        if self.mode not in ("weekdays", "dates"):
            raise ValueError(f"Invalid schedule mode: {self.mode}")
        if self.mode == "weekdays" and not self.target_weekdays:
            raise ValueError("weekdays mode requires target_weekdays")
        if self.mode == "dates" and not self.mappings:
            raise ValueError("dates mode requires mappings")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "mode": self.mode,
            "enabled": self.enabled,
        }
        if self.mode == "weekdays":
            d["target_weekdays"] = self.target_weekdays
            d["plan_ids"] = self.plan_ids
        else:
            d["mappings"] = [m.to_dict() for m in self.mappings]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Schedule":
        mappings = [DateMapping.from_dict(m) for m in data.get("mappings", [])]
        return cls(
            mode=data["mode"],
            enabled=data.get("enabled", True),
            target_weekdays=data.get("target_weekdays", []),
            plan_ids=data.get("plan_ids", []),
            mappings=mappings,
        )

    def next_trigger(self, now: datetime) -> Optional[Tuple[datetime, datetime, List[str]]]:
        """Calculate the next trigger time for this schedule.

        Returns:
            (trigger_time, target_date, plan_ids) or None if no future triggers.
            trigger_time = target_date - BOOKING_ADVANCE_DAYS at 20:00
        """
        if not self.enabled:
            return None

        if self.mode == "weekdays":
            return self._next_trigger_weekdays(now)
        elif self.mode == "dates":
            return self._next_trigger_dates(now)
        return None

    def _next_trigger_weekdays(self, now: datetime) -> Optional[Tuple[datetime, datetime, List[str]]]:
        """Find next trigger for weekday-based schedule."""
        # Convert 1-7 to Python weekday 0-6
        py_weekdays = [(w - 1) % 7 for w in self.target_weekdays]

        for delta in range(0, 14):
            candidate = (now + timedelta(days=delta)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if candidate.weekday() in py_weekdays:
                trigger = candidate.replace(hour=20, minute=0, second=0) - timedelta(
                    days=BOOKING_ADVANCE_DAYS
                )
                if trigger > now:
                    return (trigger, candidate, self.plan_ids)
        return None

    def _next_trigger_dates(self, now: datetime) -> Optional[Tuple[datetime, datetime, List[str]]]:
        """Find next trigger for date-based schedule."""
        best = None
        for mapping in self.mappings:
            target_date = datetime.strptime(mapping.target_date, "%Y-%m-%d")
            trigger = target_date.replace(hour=20, minute=0, second=0) - timedelta(
                days=BOOKING_ADVANCE_DAYS
            )
            if trigger > now:
                if best is None or trigger < best[0]:
                    best = (trigger, target_date, mapping.plan_ids)
        return best
