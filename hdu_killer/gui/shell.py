from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from hdu_killer.gui.course_tab import CourseTab
from hdu_killer.gui.seat_tab import SeatTab

TITLE = "HDU 抢课 + 抢座"
SIZE = "1020x720"


def run() -> None:
    root = tk.Tk()
    root.title(TITLE)
    root.geometry(SIZE)
    root.minsize(900, 600)

    status = ttk.Label(root, text="就绪", relief=tk.SUNKEN, anchor=tk.W, padding=(6, 3))
    status.pack(side=tk.BOTTOM, fill=tk.X)

    def set_status(msg: str) -> None:
        status.config(text=msg)

    nb = ttk.Notebook(root)
    nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
    f_seat, f_course = ttk.Frame(nb), ttk.Frame(nb)
    nb.add(f_seat, text="图书馆抢座")
    nb.add(f_course, text="教务抢课")
    nb.select(0)

    seat = SeatTab(f_seat, root, on_login_success=set_status)
    seat.pack(fill=tk.BOTH, expand=True)
    course = CourseTab(f_course, root, set_status)
    course.pack(fill=tk.BOTH, expand=True)

    def on_close() -> None:
        course.shutdown()
        seat.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        from hdu_killer.seat.platform_.window import hide_console

        root.update_idletasks()
        root.after(400, hide_console)
    except ImportError:
        pass

    root.mainloop()
