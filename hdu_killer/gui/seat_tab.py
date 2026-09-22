from __future__ import annotations

import logging
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

from hdu_killer.paths import get_seat_config_path

logger = logging.getLogger(__name__)


class SeatTab(ttk.Frame):
    def __init__(self, master: tk.Misc, root: tk.Tk, on_login_success=None) -> None:
        super().__init__(master)
        self._win = root
        self._on_login_success = on_login_success
        self._app = None
        self._placeholder = ttk.Label(self, text="正在加载图书馆模块…", anchor=tk.CENTER)
        self._placeholder.pack(fill=tk.BOTH, expand=True)
        self.after(100, self._init)

    def _init(self) -> None:
        try:
            from hdu_killer.seat.logging_.logger import setup_logging
            from hdu_killer.seat.config.manager import ConfigManager
            from hdu_killer.seat.auth.session_manager import SessionManager
            from hdu_killer.seat.api.client import ApiClient
            from hdu_killer.seat.api.room_cache import RoomCache
            from hdu_killer.seat.ui.gui import GuiApp

            setup_logging()
            config = ConfigManager(str(get_seat_config_path()))
            config.load()
            session = SessionManager(config)
            session.init_session()
            api = ApiClient(session)
            rooms = RoomCache(api)
            self._app = GuiApp(
                self._win,
                config,
                session,
                api,
                rooms,
                host=self,
                on_login_success=self._on_login_success,
            )
            self._placeholder.destroy()
        except Exception as e:
            logger.exception("seat tab init failed")
            self._placeholder.config(text=f"加载失败: {e}")
            messagebox.showerror("图书馆抢座", f"{e}\n\n{traceback.format_exc()}", parent=self._win)

    def shutdown(self) -> None:
        if self._app:
            self._app.shutdown()
