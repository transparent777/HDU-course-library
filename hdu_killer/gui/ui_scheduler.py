"""把后台线程的 UI 更新投递到 Tk 主线程（Python 3.14 + CTk 必须）."""

from __future__ import annotations

import logging
import queue
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., None])


class MainThreadUi:
    def __init__(self, root) -> None:
        self._root = root
        self._q: queue.Queue[Callable[[], None]] = queue.Queue()
        self._alive = True
        # 必须在 mainloop 运行后再开始轮询
        root.after(1, self._tick)

    def stop(self) -> None:
        self._alive = False
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def _tick(self) -> None:
        if not self._alive:
            return
        while True:
            try:
                cb = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                cb()
            except Exception:
                logger.exception("UI callback failed")
        if self._alive:
            self._root.after(50, self._tick)

    def call(self, fn: F, *args, **kwargs) -> None:
        if kwargs:
            self._q.put(lambda: fn(*args, **kwargs))
        elif args:
            self._q.put(lambda: fn(*args))
        else:
            self._q.put(fn)
