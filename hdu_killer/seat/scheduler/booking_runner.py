"""Booking runner: execute bookings with retry logic.

Extracted from main.py:157-172 (startNow) and killer.py:416-422 (run).
"""

from __future__ import annotations

import logging
from datetime import datetime
from time import sleep
from typing import List, Callable, Optional

from hdu_killer.seat.api.client import ApiClient
from hdu_killer.seat.auth.session_manager import SessionManager
from hdu_killer.seat.models.plan import Plan
from hdu_killer.seat.models.booking_result import BookingResult

logger = logging.getLogger("hdu_killer.seat.scheduler")

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class BookingRunner:
    """Executes booking attempts with retry logic."""

    def __init__(self, api_client: ApiClient, session_manager: SessionManager,
                 interval: int = 5, max_try_times: int = 10):
        self.api = api_client
        self.session_mgr = session_manager
        self.interval = interval
        self.max_try_times = max_try_times
        self._cancelled = False

    def cancel(self):
        """Cancel the current booking run."""
        self._cancelled = True

    def run_booking(self, plans: List[Plan], target_date: datetime,
                    on_result: Optional[Callable[[BookingResult], None]] = None,
                    on_attempt: Optional[Callable[[int, int], None]] = None) -> List[BookingResult]:
        """Execute booking for all plans targeting a specific date.

        Args:
            plans: List of Plan objects to book.
            target_date: The date the seats are for.
            on_result: Callback for each booking result.
            on_attempt: Callback for each attempt (attempt_num, plan_index).

        Returns:
            List of BookingResult for all attempts.
        """
        self._cancelled = False
        results = []

        for retry in range(self.max_try_times):
            if self._cancelled:
                logger.info("Booking run cancelled")
                break

            if on_attempt:
                on_attempt(retry + 1, -1)
            logger.info("Booking attempt %d/%d for %s",
                       retry + 1, self.max_try_times,
                       target_date.strftime("%Y-%m-%d"))

            for i, plan in enumerate(plans):
                if self._cancelled:
                    break

                # Build the actual datetime for the plan
                hour, minute, second = (int(x) for x in plan.begin_time.split(":"))
                begin_time = target_date.replace(hour=hour, minute=minute, second=second, microsecond=0)

                # Get seat IDs and booker UIDs
                seat_ids = [s.seat_id for s in plan.seats]
                booker_uids = [self.session_mgr.uid] * len(plan.seats)

                result = self._book_single_plan(plan, begin_time, seat_ids, booker_uids, target_date)
                results.append(result)

                if on_result:
                    on_result(result)

                if result.success:
                    logger.info("Booking successful: %s - %s", plan.id, plan.room_name)
                    return results

                logger.warning("Plan %s failed: %s", plan.id, result.message)

                if self._cancelled:
                    break

            if not self._cancelled and retry < self.max_try_times - 1:
                logger.debug("Waiting %ds before retry...", self.interval)
                # Interruptible sleep
                for _ in range(self.interval):
                    if self._cancelled:
                        break
                    sleep(1)

        return results

    def _book_single_plan(self, plan: Plan, begin_time: datetime,
                          seat_ids: List[str], booker_uids: List[str],
                          target_date: datetime) -> BookingResult:
        """Execute a single booking attempt for one plan."""
        try:
            resp = self.api.book_seat(begin_time, plan.duration_hours, seat_ids, booker_uids)
            return BookingResult.from_api_response(
                resp,
                plan_id=plan.id,
                seat_num=",".join(s.seat_num for s in plan.seats),
                room_name=plan.room_name,
                target_date=target_date.strftime("%Y-%m-%d"),
            )
        except Exception as e:
            logger.error("Booking exception for plan %s: %s", plan.id, e)
            return BookingResult(
                success=False,
                code="error",
                message=str(e),
                plan_id=plan.id,
                target_date=target_date.strftime("%Y-%m-%d"),
            )
