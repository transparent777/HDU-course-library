"""在程序内打开使用手册."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import messagebox

from hdu_killer.gui.typography import body_font
from hdu_killer.paths import get_project_root, get_seat_manual_path

# 相对路径，供抢课页传入 open()
COURSE_MANUAL = Path("docs") / "教务抢课使用手册.txt"


class ManualViewer(ctk.CTkToplevel):
    _instance: Optional["ManualViewer"] = None

    @classmethod
    def open(
        cls,
        parent: ctk.CTk,
        ui_scale: float = 1.0,
        manual_rel: Path | None = None,
        title: str = "使用手册",
    ) -> None:
        if cls._instance is not None:
            try:
                if cls._instance.winfo_exists():
                    cls._instance.lift()
                    cls._instance.focus_force()
                    return
            except Exception:
                cls._instance = None
        if manual_rel is not None:
            path = get_project_root() / manual_rel
        else:
            path = get_seat_manual_path()
        if not path.is_file():
            messagebox.showerror("错误", f"未找到手册：\n{path}", parent=parent)
            return
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            messagebox.showerror("错误", f"无法读取手册：{e}", parent=parent)
            return
        cls._instance = cls(parent, text, ui_scale, title)

    def __init__(self, parent: ctk.CTk, content: str, ui_scale: float, title: str = "使用手册") -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("640x560")
        self.minsize(480, 360)
        self.transient(parent)

        bf = body_font(ui_scale)
        box = ctk.CTkTextbox(self, font=bf, wrap="word")
        box.pack(fill="both", expand=True, padx=14, pady=14)
        box.insert("1.0", content.strip())
        box.configure(state="disabled")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self.focus_force)

    def _on_close(self) -> None:
        ManualViewer._instance = None
        self.destroy()
