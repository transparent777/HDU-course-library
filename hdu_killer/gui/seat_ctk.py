"""CustomTkinter 图书馆抢座（简化版）."""

from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import Callable, Optional

import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox, ttk

from hdu_killer.gui.manual_viewer import ManualViewer
from hdu_killer.gui.seat_service import SeatServices
from hdu_killer.gui.typography import (
    apply_fonts_to_ctk_tree,
    apply_ttk_scale,
    apply_ttk_theme,
    body_font,
    title_font,
)
from hdu_killer.gui.ui_scheduler import MainThreadUi
from hdu_killer.seat.models.booking_result import BookingResult
from hdu_killer.seat.models.plan import Plan, SeatInfo
from hdu_killer.seat.models.schedule import DateMapping, Schedule
from hdu_killer.seat.scheduler.booking_runner import WEEKDAY_NAMES
from hdu_killer.seat.ui.display import format_countdown


def _plan_begin_datetime(target_day: datetime, plan: Plan) -> datetime:
    parts = plan.begin_time.strip().split(":")
    if len(parts) < 2:
        raise ValueError(f"方案「{plan.id}」时间格式无效：{plan.begin_time}")
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) > 2 else 0
    return target_day.replace(hour=h, minute=m, second=s, microsecond=0)


def _expired_plan_lines(plans: list[Plan], target_day: datetime, now: datetime) -> list[str]:
    lines: list[str] = []
    for p in plans:
        begin = _plan_begin_datetime(target_day, p)
        if begin <= now:
            lines.append(
                f"· {p.id}：{begin.strftime('%Y-%m-%d %H:%M')}（当前 {now.strftime('%H:%M:%S')}）"
            )
    return lines


class SeatWorkspace(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkFrame,
        services: SeatServices,
        tk_root: ctk.CTk,
        on_status: Callable[[str], None],
        ui: MainThreadUi,
        compact_status_var: Optional[tk.StringVar] = None,
        on_enter_compact: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._svc = services
        self._win = tk_root
        self._ui = ui
        self._on_status = on_status
        self._compact_status = compact_status_var
        self._on_enter_compact = on_enter_compact
        self._scale = float(getattr(tk_root, "_hdu_ui_scale", 1.0))
        self._font = body_font(self._scale)
        self._font_title = title_font(self._scale)
        self._logged_in = False
        self._rooms_ready = False
        self._booking_cancel = threading.Event()
        self._ttk_hosts: list[tk.Frame] = []

        self._svc.rooms.on_ready(self._on_rooms_ready)
        self._svc.engine.on_countdown_tick = self._on_countdown
        self._svc.engine.on_booking_result = self._on_engine_result
        self._svc.engine.on_error = self._on_engine_error

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        self._account_label = ctk.CTkLabel(top, text="未登录", anchor="w", font=self._font)
        self._account_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            top,
            text="收纳小窗",
            width=88,
            height=36,
            font=self._font,
            fg_color=("gray75", "gray30"),
            command=self._request_compact,
        ).pack(side="right", padx=(4, 0))
        ctk.CTkButton(
            top,
            text="使用手册",
            width=88,
            height=36,
            font=self._font,
            fg_color="gray40",
            command=self._open_manual,
        ).pack(side="right", padx=(4, 0))
        ctk.CTkButton(
            top,
            text="登录 / 切换",
            width=120,
            height=36,
            font=self._font,
            command=self._login_dialog,
        ).pack(side="right", padx=(4, 0))

        nav = ctk.CTkSegmentedButton(
            self,
            values=["我的方案", "立刻抢座", "定时抢座", "记录"],
            command=self._switch_page,
            font=self._font,
            height=36,
        )
        nav.set("我的方案")
        nav.pack(fill="x", pady=(0, 8))
        self._nav = nav

        self._pages = ctk.CTkFrame(self, fg_color="transparent")
        self._pages.pack(fill="both", expand=True)
        self._page_plans = ctk.CTkFrame(self._pages, fg_color="transparent")
        self._page_now = ctk.CTkFrame(self._pages, fg_color="transparent")
        self._page_sched = ctk.CTkFrame(self._pages, fg_color="transparent")
        self._page_hist = ctk.CTkFrame(self._pages, fg_color="transparent")
        for p in (self._page_plans, self._page_now, self._page_sched, self._page_hist):
            p.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_plans_page()
        self._build_now_page()
        self._build_sched_page()
        self._build_hist_page()
        self._switch_page("我的方案")

        self._win.after(400, self._auto_login)
        self.apply_theme()

    def apply_theme(self) -> None:
        colors = apply_ttk_theme(self._win)
        apply_ttk_scale(self._win, self._scale)
        for host in self._ttk_hosts:
            try:
                host.configure(bg=colors["bg"])
            except Exception:
                pass

    def shutdown(self, fast: bool = False) -> None:
        self._booking_cancel.set()
        try:
            self._svc.runner.cancel()
        except Exception:
            pass
        if fast:
            self._svc.engine.stop_fast()
            self._svc.rooms.stop_background_refresh(wait=False)
        else:
            self._svc.engine.stop()
            self._svc.rooms.stop_background_refresh(wait=True)

    def apply_ui_scale(self, scale: float) -> None:
        self._scale = float(scale)
        self._font = body_font(self._scale)
        self._font_title = title_font(self._scale)
        apply_fonts_to_ctk_tree(self, self._scale)
        apply_ttk_scale(self._win, self._scale)
        self.apply_theme()

    def _switch_page(self, name: str) -> None:
        self._nav.set(name)
        for p, n in (
            (self._page_plans, "我的方案"),
            (self._page_now, "立刻抢座"),
            (self._page_sched, "定时抢座"),
            (self._page_hist, "记录"),
        ):
            if n == name:
                p.lift()
        if name == "记录":
            self._refresh_history()
        if name == "定时抢座":
            self._refresh_schedules_tree()

    def _build_plans_page(self) -> None:
        bar = ctk.CTkFrame(self._page_plans, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        ctk.CTkButton(bar, text="添加方案", width=100, command=lambda: self._open_plan_dialog()).pack(
            side="left", padx=4
        )
        ctk.CTkButton(bar, text="编辑选中", width=100, command=self._edit_selected_plan).pack(
            side="left", padx=4
        )
        ctk.CTkButton(bar, text="删除选中", width=100, command=self._delete_plans).pack(
            side="left", padx=4
        )

        wrap = ctk.CTkFrame(self._page_plans, fg_color="transparent")
        wrap.pack(fill="both", expand=True, pady=8)
        colors = apply_ttk_theme(self._win)
        tk_host = tk.Frame(wrap, bg=colors["bg"], highlightthickness=0)
        tk_host.pack(fill="both", expand=True)
        self._ttk_hosts.append(tk_host)
        apply_ttk_scale(self._win, self._scale)
        cols = ("id", "room", "floor", "seats", "time", "dur")
        self._plans_tree = ttk.Treeview(tk_host, columns=cols, show="headings", height=9)
        for c, t, w in zip(
            cols,
            ("方案", "房间", "楼层", "座位", "开始", "时长"),
            (110, 140, 160, 90, 100, 70),
        ):
            self._plans_tree.heading(c, text=t)
            self._plans_tree.column(c, width=w)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._plans_tree.yview)
        self._plans_tree.configure(yscrollcommand=sb.set)
        self._plans_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._plans_tree.bind("<Double-1>", lambda _e: self._edit_selected_plan())
        self._refresh_plans()

    def _build_now_page(self) -> None:
        dr = ctk.CTkFrame(self._page_now, fg_color="transparent")
        dr.pack(fill="x", pady=4)
        ctk.CTkLabel(dr, text="预约日期", font=self._font).pack(side="left")
        self._now_date = ctk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        ctk.CTkEntry(dr, textvariable=self._now_date, width=140, font=self._font).pack(
            side="left", padx=8
        )

        row = ctk.CTkFrame(self._page_now, fg_color="transparent")
        row.pack(fill="x", pady=8)
        self._book_btn = ctk.CTkButton(
            row,
            text="开始抢座",
            width=140,
            height=40,
            font=self._font,
            command=self._start_booking,
        )
        self._book_btn.pack(side="left", padx=4)
        self._stop_btn = ctk.CTkButton(
            row,
            text="停止",
            width=100,
            height=40,
            font=self._font,
            command=self._stop_booking,
            state="disabled",
        )
        self._stop_btn.pack(side="left", padx=4)

        self._now_summary = ctk.CTkLabel(
            self._page_now,
            text="",
            font=self._font,
            wraplength=480,
            justify="left",
        )
        self._now_summary.pack(fill="x", pady=(8, 4))

        ctk.CTkLabel(self._page_now, text="运行日志", font=self._font, anchor="w").pack(
            anchor="w", pady=(4, 2)
        )
        self._now_log = ctk.CTkTextbox(self._page_now, height=160, font=self._font)
        self._now_log.pack(fill="both", expand=True, pady=(0, 8))
        self._now_log.configure(state="disabled")

    def _build_sched_page(self) -> None:
        bar = ctk.CTkFrame(self._page_sched, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        ctk.CTkButton(bar, text="按日期添加", width=100, command=self._add_schedule_dates_dialog).pack(
            side="left", padx=4
        )
        ctk.CTkButton(bar, text="按每周添加", width=100, command=self._add_schedule_weekdays_dialog).pack(
            side="left", padx=4
        )
        ctk.CTkButton(bar, text="删除选中", width=90, command=self._delete_schedules).pack(
            side="left", padx=4
        )
        ctk.CTkButton(bar, text="启用/停用", width=90, command=self._toggle_schedules).pack(
            side="left", padx=4
        )

        wrap = ctk.CTkFrame(self._page_sched, fg_color="transparent")
        wrap.pack(fill="both", expand=True, pady=6)
        colors = apply_ttk_theme(self._win)
        tk_host = tk.Frame(wrap, bg=colors["bg"], highlightthickness=0)
        tk_host.pack(fill="both", expand=True)
        self._ttk_hosts.append(tk_host)
        cols = ("mode", "target", "plans", "next", "on")
        self._sched_tree = ttk.Treeview(tk_host, columns=cols, show="headings", height=6)
        for c, t, w in zip(
            cols,
            ("类型", "目标", "方案", "下次放号", "状态"),
            (72, 120, 140, 150, 56),
        ):
            self._sched_tree.heading(c, text=t)
            self._sched_tree.column(c, width=w)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._sched_tree.yview)
        self._sched_tree.configure(yscrollcommand=sb.set)
        self._sched_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ctrl = ctk.CTkFrame(self._page_sched, fg_color="transparent")
        ctrl.pack(fill="x", pady=4)
        ctk.CTkButton(ctrl, text="启动定时", command=self._start_scheduler).pack(side="left", padx=4)
        ctk.CTkButton(ctrl, text="停止定时", command=self._stop_scheduler).pack(side="left", padx=4)
        self._sched_status = ctk.CTkLabel(ctrl, text="定时未运行", font=self._font)
        self._sched_status.pack(side="left", padx=12)

        self._sched_summary = ctk.CTkLabel(
            self._page_sched,
            text="",
            font=self._font,
            wraplength=480,
            justify="left",
        )
        self._sched_summary.pack(fill="x", pady=(4, 2))

        ctk.CTkLabel(self._page_sched, text="定时日志", font=self._font, anchor="w").pack(anchor="w")
        self._sched_log = ctk.CTkTextbox(self._page_sched, height=100, font=self._font)
        self._sched_log.pack(fill="both", expand=True, pady=(2, 8))
        self._sched_log.configure(state="disabled")
        self._refresh_schedules_tree()

    def _build_hist_page(self) -> None:
        self._hist_box = ctk.CTkTextbox(self._page_hist, font=self._font)
        self._hist_box.pack(fill="both", expand=True)
        self._hist_box.configure(state="disabled")

    def _refresh_plans(self) -> None:
        for iid in self._plans_tree.get_children():
            self._plans_tree.delete(iid)
        for plan in self._svc.config.get_plans():
            seats = ",".join(s.seat_num for s in plan.seats)
            self._plans_tree.insert(
                "",
                "end",
                iid=plan.id,
                values=(
                    plan.id,
                    plan.room_name,
                    plan.floor_name,
                    seats,
                    plan.begin_time,
                    f"{plan.duration_hours}h",
                ),
            )

    def _refresh_history(self) -> None:
        entries = self._svc.history.query(limit=40)
        self._hist_box.configure(state="normal")
        self._hist_box.delete("1.0", "end")
        if not entries:
            self._hist_box.insert("end", "暂无预约记录\n")
        else:
            for e in reversed(entries):
                mark = "成功" if e.get("success") else "失败"
                self._hist_box.insert(
                    "end",
                    f"{e.get('timestamp', '')} [{mark}] {e.get('plan_id', '')} "
                    f"{e.get('message', '')}\n",
                )
        self._hist_box.configure(state="disabled")

    def _account_text(self) -> str:
        u = self._svc.config.get_user_info()
        sid = u.get("login_name", "")
        if self._logged_in and self._svc.session.name:
            return f"{self._svc.session.name}（{sid}）"
        if sid:
            return f"学号 {sid}（未登录）"
        return "未登录"

    def _update_account(self) -> None:
        self._account_label.configure(text=self._account_text())

    def _auto_login(self) -> None:
        user = self._svc.config.get_user_info()
        if not user.get("login_name") or not user.get("password"):
            return

        def work() -> None:
            ok, _ = self._svc.session.login()
            if ok:
                self._logged_in = True
                self._svc.rooms.start_background_refresh()
                self._ui.call(self._update_account)
                self._ui.call(self._on_status, "图书馆已登录")

        threading.Thread(target=work, daemon=True).start()

    def _login_dialog(self) -> None:
        dlg = ctk.CTkToplevel(self._win)
        dlg.title("图书馆登录")
        dlg.geometry("520x300")
        dlg.minsize(520, 300)
        dlg.transient(self._win)
        dlg.grab_set()

        u = self._svc.config.get_user_info()
        sid = ctk.StringVar(value=u.get("login_name", ""))
        pwd = ctk.StringVar(value=u.get("password", ""))
        st = ctk.StringVar()

        box = ctk.CTkFrame(dlg)
        box.pack(fill="both", expand=True, padx=28, pady=24)

        ctk.CTkLabel(box, text="图书馆账号登录", font=self._font_title).pack(anchor="w", pady=(0, 16))

        def field(label: str, var: ctk.StringVar, secret: bool = False) -> None:
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", pady=10)
            ctk.CTkLabel(row, text=label, width=110, anchor="w", font=self._font).pack(side="left")
            kw = {"show": "*"} if secret else {}
            ctk.CTkEntry(row, textvariable=var, height=38, font=self._font, **kw).pack(
                side="left", fill="x", expand=True, padx=(8, 0)
            )

        field("学号", sid)
        field("图书馆密码", pwd, secret=True)

        ctk.CTkLabel(box, textvariable=st, text_color="orange", font=self._font, wraplength=440).pack(
            anchor="w", pady=(8, 0)
        )

        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(fill="x", pady=(20, 0))

        def do_login() -> None:
            st.set("登录中…")
            dlg.update_idletasks()
            self._svc.config.update_user_info(login_name=sid.get().strip(), password=pwd.get())

            def work() -> None:
                ok, err = self._svc.session.relogin()
                if not ok:
                    self._ui.call(st.set, f"失败：{err or '请检查网络'}")
                    return
                self._logged_in = True
                self._svc.rooms.start_background_refresh()
                self._svc.rooms.wait_until_ready(timeout=120)

                def done() -> None:
                    self._update_account()
                    self._on_status("图书馆已登录")
                    dlg.destroy()

                self._ui.call(done)

            threading.Thread(target=work, daemon=True).start()

        ctk.CTkButton(btns, text="取消", width=100, height=38, font=self._font, command=dlg.destroy).pack(
            side="left"
        )
        ctk.CTkButton(btns, text="登录", width=120, height=38, font=self._font, command=do_login).pack(
            side="right"
        )

    def _on_rooms_ready(self) -> None:
        def _apply() -> None:
            self._rooms_ready = True
            self._on_status("房间列表已加载")

        self._ui.call(_apply)

    def is_engine_running(self) -> bool:
        return self._svc.engine.is_running

    def _request_compact(self) -> None:
        if self._on_enter_compact:
            self._on_enter_compact()

    def _open_manual(self) -> None:
        ManualViewer.open(self._win, self._scale)

    def _edit_selected_plan(self) -> None:
        sel = self._plans_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中要编辑的方案", parent=self._win)
            return
        if len(sel) > 1:
            messagebox.showinfo("提示", "请只选中一个方案", parent=self._win)
            return
        plan = self._svc.config.get_plan_by_id(sel[0])
        if not plan:
            messagebox.showerror("错误", "方案不存在", parent=self._win)
            return
        self._open_plan_dialog(plan)

    def _open_plan_dialog(self, existing: Optional[Plan] = None) -> None:
        if not self._logged_in:
            messagebox.showwarning("提示", "请先登录", parent=self._win)
            self._login_dialog()
            return
        if not self._rooms_ready or not self._svc.rooms.rooms:
            messagebox.showwarning("提示", "房间数据加载中，请稍候或重新登录", parent=self._win)
            return

        rooms = self._svc.rooms.rooms
        editing = existing is not None
        dlg = ctk.CTkToplevel(self._win)
        dlg.title("编辑座位方案" if editing else "添加座位方案")
        dlg.geometry("440x420")
        dlg.transient(self._win)
        dlg.grab_set()

        if editing:
            room_var = ctk.StringVar(value=existing.room_name)
            floor_var = ctk.StringVar(value=existing.floor_name)
            time_var = ctk.StringVar(value=existing.begin_time)
            dur_var = ctk.StringVar(value=str(existing.duration_hours))
            seats_var = ctk.StringVar(
                value=",".join(s.seat_num for s in existing.seats),
            )
            pid_var = ctk.StringVar(value=existing.id)
        else:
            room_var = ctk.StringVar(value=list(rooms.keys())[0])
            floor_var = ctk.StringVar()
            time_var = ctk.StringVar(value="08:00:00")
            dur_var = ctk.StringVar(value="4")
            seats_var = ctk.StringVar()
            pid_var = ctk.StringVar()
        hint = ctk.CTkLabel(dlg, text="", text_color="gray")

        def refill_floors(_=None) -> None:
            rn = room_var.get()
            floors = self._svc.rooms.get_floor_names(rn)
            floor_menu.configure(values=floors if floors else [""])
            if floors:
                floor_var.set(floors[0])
            r = rooms.get(rn, {}).get("range", {})
            hint.configure(text=f"开放时段约 {r.get('minBeginTime', 0)}:00–{r.get('maxEndTime', 24)}:00")

        ctk.CTkLabel(dlg, text="房间").grid(row=0, column=0, padx=10, pady=6, sticky="w")
        ctk.CTkOptionMenu(dlg, variable=room_var, values=list(rooms.keys()), command=refill_floors).grid(
            row=0, column=1, pady=6
        )
        ctk.CTkLabel(dlg, text="楼层").grid(row=1, column=0, padx=10, pady=6, sticky="w")
        floor_menu = ctk.CTkOptionMenu(dlg, variable=floor_var, values=[""])
        floor_menu.grid(row=1, column=1, pady=6)
        hint.grid(row=2, column=0, columnspan=2, padx=10, sticky="w")
        ctk.CTkLabel(dlg, text="开始(HH:MM:SS)").grid(row=3, column=0, padx=10, pady=6, sticky="w")
        ctk.CTkEntry(dlg, textvariable=time_var, width=200).grid(row=3, column=1, pady=6)
        ctk.CTkLabel(dlg, text="时长(小时)").grid(row=4, column=0, padx=10, pady=6, sticky="w")
        ctk.CTkEntry(dlg, textvariable=dur_var, width=200).grid(row=4, column=1, pady=6)
        ctk.CTkLabel(dlg, text="座位号").grid(row=5, column=0, padx=10, pady=6, sticky="w")
        ctk.CTkEntry(dlg, textvariable=seats_var, width=200, placeholder_text="如 101 或 101,102").grid(
            row=5, column=1, pady=6
        )
        ctk.CTkLabel(dlg, text="方案名称").grid(row=6, column=0, padx=10, pady=6, sticky="w")
        pid_entry = ctk.CTkEntry(
            dlg,
            textvariable=pid_var,
            width=200,
            placeholder_text="可留空自动生成",
        )
        pid_entry.grid(row=6, column=1, pady=6)
        if editing:
            pid_entry.configure(state="disabled")
        refill_floors()
        if editing and existing.floor_name:
            floor_var.set(existing.floor_name)

        def confirm() -> None:
            try:
                pid = existing.id if editing else pid_var.get()
                plan = self._plan_from_form(
                    room_var.get(),
                    floor_var.get(),
                    time_var.get(),
                    dur_var.get(),
                    seats_var.get(),
                    pid,
                    rooms,
                )
            except ValueError as e:
                messagebox.showerror("错误", str(e), parent=dlg)
                return
            if editing:
                if not self._svc.config.replace_plan(plan):
                    messagebox.showerror("错误", "保存失败", parent=dlg)
                    return
            else:
                self._svc.config.add_plan(plan)
            self._refresh_plans()
            dlg.destroy()

        ctk.CTkButton(dlg, text="保存", command=confirm).grid(row=7, column=1, sticky="e", pady=16)
        ctk.CTkButton(dlg, text="取消", command=dlg.destroy).grid(row=7, column=0, padx=10, pady=16)

    def _plan_from_form(
        self,
        room_name: str,
        floor_name: str,
        time_str: str,
        dur_s: str,
        seats_input: str,
        plan_id: str,
        rooms: dict,
    ) -> Plan:
        if not room_name or not floor_name:
            raise ValueError("请选择房间和楼层")
        if not re.match(r"^\d{2}:\d{2}:\d{2}$", time_str.strip()):
            raise ValueError("时间格式应为 HH:MM:SS")
        duration = int(dur_s)
        hour = int(time_str.split(":")[0])
        if hour + duration > 22:
            raise ValueError("开始时间+时长不能超过 22:00")
        rng = rooms[room_name].get("range", {})
        if hour < rng.get("minBeginTime", 0) or hour > rng.get("maxEndTime", 24):
            raise ValueError("开始时间不在房间开放时段内")
        nums = [s.strip() for s in seats_input.replace("，", ",").split(",") if s.strip()]
        if not nums:
            raise ValueError("请填写座位号")
        seats_info = self._svc.rooms.get_seats(room_name, floor_name)
        seat_list: list[SeatInfo] = []
        for num in nums:
            matched = [s for s in seats_info if s["title"] == num]
            if not matched:
                raise ValueError(f"楼层中不存在座位 {num}")
            seat_list.append(SeatInfo(seat_id=str(matched[0]["id"]), seat_num=matched[0]["title"]))
        pid = plan_id.strip() or f"plan_{datetime.now().strftime('%H%M%S')}"
        return Plan(
            id=pid,
            room_name=room_name,
            floor_name=floor_name,
            begin_time=time_str.strip(),
            duration_hours=duration,
            seats=seat_list,
        )

    def _delete_plans(self) -> None:
        sel = self._plans_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中方案", parent=self._win)
            return
        if not messagebox.askyesno("确认", f"删除 {len(sel)} 个方案？", parent=self._win):
            return
        for pid in sel:
            self._svc.config.delete_plan(pid)
        self._refresh_plans()

    def _plans_for_action(self) -> list[Plan]:
        sel = self._plans_tree.selection()
        all_plans = self._svc.config.get_plans()
        if sel:
            wanted = set(sel)
            picked = [p for p in all_plans if p.id in wanted]
            return picked
        return list(all_plans)

    def _log_now(self, msg: str) -> None:
        self._now_log.configure(state="normal")
        self._now_log.insert("end", msg + "\n")
        self._now_log.see("end")
        self._now_log.configure(state="disabled")

    def _log_sched(self, msg: str) -> None:
        self._sched_log.configure(state="normal")
        self._sched_log.insert("end", msg + "\n")
        self._sched_log.see("end")
        self._sched_log.configure(state="disabled")

    def _schedule_next_text(self, schedule: Schedule) -> str:
        hit = schedule.next_trigger(datetime.now())
        if not hit:
            return "—"
        trigger, target, _ = hit
        return f"{trigger.strftime('%m-%d %H:%M')}→{target.strftime('%m-%d')}"

    def _refresh_schedules_tree(self) -> None:
        if not hasattr(self, "_sched_tree"):
            return
        for iid in self._sched_tree.get_children():
            self._sched_tree.delete(iid)
        for i, s in enumerate(self._svc.config.get_schedules()):
            if s.mode == "weekdays":
                mode = "每周"
                days = ",".join(WEEKDAY_NAMES[w - 1] for w in sorted(s.target_weekdays))
                target = days
                pids = ", ".join(s.plan_ids)
            else:
                mode = "指定日"
                target = ", ".join(m.target_date for m in s.mappings)
                pids = "; ".join(",".join(m.plan_ids) for m in s.mappings)
            status = "启用" if s.enabled else "停用"
            nxt = self._schedule_next_text(s) if s.enabled else "—"
            self._sched_tree.insert(
                "",
                "end",
                iid=str(i),
                values=(mode, target, pids, nxt, status),
            )

    def _parse_plan_ids(self, text: str, plans: list[Plan]) -> list[str]:
        pids = [p.strip() for p in text.replace("，", ",").split(",") if p.strip()]
        valid = {p.id for p in plans}
        for pid in pids:
            if pid not in valid:
                raise ValueError(f"未知方案「{pid}」")
        if not pids:
            raise ValueError("请填写至少一个方案名称")
        return pids

    def _start_booking(self) -> None:
        if not self._logged_in:
            messagebox.showwarning("提示", "请先登录", parent=self._win)
            return
        plans = self._plans_for_action()
        if not plans:
            messagebox.showwarning("提示", "请先添加或选中方案", parent=self._win)
            return
        try:
            target_date = datetime.strptime(self._now_date.get().strip(), "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("错误", "预约日期格式应为 YYYY-MM-DD", parent=self._win)
            return
        errs: list[str] = []
        for p in plans:
            errs.extend(p.validate())
        if errs:
            messagebox.showerror("校验失败", "\n".join(errs), parent=self._win)
            return
        now = datetime.now()
        try:
            expired = _expired_plan_lines(plans, target_date, now)
        except ValueError as e:
            messagebox.showerror("时间格式错误", str(e), parent=self.winfo_toplevel())
            return
        if expired:
            msg = (
                "以下方案的开始时刻已过（或就是现在），无法立刻抢座。\n"
                "请改「预约日期」或到「我的方案」里改开始时间。\n\n"
                + "\n".join(expired)
            )
            self._now_summary.configure(text="开始时间已过，请修改日期或方案", text_color=("#c0392b", "#e74c3c"))
            self.winfo_toplevel().lift()
            self.winfo_toplevel().focus_force()
            messagebox.showwarning("开始时间已过", msg, parent=self.winfo_toplevel())
            return
        self._booking_cancel.clear()
        self._svc.runner.cancel()
        self._book_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._now_summary.configure(text="正在抢座…", text_color=("gray20", "gray75"))
        self._now_log.configure(state="normal")
        self._now_log.delete("1.0", "end")
        self._now_log.configure(state="disabled")
        threading.Thread(
            target=self._booking_worker,
            args=(plans, target_date),
            daemon=True,
        ).start()

    def _stop_booking(self) -> None:
        self._booking_cancel.set()
        self._svc.runner.cancel()

    def _booking_worker(self, plans: list[Plan], target_date: datetime) -> None:
        settings = self._svc.config.get_settings()
        date_s = target_date.strftime("%Y-%m-%d")
        self._ui.call(
            self._log_now,
            f"目标日期 {date_s}，方案：{', '.join(p.id for p in plans)}",
        )

        def on_result(result: BookingResult) -> None:
            def handle() -> None:
                self._svc.history.log(result)
                if result.success:
                    msg = (
                        f"预约成功：{result.room_name or ''} "
                        f"座位 {result.seat_num or ''} ({date_s})"
                    )
                    self._log_now(msg)
                    self._finish_booking(True, msg)
                else:
                    self._log_now(f"失败 {result.plan_id}：{result.message}")

            self._ui.call(handle)

        for retry in range(settings["max_try_times"]):
            if self._booking_cancel.is_set():
                break
            self._ui.call(self._log_now, f"第 {retry + 1} 轮尝试…")
            results = self._svc.runner.run_booking(
                plans,
                target_date,
                on_result=on_result,
            )
            if any(r.success for r in results):
                return
            if self._booking_cancel.is_set():
                break
            if retry < settings["max_try_times"] - 1:
                self._booking_cancel.wait(timeout=settings["interval"])
        if self._booking_cancel.is_set():
            self._ui.call(self._finish_booking, False, "已取消")
        else:
            self._ui.call(self._finish_booking, False, "预约未成功，详见运行日志")

    def _finish_booking(self, ok: bool, summary: str = "") -> None:
        self._book_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        if summary:
            color = ("green", "#6fbf73") if ok else ("#c0392b", "#e74c3c")
            self._now_summary.configure(text=summary, text_color=color)
        self._refresh_history()

    def _add_schedule_dates_dialog(self) -> None:
        plans = self._svc.config.get_plans()
        if not plans:
            messagebox.showwarning("提示", "请先添加方案", parent=self._win)
            return
        dlg = ctk.CTkToplevel(self._win)
        dlg.title("按日期定时")
        dlg.geometry("440x280")
        dlg.transient(self._win)
        dlg.grab_set()
        dates_var = ctk.StringVar()
        pids_var = ctk.StringVar(value=", ".join(p.id for p in plans))
        ctk.CTkLabel(
            dlg,
            text="坐馆日期 (YYYY-MM-DD，多个用逗号)",
            font=self._font,
        ).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkEntry(dlg, textvariable=dates_var, width=360).pack(padx=16)
        ctk.CTkLabel(dlg, text="使用的方案名称（逗号分隔）", font=self._font).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        ctk.CTkEntry(dlg, textvariable=pids_var, width=360).pack(padx=16)

        def ok() -> None:
            dates = [d.strip() for d in dates_var.get().replace("，", ",").split(",") if d.strip()]
            pids = self._parse_plan_ids(pids_var.get(), plans)
            for d in dates:
                datetime.strptime(d, "%Y-%m-%d")
            mappings = [DateMapping(target_date=d, plan_ids=pids) for d in dates]
            schedules = self._svc.config.get_schedules()
            schedules.append(Schedule(mode="dates", mappings=mappings))
            self._svc.config.save_schedules(schedules)
            dlg.destroy()
            self._refresh_schedules_tree()
            messagebox.showinfo("已保存", "请在本页点击「启动定时」", parent=self._win)

        def safe_ok() -> None:
            try:
                ok()
            except Exception as e:
                messagebox.showerror("错误", str(e), parent=dlg)

        ctk.CTkButton(dlg, text="保存", command=safe_ok).pack(pady=16)

    def _add_schedule_weekdays_dialog(self) -> None:
        plans = self._svc.config.get_plans()
        if not plans:
            messagebox.showwarning("提示", "请先添加方案", parent=self._win)
            return
        dlg = ctk.CTkToplevel(self._win)
        dlg.title("按每周定时")
        dlg.geometry("460x360")
        dlg.transient(self._win)
        dlg.grab_set()
        ctk.CTkLabel(
            dlg,
            text="在下列星期几去坐馆（到点自动抢该日座位；时段见方案里的开始时间）",
            wraplength=400,
            font=self._font,
        ).pack(anchor="w", padx=16, pady=(12, 8))
        box = ctk.CTkFrame(dlg, fg_color="transparent")
        box.pack(fill="x", padx=16)
        weekday_vars: list[tk.BooleanVar] = []
        for i, name in enumerate(WEEKDAY_NAMES):
            v = tk.BooleanVar(value=False)
            weekday_vars.append(v)
            ctk.CTkCheckBox(box, text=name, variable=v, font=self._font).grid(
                row=i // 4, column=i % 4, padx=6, pady=4, sticky="w"
            )
        pids_var = ctk.StringVar(value=", ".join(p.id for p in plans))
        ctk.CTkLabel(dlg, text="方案名称（逗号分隔）", font=self._font).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        ctk.CTkEntry(dlg, textvariable=pids_var, width=360).pack(padx=16)

        def ok() -> None:
            weekdays = [i + 1 for i, v in enumerate(weekday_vars) if v.get()]
            if not weekdays:
                raise ValueError("请至少选择一个星期")
            pids = self._parse_plan_ids(pids_var.get(), plans)
            schedules = self._svc.config.get_schedules()
            schedules.append(
                Schedule(
                    mode="weekdays",
                    target_weekdays=sorted(set(weekdays)),
                    plan_ids=pids,
                )
            )
            self._svc.config.save_schedules(schedules)
            dlg.destroy()
            self._refresh_schedules_tree()
            messagebox.showinfo("已保存", "请在本页点击「启动定时」", parent=self._win)

        def safe_ok() -> None:
            try:
                ok()
            except Exception as e:
                messagebox.showerror("错误", str(e), parent=dlg)

        ctk.CTkButton(dlg, text="保存", command=safe_ok).pack(pady=16)

    def _delete_schedules(self) -> None:
        sel = self._sched_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中定时任务", parent=self._win)
            return
        if not messagebox.askyesno("确认", f"删除 {len(sel)} 条定时？", parent=self._win):
            return
        schedules = self._svc.config.get_schedules()
        for iid in sorted((int(x) for x in sel), reverse=True):
            if 0 <= iid < len(schedules):
                schedules.pop(iid)
        self._svc.config.save_schedules(schedules)
        self._refresh_schedules_tree()

    def _toggle_schedules(self) -> None:
        sel = self._sched_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中定时任务", parent=self._win)
            return
        schedules = self._svc.config.get_schedules()
        for iid in sel:
            idx = int(iid)
            if 0 <= idx < len(schedules):
                schedules[idx].enabled = not schedules[idx].enabled
        self._svc.config.save_schedules(schedules)
        self._refresh_schedules_tree()

    def _start_scheduler(self) -> None:
        active = [s for s in self._svc.config.get_schedules() if s.enabled]
        if not active:
            messagebox.showwarning("提示", "请先添加定时任务", parent=self._win)
            return
        if not self._logged_in:
            messagebox.showwarning("提示", "请先登录", parent=self._win)
            return
        self._svc.engine.start()
        self._sched_status.configure(text="定时运行中")
        if self._compact_status is not None:
            self._compact_status.set("定时运行中")
        self._on_status("定时抢座已启动")

    def _stop_scheduler(self) -> None:
        self._svc.engine.stop()
        self._sched_status.configure(text="定时未运行")
        if self._compact_status is not None:
            self._compact_status.set("定时已停止")

    def _on_countdown(self, remaining, trigger_time, plan_desc) -> None:
        txt = format_countdown(remaining) if remaining is not None else ""
        line = f"倒计时 {txt} | {plan_desc}"
        short = f"剩余 {txt}" if txt else "即将开抢"

        def apply() -> None:
            self._sched_status.configure(text=line)
            if self._compact_status is not None:
                self._compact_status.set(short)

        self._ui.call(apply)

    def _on_engine_result(self, result: BookingResult) -> None:
        def show() -> None:
            line = f"{result.plan_id}: {result.message}"
            self._log_sched(line)
            if result.success:
                self._sched_summary.configure(text=line, text_color=("green", "#6fbf73"))
            else:
                self._sched_summary.configure(text=line, text_color=("#c0392b", "#e74c3c"))
            self._refresh_history()
            self._refresh_schedules_tree()

        self._ui.call(show)

    def _on_engine_error(self, error: Exception) -> None:
        self._ui.call(
            lambda: messagebox.showerror("调度错误", str(error), parent=self._win),
        )
