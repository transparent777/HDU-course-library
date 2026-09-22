"""CustomTkinter 主界面."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from hdu_killer.gui.course_ctk import CourseWorkspace
from hdu_killer.gui.seat_ctk import SeatWorkspace
from hdu_killer.gui.seat_service import SeatServices, create_seat_services
from hdu_killer.gui.ui_prefs import load_ui_prefs, save_ui_prefs
from hdu_killer.gui.ui_scheduler import MainThreadUi
from hdu_killer.gui.typography import (
    apply_fonts_to_ctk_tree,
    apply_ttk_scale,
    apply_ttk_theme,
    body_font,
    reapply_all,
    title_font,
)
from hdu_killer.gui.wizard.login_wizard import LoginWizard

TITLE = "HDU 抢座 + 抢课"
DEFAULT_W, DEFAULT_H = 900, 680
MAX_W, MAX_H = 980, 760
COMPACT_W, COMPACT_H = 300, 88


def _clamp_window_size(w: int, h: int) -> tuple[int, int]:
    w = max(720, min(int(w), MAX_W))
    h = max(520, min(int(h), MAX_H))
    return w, h


def _center_geometry(root: ctk.CTk, w: int, h: int) -> str:
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    return f"{w}x{h}+{x}+{y}"


def _should_show_wizard(services: SeatServices) -> bool:
    prefs = load_ui_prefs()
    if prefs.get("wizard_completed"):
        return False
    user = services.config.get_user_info()
    if user.get("login_name") and user.get("password"):
        return False
    return True


def run() -> None:
    prefs = load_ui_prefs()
    mode = prefs.get("appearance_mode", "system")
    if mode not in ("dark", "light", "system"):
        mode = "system"
    ctk.set_appearance_mode(mode)
    ctk.set_default_color_theme(prefs.get("color_theme", "blue"))
    ui_scale = float(prefs.get("ui_scale", 1.0))
    win_w, win_h = _clamp_window_size(
        int(prefs.get("window_width", DEFAULT_W)),
        int(prefs.get("window_height", DEFAULT_H)),
    )

    root = ctk.CTk()
    reapply_all(root, ui_scale)
    root.title(TITLE)
    root._hdu_win_size = (win_w, win_h)  # noqa: SLF001
    root.minsize(720, 520)
    root.maxsize(MAX_W, MAX_H)
    root.geometry(_center_geometry(root, win_w, win_h))

    def enforce_window_size() -> None:
        w, h = getattr(root, "_hdu_win_size", (win_w, win_h))
        root.geometry(_center_geometry(root, w, h))
    ui = MainThreadUi(root)
    root._hdu_ui = ui  # noqa: SLF001 — CourseTab 等子模块投递 UI 更新

    shell = ctk.CTkFrame(root, fg_color=("gray90", "gray16"))
    shell.pack(fill="both", expand=True, padx=10, pady=10)
    pad = 10

    status_var = ctk.StringVar(value="就绪")
    status = ctk.CTkLabel(root, textvariable=status_var, anchor="w", font=body_font(ui_scale))
    status.pack(side="bottom", fill="x", padx=8, pady=4)
    compact_status_var = ctk.StringVar(value="定时未启动")
    compact_frame = ctk.CTkFrame(root, fg_color=("gray88", "gray22"), corner_radius=6)
    compact_row = ctk.CTkFrame(compact_frame, fg_color="transparent")
    compact_row.pack(fill="x", padx=10, pady=8)
    compact_font = ctk.CTkFont(family="Microsoft YaHei UI", size=13)
    compact_status_label = ctk.CTkLabel(
        compact_row,
        textvariable=compact_status_var,
        font=compact_font,
        anchor="w",
    )
    compact_status_label.grid(row=0, column=0, sticky="ew", padx=(0, 8))
    compact_row.grid_columnconfigure(0, weight=1)
    _compact_mode = False
    _geometry_before_compact: str | None = None
    sidebar_title: ctk.CTkLabel | None = None
    nav_buttons: list[ctk.CTkButton] = []

    def set_status(msg: str) -> None:
        status_var.set(msg)

    services = create_seat_services()
    seat_view: Optional[SeatWorkspace] = None
    course_view: Optional[CourseWorkspace] = None

    sidebar = ctk.CTkFrame(
        shell,
        width=148,
        corner_radius=8,
        fg_color=("gray86", "gray22"),
    )
    sidebar.pack(side="left", fill="y", padx=(0, 10), pady=0)
    sidebar.pack_propagate(False)

    content = ctk.CTkFrame(shell, fg_color="transparent")
    content.pack(side="left", fill="both", expand=True)

    pages: dict[str, ctk.CTkFrame] = {}
    for key in ("seat", "course", "look"):
        fr = ctk.CTkFrame(content, fg_color="transparent")
        fr.place(relx=0, rely=0, relwidth=1, relheight=1)
        pages[key] = fr

    def show_page(key: str) -> None:
        pages[key].lift()
        set_status({"seat": "图书馆抢座", "course": "教务抢课", "look": "外观设置"}[key])

    def enter_compact_mode() -> None:
        nonlocal _compact_mode, _geometry_before_compact
        if _compact_mode:
            return
        _geometry_before_compact = root.geometry()
        _compact_mode = True
        shell.pack_forget()
        status.pack_forget()
        compact_frame.pack(fill="x", padx=8, pady=8)
        root.minsize(COMPACT_W, COMPACT_H)
        root.maxsize(520, COMPACT_H)
        root.resizable(False, False)
        sw = root.winfo_screenwidth()
        root.geometry(f"{COMPACT_W}x{COMPACT_H}+{max(0, sw - COMPACT_W - 20)}+20")
        root.title("HDU 抢座")
        if seat_view and seat_view.is_engine_running():
            compact_status_var.set("定时运行中")
            set_status("收纳模式：定时仍在运行")
        else:
            compact_status_var.set("定时未启动")
            set_status("收纳模式：点展开恢复大界面")

    def exit_compact_mode() -> None:
        nonlocal _compact_mode
        if not _compact_mode:
            return
        _compact_mode = False
        compact_frame.pack_forget()
        shell.pack(fill="both", expand=True, padx=pad, pady=pad)
        status.pack(side="bottom", fill="x", padx=8, pady=4)
        root.minsize(720, 520)
        root.maxsize(MAX_W, MAX_H)
        root.resizable(True, True)
        root.title(TITLE)
        if _geometry_before_compact:
            root.geometry(_geometry_before_compact)
        else:
            enforce_window_size()

    def build_seat() -> None:
        nonlocal seat_view
        if seat_view is None:
            seat_view = SeatWorkspace(
                pages["seat"],
                services,
                root,
                set_status,
                ui,
                compact_status_var=compact_status_var,
                on_enter_compact=enter_compact_mode,
            )
            seat_view.pack(fill="both", expand=True)

    def build_course() -> None:
        nonlocal course_view
        if course_view is None:
            course_view = CourseWorkspace(
                pages["course"],
                root,
                set_status,
                on_enter_compact=enter_compact_mode,
            )
            course_view.pack(fill="both", expand=True)

    def build_look() -> None:
        if pages["look"].winfo_children():
            return
        p = pages["look"]
        bf = body_font(ui_scale)
        tf = title_font(ui_scale)
        ctk.CTkLabel(p, text="外观", font=tf).pack(anchor="w", pady=(0, 12))
        cur = load_ui_prefs()

        ctk.CTkLabel(p, text="界面缩放（字号）", font=bf).pack(anchor="w", pady=(0, 4))
        scale_var = ctk.DoubleVar(value=float(cur.get("ui_scale", ui_scale)))

        def on_scale(val: float) -> None:
            v = round(float(val), 2)
            data = load_ui_prefs()
            data["ui_scale"] = v
            save_ui_prefs(data)
            reapply_all(root, v)
            status.configure(font=body_font(v))
            if sidebar_title is not None:
                sidebar_title.configure(font=title_font(v))
            nf = body_font(v)
            for btn in nav_buttons:
                btn.configure(font=nf)
            apply_fonts_to_ctk_tree(shell, v)
            if seat_view is not None:
                seat_view.apply_ui_scale(v)
            if course_view is not None:
                course_view.apply_ui_scale(v)
            set_status(f"字号缩放已设为 {v}")

        ctk.CTkSlider(p, from_=0.9, to=1.55, number_of_steps=13, variable=scale_var, command=on_scale).pack(
            fill="x", pady=(0, 16)
        )

        ctk.CTkLabel(p, text="主题模式", font=bf).pack(anchor="w")
        theme_var = ctk.StringVar(value=cur.get("appearance_mode", "system"))

        def on_theme(_v: str) -> None:
            ctk.set_appearance_mode(theme_var.get())
            data = load_ui_prefs()
            data["appearance_mode"] = theme_var.get()
            save_ui_prefs(data)
            if seat_view is not None:
                seat_view.apply_theme()
            if course_view is not None:
                course_view.apply_theme()
            if seat_view is None and course_view is None:
                apply_ttk_theme(root)
                apply_ttk_scale(root, ui_scale)

        seg = ctk.CTkSegmentedButton(
            p, values=["system", "light", "dark"], variable=theme_var, command=on_theme
        )
        seg.pack(anchor="w", pady=8)

        ctk.CTkLabel(p, text="抢座请求间隔 / 重试", anchor="w").pack(anchor="w", pady=(20, 4))
        st = services.config.get_settings()
        iv = ctk.StringVar(value=str(st.get("interval", 5)))
        mx = ctk.StringVar(value=str(st.get("max_try_times", 10)))
        r2 = ctk.CTkFrame(p, fg_color="transparent")
        r2.pack(fill="x")
        ctk.CTkLabel(r2, text="间隔(秒)").pack(side="left")
        ctk.CTkEntry(r2, textvariable=iv, width=60).pack(side="left", padx=8)
        ctk.CTkLabel(r2, text="最大重试").pack(side="left", padx=(16, 0))
        ctk.CTkEntry(r2, textvariable=mx, width=60).pack(side="left", padx=8)

        def save_seat_settings() -> None:
            try:
                services.config.update_settings(int(iv.get()), int(mx.get()))
                services.runner.interval = int(iv.get())
                services.runner.max_try_times = int(mx.get())
                set_status("抢座参数已保存")
            except ValueError:
                messagebox.showerror("错误", "请输入有效数字", parent=root)

        ctk.CTkButton(p, text="保存抢座参数", command=save_seat_settings).pack(anchor="w", pady=8)

    def nav_seat() -> None:
        build_seat()
        show_page("seat")

    def nav_course() -> None:
        build_course()
        show_page("course")

    def nav_look() -> None:
        build_look()
        show_page("look")

    def rerun_wizard() -> None:
        def after_wizard_login() -> None:
            build_seat()
            build_course()
            if course_view is not None:
                course_view.refresh_account()
            if seat_view is not None:
                seat_view._update_account()

        LoginWizard(root, services, on_complete=after_wizard_login, ui=ui)

    nav_font = body_font(ui_scale)
    sidebar_title = ctk.CTkLabel(sidebar, text="HDU", font=title_font(ui_scale))
    sidebar_title.pack(pady=(16, 24))
    for label, cmd in (
        ("图书馆抢座", nav_seat),
        ("教务抢课", nav_course),
        ("外观与参数", nav_look),
    ):
        btn = ctk.CTkButton(
            sidebar,
            text=label,
            command=cmd,
            anchor="w",
            font=nav_font,
            height=40,
        )
        btn.pack(fill="x", padx=8, pady=4)
        nav_buttons.append(btn)
    wiz_btn = ctk.CTkButton(
        sidebar,
        text="重新登录向导",
        command=rerun_wizard,
        anchor="w",
        fg_color="gray35",
        font=nav_font,
        height=40,
    )
    wiz_btn.pack(fill="x", padx=8, pady=(24, 4))
    nav_buttons.append(wiz_btn)

    def real_quit() -> None:
        nonlocal _closing
        if _closing:
            return
        _closing = True
        root.withdraw()
        try:
            data = load_ui_prefs()
            ww, wh = _clamp_window_size(root.winfo_width(), root.winfo_height())
            if ww < 200:
                ww, wh = getattr(root, "_hdu_win_size", (win_w, win_h))
            data["window_width"] = ww
            data["window_height"] = wh
            save_ui_prefs(data)
        except Exception:
            pass
        ui.stop()
        if course_view:
            course_view.shutdown()
        if seat_view:
            seat_view.shutdown(fast=True)
        root.quit()
        root.destroy()

    _closing = False

    def on_close() -> None:
        if _compact_mode:
            if messagebox.askyesno(
                "退出程序",
                "确定退出？定时抢座将停止。",
                parent=root,
            ):
                real_quit()
            return
        if seat_view and seat_view.is_engine_running():
            choice = messagebox.askyesnocancel(
                "定时运行中",
                "收纳到小窗继续计时？\n\n"
                "「是」= 收纳（定时继续）\n"
                "「否」= 退出并停止定时\n"
                "「取消」= 返回",
                parent=root,
            )
            if choice is None:
                return
            if choice:
                enter_compact_mode()
                return
        real_quit()

    ctk.CTkButton(
        compact_row,
        text="展开",
        width=64,
        height=30,
        command=exit_compact_mode,
        font=compact_font,
    ).grid(row=0, column=1, sticky="e")

    root.protocol("WM_DELETE_WINDOW", on_close)

    def after_wizard() -> None:
        build_seat()
        show_page("seat")
        root.after(30, enforce_window_size)

    def boot() -> None:
        if _should_show_wizard(services):
            LoginWizard(root, services, on_complete=after_wizard, ui=ui)
        else:
            after_wizard()

    root.after(0, boot)

    try:
        from hdu_killer.seat.platform_.window import hide_console

        root.after(400, hide_console)
    except ImportError:
        pass

    root.mainloop()
