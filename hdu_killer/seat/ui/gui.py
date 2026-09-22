"""经典 tkinter 抢座界面（main.py --classic）。"""

from __future__ import annotations

import os
from typing import Callable, Optional
import logging
import re
import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox

from hdu_killer.seat.config.manager import ConfigManager
from hdu_killer.seat.auth.session_manager import SessionManager
from hdu_killer.seat.api.client import ApiClient
from hdu_killer.seat.api.room_cache import RoomCache
from hdu_killer.seat.scheduler.engine import SchedulerEngine
from hdu_killer.seat.scheduler.booking_runner import BookingRunner
from hdu_killer.seat.models.plan import Plan, SeatInfo
from hdu_killer.seat.models.schedule import Schedule, DateMapping
from hdu_killer.seat.models.booking_result import BookingResult
from hdu_killer.seat.ui.display import format_countdown, WEEKDAY_NAMES
from hdu_killer.seat.platform_.paths import get_app_dir
from hdu_killer.seat.logging_.history import HistoryLogger

logger = logging.getLogger("hdu_killer.seat.ui")


class GuiApp:
    """经典 tkinter 主窗口。"""

    def __init__(self, root: tk.Tk, config_manager: ConfigManager,
                 session_manager: SessionManager, api_client: ApiClient,
                 room_cache: RoomCache, host: Optional[tk.Widget] = None,
                 on_login_success: Optional[Callable[[str], None]] = None):
        self.root = root
        self._embedded = host is not None
        self._host = host if host is not None else root
        self.config = config_manager
        self.session_mgr = session_manager
        self.api = api_client
        self.room_cache = room_cache
        self._on_login_success = on_login_success

        # Create booking runner and scheduler engine
        settings = self.config.get_settings()
        self.runner = BookingRunner(
            api_client=self.api,
            session_manager=self.session_mgr,
            interval=settings["interval"],
            max_try_times=settings["max_try_times"],
        )
        self.engine = SchedulerEngine(
            config_manager=self.config,
            session_manager=self.session_mgr,
            booking_runner=self.runner,
        )
        self.history = HistoryLogger()
        self.room_cache.on_ready(self._on_rooms_ready)

        # Engine callbacks
        self.engine.on_countdown_tick = self._on_countdown_tick
        self.engine.on_booking_result = self._on_booking_result
        self.engine.on_booking_start = self._on_booking_start
        self.engine.on_error = self._on_engine_error

        # Threading state
        self._booking_cancel = threading.Event()
        self._logged_in = False
        self._rooms_ready = False

        # Build GUI
        self._build_main_window()
        self._build_status_bar()
        self._build_tabs()

        if not self._embedded:
            self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Start auto-login after GUI is shown
        self.root.after(200, self._auto_login)

    # ================================================================
    # GUI Building
    # ================================================================

    def _build_main_window(self):
        if self._embedded:
            return
        self.root.title("HDU 图书馆抢座")
        self.root.geometry("900x650")
        self.root.minsize(800, 550)
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 900) // 2
        y = (sh - 650) // 2
        self.root.geometry(f"900x650+{x}+{y}")

    def _build_status_bar(self):
        self.status_bar = ttk.Label(
            self._host, text="就绪", relief=tk.SUNKEN, anchor=tk.W, padding=(5, 2),
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_tabs(self):
        self.notebook = ttk.Notebook(self._host)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5, 0))

        self._build_plans_tab()
        self._build_booking_tab()
        self._build_scheduler_tab()
        self._build_status_tab()
        self._build_settings_tab()
        self._build_help_tab()

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, event=None):
        idx = self.notebook.index(self.notebook.select())
        if idx == 1:
            self._refresh_booking_plans_tree()
        elif idx == 3:
            self._update_status_display()

    # ─── Tab 1: Plans ───────────────────────────────────────────

    def _build_plans_tab(self):
        frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(frame, text="方案管理")

        acct = ttk.LabelFrame(frame, text="当前预约账号", padding=8)
        acct.pack(fill=tk.X, pady=(0, 6))
        self.account_label = ttk.Label(
            acct,
            text="未登录 — 请使用智慧图书馆账号登录后再添加方案",
            wraplength=700,
        )
        self.account_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(acct, text="登录 / 切换账号", command=lambda: self._show_login_dialog()).pack(
            side=tk.RIGHT, padx=4,
        )

        # Buttons at bottom
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(5, 0))
        ttk.Button(btn_frame, text="添加方案", command=self._add_plan_dialog).pack(
            side=tk.LEFT, padx=2,
        )
        ttk.Button(btn_frame, text="删除选中", command=self._delete_selected_plans).pack(
            side=tk.LEFT, padx=2,
        )
        ttk.Button(
            btn_frame, text="批量修改时间", command=self._batch_change_time_dialog,
        ).pack(side=tk.LEFT, padx=2)

        # Treeview fills remaining space
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("idx", "plan_id", "room", "floor", "seats", "time", "duration")
        self.plans_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=18,
        )
        for col, text, width in [
            ("idx", "序号", 50), ("plan_id", "方案ID", 130),
            ("room", "房间名", 130), ("floor", "楼层", 80),
            ("seats", "座位号", 100), ("time", "开始时间", 100),
            ("duration", "时长", 60),
        ]:
            self.plans_tree.heading(col, text=text)
            self.plans_tree.column(col, width=width, anchor=tk.CENTER if col in ("idx", "time", "duration") else tk.W)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.plans_tree.yview)
        self.plans_tree.configure(yscrollcommand=scrollbar.set)
        self.plans_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._update_account_display()
        self._refresh_plans_tree()

    # ─── Tab 2: Booking ─────────────────────────────────────────

    def _build_booking_tab(self):
        frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(frame, text="立即抢座")

        # Top: plan tree (read-only)
        tree_frame = ttk.LabelFrame(frame, text="当前方案", padding=3)
        tree_frame.pack(fill=tk.X, pady=(0, 5))

        cols = ("plan_id", "room", "floor", "seats", "time", "duration")
        self.booking_tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", height=4,
        )
        for col, text, w in [
            ("plan_id", "方案ID", 120), ("room", "房间名", 120),
            ("floor", "楼层", 80), ("seats", "座位号", 100),
            ("time", "开始时间", 100), ("duration", "时长", 60),
        ]:
            self.booking_tree.heading(col, text=text)
            self.booking_tree.column(col, width=w, anchor=tk.CENTER if col in ("time", "duration") else tk.W)

        self.booking_tree.pack(fill=tk.X)

        # Progress and buttons
        ctrl_frame = ttk.Frame(frame)
        ctrl_frame.pack(fill=tk.X, pady=5)

        self.booking_progress_label = ttk.Label(ctrl_frame, text="")
        self.booking_progress_label.pack(side=tk.LEFT, padx=5)

        self.booking_start_btn = ttk.Button(
            ctrl_frame, text="开始抢座", command=self._start_booking,
        )
        self.booking_start_btn.pack(side=tk.RIGHT, padx=2)
        self.booking_stop_btn = ttk.Button(
            ctrl_frame, text="停止", command=self._cancel_booking, state=tk.DISABLED,
        )
        self.booking_stop_btn.pack(side=tk.RIGHT, padx=2)

        # Log area
        log_frame = ttk.LabelFrame(frame, text="结果日志", padding=3)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.booking_log = tk.Text(
            log_frame, state=tk.DISABLED, wrap=tk.WORD, height=10,
            font=("Consolas", 9),
        )
        self.booking_log.tag_configure("success", foreground="green")
        self.booking_log.tag_configure("error", foreground="red")
        self.booking_log.tag_configure("info", foreground="#0066cc")
        self.booking_log.tag_configure("warning", foreground="#cc6600")

        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.booking_log.yview)
        self.booking_log.configure(yscrollcommand=log_scroll.set)
        self.booking_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ─── Tab 3: Scheduler ───────────────────────────────────────

    def _build_scheduler_tab(self):
        frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(frame, text="调度管理")

        # Top buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(0, 5))

        self.scheduler_start_btn = ttk.Button(
            btn_frame, text="启动调度", command=self._start_scheduler,
        )
        self.scheduler_start_btn.pack(side=tk.LEFT, padx=2)
        self.scheduler_stop_btn = ttk.Button(
            btn_frame, text="停止调度", command=self._stop_scheduler,
        )
        self.scheduler_stop_btn.pack(side=tk.LEFT, padx=2)

        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8,
        )
        ttk.Button(
            btn_frame, text="添加按星期调度", command=self._add_weekday_schedule_dialog,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            btn_frame, text="添加按日期调度", command=self._add_date_schedule_dialog,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            btn_frame, text="切换启用", command=self._toggle_schedule_enabled,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            btn_frame, text="删除选中", command=self._delete_selected_schedules,
        ).pack(side=tk.LEFT, padx=2)

        # Engine running status indicator
        self.scheduler_status_label = tk.Label(
            btn_frame, text="● 调度未运行", fg="red", font=("", 10),
        )
        self.scheduler_status_label.pack(side=tk.RIGHT, padx=10)

        # Schedule tree
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("idx", "type", "target", "status", "plans")
        self.schedules_tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", height=15,
        )
        for col, text, w in [
            ("idx", "序号", 50), ("type", "类型", 80),
            ("target", "目标", 200), ("status", "状态", 60),
            ("plans", "绑定方案", 300),
        ]:
            self.schedules_tree.heading(col, text=text)
            self.schedules_tree.column(col, width=w, anchor=tk.CENTER if col in ("idx", "status") else tk.W)

        self.schedules_tree.tag_configure("enabled", foreground="black")
        self.schedules_tree.tag_configure("disabled", foreground="gray")

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.schedules_tree.yview)
        self.schedules_tree.configure(yscrollcommand=sb.set)
        self.schedules_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._refresh_schedules_tree()

    # ─── Tab 4: Status ──────────────────────────────────────────

    def _build_status_tab(self):
        frame = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(frame, text="状态")

        info_frame = ttk.LabelFrame(frame, text="调度引擎状态", padding=15)
        info_frame.pack(fill=tk.X)

        self.status_labels = {}
        for i, (key, label_text) in enumerate([
            ("engine", "引擎"),
            ("trigger", "下次触发"),
            ("remaining", "剩余时间"),
            ("plans", "目标方案"),
        ]):
            ttk.Label(info_frame, text=f"{label_text}:", font=("", 10, "bold")).grid(
                row=i, column=0, sticky=tk.W, pady=4,
            )
            lbl = ttk.Label(info_frame, text="—", font=("", 10))
            lbl.grid(row=i, column=1, sticky=tk.W, padx=(15, 0), pady=4)
            self.status_labels[key] = lbl

        self._update_status_display()

    # ─── Tab 5: Settings ────────────────────────────────────────

    def _build_settings_tab(self):
        frame = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(frame, text="设置")

        s_frame = ttk.LabelFrame(frame, text="请求设置", padding=15)
        s_frame.pack(fill=tk.X)

        ttk.Label(s_frame, text="重试间隔（秒）:").grid(row=0, column=0, sticky=tk.W, pady=8)
        self.interval_var = tk.StringVar()
        self.interval_entry = ttk.Spinbox(
            s_frame, from_=1, to=300, textvariable=self.interval_var, width=10,
        )
        self.interval_entry.grid(row=0, column=1, padx=10, pady=8)
        ttk.Label(s_frame, text="建议不小于5").grid(row=0, column=2, sticky=tk.W)

        ttk.Label(s_frame, text="最大重试次数:").grid(row=1, column=0, sticky=tk.W, pady=8)
        self.max_try_var = tk.StringVar()
        self.max_try_entry = ttk.Spinbox(
            s_frame, from_=1, to=999, textvariable=self.max_try_var, width=10,
        )
        self.max_try_entry.grid(row=1, column=1, padx=10, pady=8)

        ttk.Button(frame, text="保存设置", command=self._save_settings).pack(pady=20)

        self._load_settings()

    # ─── Tab 6: Help ────────────────────────────────────────────

    def _build_help_tab(self):
        frame = ttk.Frame(self.notebook, padding=5)
        self.notebook.add(frame, text="帮助")

        self.help_text = tk.Text(
            frame, state=tk.DISABLED, wrap=tk.WORD, font=("", 10),
        )
        help_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.help_text.yview)
        self.help_text.configure(yscrollcommand=help_scroll.set)
        self.help_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        help_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._load_help()

    # ================================================================
    # Login
    # ================================================================

    def _auto_login(self):
        # 与原版说明一致：先由用户确认学号/密码，避免静默登录导致不知道为谁预约
        self._show_login_dialog()

    def _show_login_dialog(self, error_msg: str = None):
        dlg = tk.Toplevel(self.root)
        dlg.title("图书馆预约 — 登录")
        dlg.geometry("420x280")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.lift()
        dlg.attributes("-topmost", True)
        dlg.after(300, lambda: dlg.attributes("-topmost", False))

        # Center on parent
        dlg.update_idletasks()
        px = self.root.winfo_x() + (self.root.winfo_width() - 420) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - 280) // 2
        dlg.geometry(f"+{px}+{py}")

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        user = self.config.get_user_info()

        ttk.Label(
            frame,
            text="图书馆智慧座位系统账号登录。"
            "密码一般为图书馆系统密码，若与统一认证不同请以网页登录为准。",
            wraplength=380,
            foreground="gray",
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))

        ttk.Label(frame, text="学号:").grid(row=1, column=0, sticky=tk.W, pady=5)
        login_var = tk.StringVar(value=user.get("login_name", ""))
        ttk.Entry(frame, textvariable=login_var, width=25).grid(row=1, column=1, pady=5)

        ttk.Label(frame, text="密码:").grid(row=2, column=0, sticky=tk.W, pady=5)
        pwd_var = tk.StringVar(value=user.get("password", ""))
        ttk.Entry(frame, textvariable=pwd_var, width=25, show="*").grid(row=2, column=1, pady=5)

        status_label = ttk.Label(frame, text=error_msg or "", foreground="red")
        status_label.grid(row=3, column=0, columnspan=2, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)

        login_btn = ttk.Button(
            btn_frame, text="登录",
            command=lambda: self._dialog_login(dlg, login_var, pwd_var, status_label),
        )
        # Store reference so login callback can update it directly
        dlg._status_label = status_label
        login_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(
            btn_frame, text="稍后登录", command=dlg.destroy,
        ).pack(side=tk.LEFT, padx=5)

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    def _dialog_login(self, dlg, login_var, pwd_var, status_label):
        login_name = login_var.get().strip()
        password = pwd_var.get().strip()
        if not login_name or not password:
            status_label.config(text="请输入学号和密码")
            return
        status_label.config(
            text="登录中…正在连接图书馆服务器",
            foreground="blue",
        )
        dlg.update_idletasks()
        self._start_login_thread(dlg, (login_name, password))

    def _start_login_thread(self, dlg, credentials):
        def worker():
            if credentials:
                login_name, password = credentials
                self.config.update_user_info(login_name=login_name, password=password)
                success, err_type = self.session_mgr.relogin()
            else:
                success, err_type = self.session_mgr.login()
            self.root.after(0, self._login_callback, success, err_type, dlg)

        threading.Thread(target=worker, daemon=True).start()

    def _account_status_text(self) -> str:
        user = self.config.get_user_info()
        login_name = user.get("login_name", "")
        name = self.session_mgr.name or ""
        uid = self.session_mgr.uid or ""
        if name and uid:
            return f"已登录：{name}（学号 {login_name}，预约身份 uid={uid}）"
        if login_name:
            return f"已登录：学号 {login_name}"
        return "已登录"

    def _update_account_display(self):
        if hasattr(self, "account_label"):
            if self._logged_in:
                self.account_label.config(text=self._account_status_text())
            else:
                self.account_label.config(
                    text="未登录 — 请点击「登录 / 切换账号」后再添加方案",
                )

    def _login_callback(self, success, err_type, dlg):
        if success:
            self._logged_in = True
            self.config.save()
            self._update_account_display()
            self.status_bar.config(text=self._account_status_text() + " | 正在加载房间列表…")
            if self._on_login_success:
                self._on_login_success(self._account_status_text())
            if dlg and dlg.winfo_exists():
                dlg.destroy()
            self._rooms_ready = False
            self.room_cache.stop_background_refresh()
            self.room_cache.reset()
            self.room_cache.start_background_refresh()

            def _ensure_rooms():
                self.room_cache.wait_until_ready(timeout=180)
                if not self.room_cache.get_room_names():
                    self.root.after(
                        0,
                        lambda: messagebox.showwarning(
                            "房间列表",
                            "房间数据加载失败。请确认已连接校园网/VPN，并重新登录。",
                            parent=self.root,
                        ),
                    )
                    self.root.after(
                        0,
                        lambda: self.status_bar.config(
                            text=self._account_status_text() + " | 房间加载失败，请重新登录",
                        ),
                    )

            threading.Thread(target=_ensure_rooms, daemon=True, name="RoomLoadWait").start()
        else:
            detail = getattr(self.session_mgr, "last_login_detail", "") or ""
            if err_type == "network":
                msg = "网络连接失败，请检查 VPN/校园网是否可访问 hdu.huitu.zhishulib.com"
            else:
                msg = "登录失败：请检查学号与图书馆登录密码"
            if detail:
                msg = f"{msg}\n{detail}"
            if dlg and dlg.winfo_exists():
                dlg._status_label.config(text=msg, foreground="red")
            else:
                self._show_login_dialog(msg)

    def _on_rooms_ready(self):
        self._rooms_ready = True
        n = len(self.room_cache.get_room_names())

        def _ui():
            self._refresh_plans_tree()
            self.status_bar.config(
                text=self._account_status_text() + f" | 已加载 {n} 个房间，可添加方案",
            )

        self.root.after(0, _ui)

    def _exit_from_dialog(self, dlg):
        dlg.destroy()
        if not self._embedded:
            self._on_closing()

    # ================================================================
    # Plans Management
    # ================================================================

    def _refresh_plans_tree(self):
        for item in self.plans_tree.get_children():
            self.plans_tree.delete(item)
        plans = self.config.get_plans()
        for i, plan in enumerate(plans):
            seats_str = ",".join(s.seat_num for s in plan.seats)
            self.plans_tree.insert("", tk.END, iid=str(i), values=(
                i + 1, plan.id, plan.room_name, plan.floor_name,
                seats_str, plan.begin_time, f"{plan.duration_hours}小时",
            ))

    def _add_plan_dialog(self):
        if not self._logged_in:
            messagebox.showwarning("提示", "请先登录图书馆账号", parent=self.root)
            self._show_login_dialog()
            return
        if not self._rooms_ready:
            messagebox.showwarning(
                "提示",
                "房间数据尚未加载完成，请稍候或重新登录。\n"
                "（需连接校园网/VPN，登录成功后自动拉取房间列表）",
                parent=self.root,
            )
            return

        rooms = self.room_cache.rooms
        if not rooms:
            messagebox.showerror("错误", "无法获取房间信息，请检查网络连接")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("添加方案")
        dlg.geometry("420x380")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_on_parent(dlg, 420, 380)

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        room_names = list(rooms.keys())

        # Room
        ttk.Label(frame, text="房间类型:").grid(row=0, column=0, sticky=tk.W, pady=4)
        room_var = tk.StringVar()
        room_combo = ttk.Combobox(frame, textvariable=room_var, values=room_names, state="readonly", width=22)
        room_combo.grid(row=0, column=1, pady=4)

        # Floor
        ttk.Label(frame, text="楼层:").grid(row=1, column=0, sticky=tk.W, pady=4)
        floor_var = tk.StringVar()
        floor_combo = ttk.Combobox(frame, textvariable=floor_var, state="readonly", width=22)
        floor_combo.grid(row=1, column=1, pady=4)

        # Hours hint
        hours_label = ttk.Label(frame, text="", foreground="gray")
        hours_label.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=2)

        # Time
        ttk.Label(frame, text="开始时间:").grid(row=3, column=0, sticky=tk.W, pady=4)
        time_var = tk.StringVar(value="08:00:00")
        ttk.Entry(frame, textvariable=time_var, width=25).grid(row=3, column=1, pady=4)

        # Duration
        ttk.Label(frame, text="使用时长(小时):").grid(row=4, column=0, sticky=tk.W, pady=4)
        dur_var = tk.StringVar(value="4")
        dur_spin = ttk.Spinbox(frame, from_=1, to=24, textvariable=dur_var, width=22)
        dur_spin.grid(row=4, column=1, pady=4)

        # Seats
        ttk.Label(frame, text="座位号(逗号分隔):").grid(row=5, column=0, sticky=tk.W, pady=4)
        seats_var = tk.StringVar()
        ttk.Entry(frame, textvariable=seats_var, width=25).grid(row=5, column=1, pady=4)

        # Plan ID
        ttk.Label(frame, text="方案ID:").grid(row=6, column=0, sticky=tk.W, pady=4)
        plan_id_var = tk.StringVar()
        ttk.Entry(frame, textvariable=plan_id_var, width=25).grid(row=6, column=1, pady=4)

        def on_room_selected(event):
            room_name = room_var.get()
            floors = self.room_cache.get_floor_names(room_name)
            floor_combo["values"] = floors
            floor_var.set("")
            if floors:
                floor_var.set(floors[0])
            range_info = rooms[room_name].get("range", {})
            min_h = range_info.get("minBeginTime", 0)
            max_h = range_info.get("maxEndTime", 24)
            hours_label.config(text=f"开放时间: {min_h}:00-{max_h}:00")
            dur_spin.config(to=max_h)

        room_combo.bind("<<ComboboxSelected>>", on_room_selected)
        if room_names:
            room_var.set(room_names[0])
            on_room_selected(None)

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=7, column=0, columnspan=2, pady=15)
        ttk.Button(
            btn_frame, text="确认",
            command=lambda: self._confirm_add_plan(dlg, room_var, floor_var, time_var, dur_var, seats_var, plan_id_var),
        ).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=10)

    def _confirm_add_plan(self, dlg, room_var, floor_var, time_var, dur_var, seats_var, plan_id_var):
        room_name = room_var.get().strip()
        floor_name = floor_var.get().strip()
        time_str = time_var.get().strip()
        seats_input = seats_var.get().strip()
        plan_id = plan_id_var.get().strip()

        if not room_name or not floor_name:
            messagebox.showerror("错误", "请选择房间和楼层", parent=dlg)
            return

        # Validate time format
        if not re.match(r"^\d{2}:\d{2}:\d{2}$", time_str):
            messagebox.showerror("错误", "时间格式不正确，请使用 HH:MM:SS 格式", parent=dlg)
            return

        try:
            duration = int(dur_var.get())
        except ValueError:
            messagebox.showerror("错误", "请输入有效的时长", parent=dlg)
            return
        if duration < 1:
            messagebox.showerror("错误", "时长不能小于1小时", parent=dlg)
            return

        # Validate start_time + duration <= 22:00
        hour = int(time_str.split(":")[0])
        if hour + duration > 22:
            messagebox.showerror(
                "错误",
                f"开始时间({hour}:00) + 使用时长({duration}小时) = {hour + duration}:00，"
                f"超过了图书馆最晚预约时间22:00",
                parent=dlg,
            )
            return

        # Validate time within room hours
        rooms = self.room_cache.rooms
        range_info = rooms[room_name].get("range", {})
        min_hour = range_info.get("minBeginTime", 0)
        max_hour = range_info.get("maxEndTime", 24)
        if hour < min_hour or hour > max_hour:
            messagebox.showerror(
                "错误",
                f"开始时间不在房间开放时间内({min_hour}:00-{max_hour}:00)",
                parent=dlg,
            )
            return

        # Validate seats
        seat_nums = [s.strip() for s in seats_input.replace("，", ",").split(",") if s.strip()]
        if not seat_nums:
            messagebox.showerror("错误", "请输入至少一个座位号", parent=dlg)
            return

        seats_info = self.room_cache.get_seats(room_name, floor_name)
        seat_list = []
        for seat_num in seat_nums:
            matched = [s for s in seats_info if s["title"] == seat_num]
            if not matched:
                messagebox.showerror("错误", f"{floor_name}中座位{seat_num}不存在", parent=dlg)
                return
            if len(matched) > 1:
                messagebox.showerror("错误", f"座位{seat_num}存在多个匹配", parent=dlg)
                return
            seat_list.append(SeatInfo(seat_id=str(matched[0]["id"]), seat_num=matched[0]["title"]))

        if not plan_id:
            plan_id = f"plan_{datetime.now().strftime('%H%M%S')}"

        plan = Plan(
            id=plan_id, room_name=room_name, floor_name=floor_name,
            begin_time=time_str, duration_hours=duration, seats=seat_list,
        )
        self.config.add_plan(plan)
        self._refresh_plans_tree()
        dlg.destroy()

    def _delete_selected_plans(self):
        selected = self.plans_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要删除的方案")
            return

        plans = self.config.get_plans()
        indices = sorted(int(iid) for iid in selected)
        if any(idx < 0 or idx >= len(plans) for idx in indices):
            messagebox.showerror("错误", "选中的序号超出范围")
            return

        if not messagebox.askyesno("确认", f"确定要删除{len(indices)}个方案吗？"):
            return

        plan_ids = [plans[idx].id for idx in indices]
        for pid in plan_ids:
            self.config.delete_plan(pid)
        self._refresh_plans_tree()

    def _batch_change_time_dialog(self):
        selected = self.plans_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要修改的方案")
            return

        plans = self.config.get_plans()
        indices = [int(iid) for iid in selected]

        dlg = tk.Toplevel(self.root)
        dlg.title("批量修改时间")
        dlg.geometry("360x200")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_on_parent(dlg, 360, 200)

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=f"已选择 {len(indices)} 个方案", foreground="blue").grid(
            row=0, column=0, columnspan=2, pady=5,
        )
        ttk.Label(frame, text="错误的时间可能导致封号一周，请仔细检查。", foreground="red").grid(
            row=1, column=0, columnspan=2, pady=2,
        )

        ttk.Label(frame, text="开始时间(HH:MM:SS):").grid(row=2, column=0, sticky=tk.W, pady=5)
        time_var = tk.StringVar(value="08:00:00")
        ttk.Entry(frame, textvariable=time_var, width=15).grid(row=2, column=1, pady=5)

        ttk.Label(frame, text="使用时长(小时):").grid(row=3, column=0, sticky=tk.W, pady=5)
        dur_var = tk.StringVar(value="4")
        ttk.Spinbox(frame, from_=1, to=24, textvariable=dur_var, width=13).grid(row=3, column=1, pady=5)

        def confirm():
            time_str = time_var.get().strip()
            if not re.match(r"^\d{2}:\d{2}:\d{2}$", time_str):
                messagebox.showerror("错误", "时间格式不正确", parent=dlg)
                return
            try:
                duration = int(dur_var.get())
            except ValueError:
                messagebox.showerror("错误", "请输入有效时长", parent=dlg)
                return
            if duration < 1:
                messagebox.showerror("错误", "时长不能小于1", parent=dlg)
                return

            # Validate start_time + duration <= 22:00
            batch_hour = int(time_str.split(":")[0])
            if batch_hour + duration > 22:
                messagebox.showerror(
                    "错误",
                    f"开始时间({batch_hour}:00) + 使用时长({duration}小时) = "
                    f"{batch_hour + duration}:00，超过了图书馆最晚预约时间22:00",
                    parent=dlg,
                )
                return

            all_plans = self.config.config.get("plans", [])
            for idx in indices:
                if idx < len(all_plans):
                    all_plans[idx]["begin_time"] = time_str
                    all_plans[idx]["duration_hours"] = duration
            self.config.save()
            self._refresh_plans_tree()
            dlg.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=15)
        ttk.Button(btn_frame, text="确认", command=confirm).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=10)

    # ================================================================
    # Booking
    # ================================================================

    def _refresh_booking_plans_tree(self):
        for item in self.booking_tree.get_children():
            self.booking_tree.delete(item)
        plans = self.config.get_plans()
        for plan in plans:
            seats_str = ",".join(s.seat_num for s in plan.seats)
            self.booking_tree.insert("", tk.END, values=(
                plan.id, plan.room_name, plan.floor_name,
                seats_str, plan.begin_time, f"{plan.duration_hours}小时",
            ))

    def _start_booking(self):
        if not self._logged_in:
            messagebox.showwarning("提示", "请先登录")
            return
        plans = self.config.get_plans()
        if not plans:
            messagebox.showwarning("提示", "没有预约方案，请先添加方案")
            return
        # Pre-run validation
        errors = []
        for plan in plans:
            errors.extend(plan.validate())
        if errors:
            messagebox.showerror("方案校验失败", "\n".join(errors))
            return

        self._booking_cancel.clear()
        self.booking_start_btn.config(state=tk.DISABLED)
        self.booking_stop_btn.config(state=tk.NORMAL)

        # Clear log
        self.booking_log.configure(state=tk.NORMAL)
        self.booking_log.delete("1.0", tk.END)
        self.booking_log.configure(state=tk.DISABLED)

        threading.Thread(target=self._booking_thread_func, daemon=True).start()

    def _cancel_booking(self):
        self._booking_cancel.set()

    def _booking_thread_func(self):
        plans = self.config.get_plans()
        settings = self.config.get_settings()

        for retry in range(settings["max_try_times"]):
            if self._booking_cancel.is_set():
                self.root.after(0, self._append_booking_log, "已取消", "warning")
                break

            ts = datetime.now().strftime("%H:%M:%S")
            self.root.after(
                0, self._append_booking_log,
                f"[{ts}] 第{retry + 1}次尝试...", "info",
            )
            self.root.after(
                0, self._update_booking_progress,
                f"第{retry + 1}次尝试 / 最大{settings['max_try_times']}次",
            )

            for plan in plans:
                if self._booking_cancel.is_set():
                    break

                now = datetime.now()
                h, m, s = (int(x) for x in plan.begin_time.split(":"))
                begin_time = now.replace(hour=h, minute=m, second=s, microsecond=0)

                seat_ids = [seat.seat_id for seat in plan.seats]
                booker_uids = [self.session_mgr.uid] * len(plan.seats)

                try:
                    resp = self.api.book_seat(begin_time, plan.duration_hours, seat_ids, booker_uids)
                    result = BookingResult.from_api_response(resp, plan_id=plan.id)
                except Exception as e:
                    result = BookingResult(
                        success=False, code="error", message=str(e), plan_id=plan.id,
                    )

                self.history.log(result)
                ts = datetime.now().strftime("%H:%M:%S")

                if result.success:
                    self.root.after(
                        0, self._append_booking_log,
                        f"[{ts}] 方案 {plan.id} 预约成功！", "success",
                    )
                    self.root.after(
                        0, self._append_booking_log,
                        f"  房间: {plan.room_name} | 楼层: {plan.floor_name} | "
                        f"座位: {','.join(s.seat_num for s in plan.seats)} | "
                        f"时间: {plan.begin_time} | 时长: {plan.duration_hours}小时",
                        "success",
                    )
                    self.root.after(0, self._on_booking_complete, True)
                    return
                else:
                    self.root.after(
                        0, self._append_booking_log,
                        f"[{ts}] 方案 {plan.id} 预约失败: {result.message}", "error",
                    )

            if self._booking_cancel.is_set():
                break

            if retry < settings["max_try_times"] - 1:
                self.root.after(
                    0, self._append_booking_log,
                    f"等待{settings['interval']}秒后重试...", "info",
                )
                self._booking_cancel.wait(timeout=settings["interval"])

        self.root.after(0, self._on_booking_complete, False)

    def _append_booking_log(self, message, tag="info"):
        self.booking_log.configure(state=tk.NORMAL)
        self.booking_log.insert(tk.END, message + "\n", tag)
        self.booking_log.see(tk.END)
        self.booking_log.configure(state=tk.DISABLED)

    def _update_booking_progress(self, text):
        if self.booking_progress_label.winfo_exists():
            self.booking_progress_label.config(text=text)

    def _on_booking_complete(self, success):
        self.booking_start_btn.config(state=tk.NORMAL)
        self.booking_stop_btn.config(state=tk.DISABLED)
        if success:
            self.booking_progress_label.config(text="预约成功")
        else:
            self.booking_progress_label.config(text="预约结束")

    # ================================================================
    # Schedule Management
    # ================================================================

    def _refresh_schedules_tree(self):
        for item in self.schedules_tree.get_children():
            self.schedules_tree.delete(item)
        schedules = self.config.get_schedules()
        plan_map = {p.id: p for p in self.config.get_plans()}

        for i, s in enumerate(schedules):
            status = "● 启用" if s.enabled else "○ 禁用"
            if s.mode == "weekdays":
                s_type = "按星期"
                target = ", ".join(WEEKDAY_NAMES[w - 1] for w in s.target_weekdays)
                plan_descs = []
                for pid in s.plan_ids:
                    p = plan_map.get(pid)
                    if p:
                        seats_str = ",".join(seat.seat_num for seat in p.seats)
                        plan_descs.append(f"{pid}({p.room_name} {seats_str}号)")
                    else:
                        plan_descs.append(f"{pid}(不存在)")
                plans_str = ", ".join(plan_descs)
            elif s.mode == "dates":
                s_type = "按日期"
                dates_str = ", ".join(m.target_date for m in s.mappings)
                target = dates_str
                all_pids = set()
                for m in s.mappings:
                    all_pids.update(m.plan_ids)
                plan_descs = []
                for pid in all_pids:
                    p = plan_map.get(pid)
                    if p:
                        seats_str = ",".join(seat.seat_num for seat in p.seats)
                        plan_descs.append(f"{pid}({p.room_name} {seats_str}号)")
                    else:
                        plan_descs.append(f"{pid}(不存在)")
                plans_str = ", ".join(plan_descs)
            else:
                continue

            tag = "enabled" if s.enabled else "disabled"
            self.schedules_tree.insert("", tk.END, iid=str(i), values=(
                i + 1, s_type, target, status, plans_str,
            ), tags=(tag,))

    def _start_scheduler(self):
        if not self._logged_in:
            messagebox.showwarning("提示", "请先登录")
            return
        schedules = self.config.get_schedules()
        active = [s for s in schedules if s.enabled]
        if not active:
            messagebox.showwarning("提示", "没有启用的调度，请先添加调度")
            return
        plans = self.config.get_plans()
        if not plans:
            messagebox.showwarning("提示", "没有预约方案，请先添加方案")
            return
        # Pre-run validation
        errors = []
        for plan in plans:
            errors.extend(plan.validate())
        if errors:
            messagebox.showerror("方案校验失败", "\n".join(errors))
            return

        self.engine.start()
        self.scheduler_status_label.config(text="● 调度运行中", fg="green")
        self.status_bar.config(text="调度引擎已启动")
        self._schedule_status_refresh()

    def _stop_scheduler(self):
        if self.engine.is_running:
            self.engine.stop()
            self.scheduler_status_label.config(text="● 调度未运行", fg="red")
            self.status_bar.config(text="调度引擎已停止")
        else:
            messagebox.showinfo("提示", "调度引擎未在运行")

    def _add_weekday_schedule_dialog(self):
        plans = self.config.get_plans()
        if not plans:
            messagebox.showwarning("提示", "请先添加方案")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("添加按星期调度")
        dlg.geometry("400x300")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_on_parent(dlg, 400, 300)

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="选择星期:").grid(row=0, column=0, sticky=tk.W, pady=5)

        cb_frame = ttk.Frame(frame)
        cb_frame.grid(row=0, column=1, sticky=tk.W, pady=5)

        weekday_vars = []
        for i, name in enumerate(WEEKDAY_NAMES):
            var = tk.BooleanVar()
            ttk.Checkbutton(cb_frame, text=name, variable=var).grid(
                row=i // 4, column=i % 4, sticky=tk.W, padx=5,
            )
            weekday_vars.append(var)

        ttk.Label(frame, text="方案ID(逗号分隔):").grid(row=1, column=0, sticky=tk.W, pady=8)
        plan_ids_var = tk.StringVar()
        ttk.Entry(frame, textvariable=plan_ids_var, width=30).grid(row=1, column=1, pady=8)

        plan_ids_str = ", ".join(p.id for p in plans)
        ttk.Label(frame, text=f"可用方案: {plan_ids_str}", foreground="gray").grid(
            row=2, column=0, columnspan=2, sticky=tk.W,
        )

        def confirm():
            weekdays = [i + 1 for i, v in enumerate(weekday_vars) if v.get()]
            if not weekdays:
                messagebox.showerror("错误", "至少需要选择一天", parent=dlg)
                return
            pids = [p.strip() for p in plan_ids_var.get().replace("，", ",").split(",") if p.strip()]
            if not pids:
                messagebox.showerror("错误", "请输入方案ID", parent=dlg)
                return
            valid_ids = {p.id for p in plans}
            for pid in pids:
                if pid not in valid_ids:
                    messagebox.showerror("错误", f"方案ID '{pid}' 不存在", parent=dlg)
                    return
            schedule = Schedule(mode="weekdays", target_weekdays=sorted(set(weekdays)), plan_ids=pids)
            schedules = self.config.get_schedules()
            schedules.append(schedule)
            self.config.save_schedules(schedules)
            self._refresh_schedules_tree()
            dlg.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="确认", command=confirm).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=10)

    def _add_date_schedule_dialog(self):
        plans = self.config.get_plans()
        if not plans:
            messagebox.showwarning("提示", "请先添加方案")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("添加按日期调度")
        dlg.geometry("400x250")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_on_parent(dlg, 400, 250)

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="日期(YYYY-MM-DD，逗号分隔):").grid(row=0, column=0, sticky=tk.W, pady=8)
        dates_var = tk.StringVar()
        ttk.Entry(frame, textvariable=dates_var, width=30).grid(row=0, column=1, pady=8)

        ttk.Label(frame, text="方案ID(逗号分隔):").grid(row=1, column=0, sticky=tk.W, pady=8)
        plan_ids_var = tk.StringVar()
        ttk.Entry(frame, textvariable=plan_ids_var, width=30).grid(row=1, column=1, pady=8)

        plan_ids_str = ", ".join(p.id for p in plans)
        ttk.Label(frame, text=f"可用方案: {plan_ids_str}", foreground="gray").grid(
            row=2, column=0, columnspan=2, sticky=tk.W,
        )

        def confirm():
            dates_input = dates_var.get().strip().replace("，", ",")
            dates = [d.strip() for d in dates_input.split(",") if d.strip()]
            if not dates:
                messagebox.showerror("错误", "请输入至少一个日期", parent=dlg)
                return
            for d in dates:
                try:
                    datetime.strptime(d, "%Y-%m-%d")
                except ValueError:
                    messagebox.showerror("错误", f"日期格式不正确: {d}", parent=dlg)
                    return
            pids = [p.strip() for p in plan_ids_var.get().replace("，", ",").split(",") if p.strip()]
            if not pids:
                messagebox.showerror("错误", "请输入方案ID", parent=dlg)
                return
            valid_ids = {p.id for p in plans}
            for pid in pids:
                if pid not in valid_ids:
                    messagebox.showerror("错误", f"方案ID '{pid}' 不存在", parent=dlg)
                    return

            mappings = [DateMapping(target_date=d, plan_ids=pids) for d in dates]
            schedule = Schedule(mode="dates", mappings=mappings)
            schedules = self.config.get_schedules()
            schedules.append(schedule)
            self.config.save_schedules(schedules)
            self._refresh_schedules_tree()
            dlg.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="确认", command=confirm).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=10)

    def _delete_selected_schedules(self):
        selected = self.schedules_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要删除的调度")
            return

        schedules = self.config.get_schedules()
        indices = sorted(int(iid) for iid in selected)
        if any(idx < 0 or idx >= len(schedules) for idx in indices):
            messagebox.showerror("错误", "选中的序号超出范围")
            return

        if not messagebox.askyesno("确认", f"确定要删除{len(indices)}个调度吗？"):
            return

        # Delete in reverse order
        for idx in reversed(indices):
            schedules.pop(idx)
        self.config.save_schedules(schedules)
        self._refresh_schedules_tree()

    def _toggle_schedule_enabled(self):
        selected = self.schedules_tree.selection()
        if not selected:
            messagebox.showinfo("提示", "请先选择要切换的调度")
            return

        schedules = self.config.get_schedules()
        indices = [int(iid) for iid in selected]
        if any(idx < 0 or idx >= len(schedules) for idx in indices):
            messagebox.showerror("错误", "选中的序号超出范围")
            return

        for idx in indices:
            schedules[idx].enabled = not schedules[idx].enabled

        self.config.save_schedules(schedules)
        self._refresh_schedules_tree()

    # ================================================================
    # Status
    # ================================================================

    def _update_status_display(self):
        if not self.status_labels:
            return
        try:
            if self.engine.is_running:
                self.status_labels["engine"].config(text="● 运行中", foreground="green")
                status = self.engine.get_status()
                trigger = status.get("trigger_time")
                remaining = status.get("remaining_seconds")
                plan_ids = status.get("plan_ids", [])

                if trigger:
                    self.status_labels["trigger"].config(
                        text=trigger.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                else:
                    self.status_labels["trigger"].config(text="等待中...")

                if remaining is not None:
                    self.status_labels["remaining"].config(text=format_countdown(remaining))
                else:
                    self.status_labels["remaining"].config(text="—")

                self.status_labels["plans"].config(text=", ".join(plan_ids) if plan_ids else "—")
            else:
                self.status_labels["engine"].config(text="● 未运行", foreground="red")
                self.status_labels["trigger"].config(text="—")
                self.status_labels["remaining"].config(text="—")
                self.status_labels["plans"].config(text="—")
        except tk.TclError:
            pass  # Widget already destroyed

    def _schedule_status_refresh(self):
        """Periodically refresh status display while engine runs."""
        try:
            self._update_status_display()
            if self.engine.is_running:
                self.scheduler_status_label.config(text="● 调度运行中", fg="green")
                self.root.after(1000, self._schedule_status_refresh)
        except tk.TclError:
            pass

    # ================================================================
    # Settings
    # ================================================================

    def _load_settings(self):
        settings = self.config.get_settings()
        self.interval_var.set(str(settings["interval"]))
        self.max_try_var.set(str(settings["max_try_times"]))

    def _save_settings(self):
        try:
            interval = int(self.interval_var.get())
            max_try = int(self.max_try_var.get())
        except ValueError:
            messagebox.showerror("错误", "请输入有效数字")
            return
        if interval < 1:
            messagebox.showerror("错误", "间隔不能小于1秒")
            return
        if max_try < 1:
            messagebox.showerror("错误", "重试次数不能小于1")
            return

        self.config.update_settings(interval=interval, max_try_times=max_try)
        self.runner.interval = interval
        self.runner.max_try_times = max_try
        messagebox.showinfo("成功", "设置已保存")

    # ================================================================
    # Help
    # ================================================================

    def _load_help(self):
        from hdu_killer.paths import get_seat_manual_path

        help_path = get_seat_manual_path()
        content = ""
        if help_path.is_file():
            content = help_path.read_text(encoding="utf-8")
        else:
            content = "使用手册未找到（docs/图书馆抢座使用手册.txt）"

        self.help_text.configure(state=tk.NORMAL)
        self.help_text.delete("1.0", tk.END)
        self.help_text.insert(tk.END, content)
        self.help_text.configure(state=tk.DISABLED)

    # ================================================================
    # Engine Callbacks (called from engine thread)
    # ================================================================

    def _on_countdown_tick(self, remaining, trigger_time, plan_desc):
        try:
            self.root.after(0, self._update_countdown_display, remaining, trigger_time, plan_desc)
        except RuntimeError:
            pass  # root destroyed

    def _update_countdown_display(self, remaining, trigger_time, plan_desc):
        remaining_str = format_countdown(remaining)
        trigger_str = trigger_time.strftime("%m-%d %H:%M")
        self.status_bar.config(
            text=f"调度运行中 | 下次触发: {trigger_str} | "
                 f"剩余: {remaining_str} | 方案: {plan_desc}",
        )

    def _on_booking_result(self, result: BookingResult):
        self.history.log(result)
        ts = datetime.now().strftime("%H:%M:%S")
        if result.success:
            msg = f"[{ts}] [调度] 预约成功: {result}"
            tag = "success"
        else:
            msg = f"[{ts}] [调度] 预约失败: {result.message}"
            tag = "warning"
        try:
            self.root.after(0, self._append_booking_log, msg, tag)
        except RuntimeError:
            pass

    def _on_booking_start(self, target_date, plan_ids):
        ts = datetime.now().strftime("%H:%M:%S")
        msg = (f"[{ts}] 预约开放时间已到达，正在为"
               f"{target_date.strftime('%Y-%m-%d')}执行预约...")
        try:
            self.root.after(0, self._append_booking_log, msg, "info")
        except RuntimeError:
            pass

    def _on_engine_error(self, error):
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"[{ts}] 调度引擎错误: {error}"
        try:
            self.root.after(0, self._append_booking_log, msg, "error")
        except RuntimeError:
            pass

    # ================================================================
    # Utilities
    # ================================================================

    def _center_on_parent(self, dlg, w, h):
        dlg.update_idletasks()
        px = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{px}+{py}")

    # ================================================================
    # Lifecycle
    # ================================================================

    def shutdown(self):
        """Stop background tasks without destroying the root window."""
        if self.engine.is_running:
            self.engine.stop()
        if self.room_cache.is_ready:
            self.room_cache.stop_background_refresh()

    def _on_closing(self):
        self.shutdown()
        if not self._embedded:
            self.root.destroy()
