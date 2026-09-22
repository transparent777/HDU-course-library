"""Non-blocking scheduler engine.

Core new module: runs in a dedicated thread, uses threading.Event
for interruptible waits instead of blocking sleep().
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import List, Optional, Callable, Dict, Any

from hdu_killer.seat.models.schedule import Schedule
from hdu_killer.seat.models.booking_result import BookingResult
from hdu_killer.seat.scheduler.booking_runner import BookingRunner, WEEKDAY_NAMES
from hdu_killer.seat.auth.session_manager import SessionManager
from hdu_killer.seat.config.manager import ConfigManager

logger = logging.getLogger("hdu_killer.seat.scheduler")


class SchedulerEngine:
    """Non-blocking scheduling engine that runs in a background thread.

    Replaces the old sleep()-based countdown with threading.Event-based waits,
    allowing clean shutdown within 1 second.

    Callbacks:
        on_countdown_tick(remaining_seconds, trigger_time, plan_desc)
        on_booking_result(result: BookingResult)
        on_booking_start(target_date, plan_ids)
        on_error(error: Exception)
        on_idle()  # called when no schedules are active
    """

    def __init__(self, config_manager: ConfigManager, session_manager: SessionManager,
                 booking_runner: BookingRunner):
        self.config = config_manager
        self.session_mgr = session_manager
        self.runner = booking_runner

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._cancel_booking = threading.Event()

        # Callbacks
        self.on_countdown_tick: Optional[Callable] = None
        self.on_booking_result: Optional[Callable] = None
        self.on_booking_start: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_idle: Optional[Callable] = None

        # Current state for status queries
        self._state_lock = threading.Lock()
        self._current_trigger: Optional[datetime] = None
        self._current_target: Optional[datetime] = None
        self._current_plan_ids: List[str] = []
        self._running = False

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status (thread-safe)."""
        with self._state_lock:
            return {
                "running": self._running,
                "trigger_time": self._current_trigger,
                "target_date": self._current_target,
                "plan_ids": list(self._current_plan_ids),
                "remaining_seconds": (
                    int((self._current_trigger - datetime.now()).total_seconds())
                    if self._current_trigger and self._current_trigger > datetime.now()
                    else None
                ),
            }

    def start(self):
        """Start the scheduler engine in a background thread."""
        with self._state_lock:
            if self._running:
                logger.warning("Engine already running")
                return

        self._stop_event.clear()
        self._cancel_booking.clear()
        with self._state_lock:
            self._running = True

        self._thread = threading.Thread(target=self._engine_loop, daemon=True, name="SchedulerEngine")
        self._thread.start()
        logger.info("Scheduler engine started")

    def stop(self):
        """Stop the engine (clean shutdown within ~1 second)."""
        with self._state_lock:
            if not self._running:
                return

        logger.info("Stopping scheduler engine...")
        self._stop_event.set()
        self._cancel_booking.set()
        self.runner.cancel()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        with self._state_lock:
            self._running = False
        logger.info("Scheduler engine stopped")

    def stop_fast(self) -> None:
        """退出程序时仅发停止信号，不阻塞等待线程结束。"""
        with self._state_lock:
            if not self._running:
                return
        self._stop_event.set()
        self._cancel_booking.set()
        self.runner.cancel()
        with self._state_lock:
            self._running = False

    def _engine_loop(self):
        """Main engine loop running in background thread."""
        while not self._stop_event.is_set():
            try:
                schedules = self.config.get_schedules()
                plans_map = {p.id: p for p in self.config.get_plans()}

                # Find the earliest trigger time and collect ALL schedules at that time
                now = datetime.now()
                earliest_trigger = None
                triggers = []  # list of (trigger, target_date, plan_ids)
                for schedule in schedules:
                    result = schedule.next_trigger(now)
                    if result is not None:
                        trigger, target_date, plan_ids = result
                        if earliest_trigger is None or trigger < earliest_trigger:
                            earliest_trigger = trigger
                            triggers = [(trigger, target_date, plan_ids)]
                        elif trigger == earliest_trigger:
                            triggers.append((trigger, target_date, plan_ids))

                if earliest_trigger is None:
                    with self._state_lock:
                        self._current_trigger = None
                        self._current_target = None
                        self._current_plan_ids = []
                    if self.on_idle:
                        self.on_idle()
                    # Wait and re-check
                    self._stop_event.wait(timeout=30.0)
                    continue

                # Merge plan_ids from all grouped triggers (deduplicate)
                trigger_time = earliest_trigger
                all_plan_ids = []
                seen_pids = set()
                for _, target_date, plan_ids in triggers:
                    for pid in plan_ids:
                        if pid not in seen_pids:
                            seen_pids.add(pid)
                            all_plan_ids.append(pid)

                # Use the first trigger's target_date (they typically match)
                target_date = triggers[0][1]

                # Update state
                with self._state_lock:
                    self._current_trigger = trigger_time
                    self._current_target = target_date
                    self._current_plan_ids = all_plan_ids

                # Resolve plan objects
                active_plans = [plans_map[pid] for pid in all_plan_ids if pid in plans_map]
                if not active_plans:
                    logger.warning("No valid plans found for IDs: %s", all_plan_ids)
                    self._stop_event.wait(timeout=30.0)
                    continue

                plan_desc = ", ".join(f"{p.room_name}-{p.seats[0].seat_num}" for p in active_plans if p.seats)
                if len(triggers) > 1:
                    plan_desc = f"[{len(triggers)}个调度] " + plan_desc

                # Countdown phase (interruptible, 1-second ticks)
                while not self._stop_event.is_set():
                    now = datetime.now()
                    remaining = (trigger_time - now).total_seconds()
                    if remaining <= 0:
                        break
                    if self.on_countdown_tick:
                        self.on_countdown_tick(int(remaining), trigger_time, plan_desc)
                    self._stop_event.wait(timeout=1.0)

                if self._stop_event.is_set():
                    break

                # Booking phase - execute for each grouped trigger's plans
                logger.info("Trigger time reached (%d schedule(s)), booking for %s (%s)",
                           len(triggers),
                           target_date.strftime("%Y-%m-%d"),
                           WEEKDAY_NAMES[target_date.weekday()])

                if self.on_booking_start:
                    self.on_booking_start(target_date, all_plan_ids)

                def _on_result(result: BookingResult):
                    if self.on_booking_result:
                        self.on_booking_result(result)

                def _on_attempt(attempt_num, plan_idx):
                    pass  # Could add callback

                results = self.runner.run_booking(
                    plans=active_plans,
                    target_date=target_date,
                    on_result=_on_result,
                    on_attempt=_on_attempt,
                )

                # Log results
                for r in results:
                    if r.success:
                        logger.info("Booking result: %s", r)
                    else:
                        logger.warning("Booking result: %s", r)

                # After booking, loop back to find next trigger
                # Brief pause to avoid tight loop
                self._stop_event.wait(timeout=5.0)

            except Exception as e:
                logger.error("Engine loop error: %s", e, exc_info=True)
                if self.on_error:
                    self.on_error(e)
                self._stop_event.wait(timeout=10.0)

        with self._state_lock:
            self._running = False
