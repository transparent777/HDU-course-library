"""图书馆抢座后端组装（供 CTk GUI 使用）."""

from __future__ import annotations

from dataclasses import dataclass

from hdu_killer.paths import get_seat_config_path
from hdu_killer.seat.api.client import ApiClient
from hdu_killer.seat.api.room_cache import RoomCache
from hdu_killer.seat.auth.session_manager import SessionManager
from hdu_killer.seat.config.manager import ConfigManager
from hdu_killer.seat.logging_.history import HistoryLogger
from hdu_killer.seat.logging_.logger import setup_logging
from hdu_killer.seat.scheduler.booking_runner import BookingRunner
from hdu_killer.seat.scheduler.engine import SchedulerEngine


@dataclass
class SeatServices:
    config: ConfigManager
    session: SessionManager
    api: ApiClient
    rooms: RoomCache
    runner: BookingRunner
    engine: SchedulerEngine
    history: HistoryLogger


def create_seat_services() -> SeatServices:
    setup_logging()
    config = ConfigManager(str(get_seat_config_path()))
    config.load()
    session = SessionManager(config)
    session.init_session()
    api = ApiClient(session)
    rooms = RoomCache(api)
    settings = config.get_settings()
    runner = BookingRunner(
        api_client=api,
        session_manager=session,
        interval=settings["interval"],
        max_try_times=settings["max_try_times"],
    )
    engine = SchedulerEngine(config_manager=config, session_manager=session, booking_runner=runner)
    return SeatServices(
        config=config,
        session=session,
        api=api,
        rooms=rooms,
        runner=runner,
        engine=engine,
        history=HistoryLogger(),
    )
