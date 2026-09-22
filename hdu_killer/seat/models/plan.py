"""Plan and SeatInfo data models with validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class SeatInfo:
    """A single seat within a plan."""
    seat_id: str
    seat_num: str

    def to_dict(self) -> Dict[str, str]:
        return {"seat_id": self.seat_id, "seat_num": self.seat_num}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SeatInfo":
        return cls(seat_id=str(data["seat_id"]), seat_num=str(data["seat_num"]))


@dataclass
class Plan:
    """A booking plan template - defines 'what to book' (seat, time, duration).

    Note: begin_time is a time template (HH:MM:SS) without a date.
    The scheduler fills in the actual date at execution time.
    """
    id: str
    room_name: str
    floor_name: str
    begin_time: str  # HH:MM:SS format, e.g. "08:00:00"
    duration_hours: int
    seats: List[SeatInfo] = field(default_factory=list)

    # Populated at execution time by the engine
    _room_data: Optional[Dict] = field(default=None, repr=False)

    def __post_init__(self):
        # Validate time format
        if not re.match(r"^\d{2}:\d{2}:\d{2}$", self.begin_time):
            raise ValueError(f"Invalid begin_time format: {self.begin_time}, expected HH:MM:SS")
        if self.duration_hours < 1:
            raise ValueError(f"Duration must be >= 1 hour, got {self.duration_hours}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "room_name": self.room_name,
            "floor_name": self.floor_name,
            "begin_time": self.begin_time,
            "duration_hours": self.duration_hours,
            "seats": [s.to_dict() for s in self.seats],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        seats = [SeatInfo.from_dict(s) for s in data.get("seats", [])]
        return cls(
            id=data["id"],
            room_name=data["room_name"],
            floor_name=data["floor_name"],
            begin_time=data["begin_time"],
            duration_hours=int(data["duration_hours"]),
            seats=seats,
        )

    def validate(self, room_data: Optional[Dict] = None) -> List[str]:
        """Validate plan against room data. Returns list of warning strings."""
        warnings = []
        # Library closes at 22:00, start_time + duration must not exceed 22:00
        start_hour = int(self.begin_time.split(":")[0])
        if start_hour + self.duration_hours > 22:
            warnings.append(
                f"方案 '{self.id}': 开始时间({start_hour}:00) + 使用时长({self.duration_hours}小时) = "
                f"{start_hour + self.duration_hours}:00，超过了图书馆最晚预约时间22:00"
            )
        if room_data is not None:
            # Check time is within room hours
            range_info = room_data.get("range", {})
            min_hour = range_info.get("minBeginTime")
            max_hour = range_info.get("maxEndTime")
            if min_hour is not None and max_hour is not None:
                hour = int(self.begin_time.split(":")[0])
                if hour < min_hour or hour > max_hour:
                    warnings.append(
                        f"Plan '{self.id}': begin_time {self.begin_time} is outside "
                        f"room hours ({min_hour}:00-{max_hour}:00)"
                    )
                max_duration = max_hour - hour
                if self.duration_hours > max_duration:
                    warnings.append(
                        f"Plan '{self.id}': duration {self.duration_hours}h exceeds "
                        f"available {max_duration}h from {self.begin_time}"
                    )
        if not self.seats:
            warnings.append(f"Plan '{self.id}': no seats defined")
        return warnings
