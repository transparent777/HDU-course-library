"""BookingResult data model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BookingResult:
    """Result of a booking attempt."""
    success: bool
    code: str
    message: str
    plan_id: Optional[str] = None
    seat_num: Optional[str] = None
    room_name: Optional[str] = None
    target_date: Optional[str] = None

    def __str__(self) -> str:
        status = "成功" if self.success else "失败"
        parts = [f"[{status}]"]
        if self.plan_id:
            parts.append(f"方案: {self.plan_id}")
        if self.room_name and self.seat_num:
            parts.append(f"座位: {self.room_name}-{self.seat_num}")
        if self.target_date:
            parts.append(f"日期: {self.target_date}")
        parts.append(self.message)
        return " | ".join(parts)

    @classmethod
    def from_api_response(cls, resp: dict, plan_id: str = None, seat_num: str = None,
                          room_name: str = None, target_date: str = None) -> "BookingResult":
        code = resp.get("CODE", "unknown")
        message = resp.get("MESSAGE", "")
        return cls(
            success=(code == "ok"),
            code=code,
            message=message,
            plan_id=plan_id,
            seat_num=seat_num,
            room_name=room_name,
            target_date=target_date,
        )
