"""Background course job for GUI."""

from __future__ import annotations

import threading
from typing import Callable

from hdu_killer.course.config import load_config, save_config, validate_config
from hdu_killer.course.jw_client import JwClient
from hdu_killer.course.workflow import (
    ensure_catalog,
    format_jw_error,
    run_scheduled,
    run_wait,
)

LogFn = Callable[[str], None]


class CourseRunner:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._cancel.set()

    def start(self, on_log: LogFn) -> None:
        if self.is_running:
            raise RuntimeError("抢课任务已在运行")
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._work, args=(on_log,), daemon=True, name="CourseRunner"
        )
        self._thread.start()

    def _work(self, on_log: LogFn) -> None:
        try:
            cfg = load_config()
            validate_config(cfg)
            ua = cfg.get("user_agent") or ""
            client = JwClient(user_agent=ua)
            on_log("正在登录教务系统…")
            client.login_flow(cfg)
            save_config(cfg)
            on_log("登录成功")
            catalog = ensure_catalog(client, cfg, on_log)
            if cfg.get("wait_course", {}).get("enabled") == "1":
                run_wait(client, cfg, catalog, on_log, self._cancel.is_set)
            else:
                run_scheduled(client, cfg, catalog, on_log, self._cancel.is_set)
            on_log("任务结束")
        except Exception as e:
            on_log(f"错误: {format_jw_error(e)}")
