"""首次 / 重新登录向导."""

from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk
from tkinter import messagebox

from hdu_killer.course.config import load_config, save_config
from hdu_killer.gui.seat_service import SeatServices
from hdu_killer.gui.ui_prefs import load_ui_prefs, save_ui_prefs
from hdu_killer.gui.typography import body_font, title_font
from hdu_killer.gui.ui_scheduler import MainThreadUi


def _course_enabled_in_config() -> bool:
    try:
        cfg = load_config()
        user = (cfg.get("newjw_login") or {}).get("username", "").strip()
        pwd = (cfg.get("newjw_login") or {}).get("password", "") or (
            cfg.get("cas_login") or {}
        ).get("password", "")
        return bool(user and pwd)
    except Exception:
        return False


class LoginWizard(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        services: SeatServices,
        on_complete: Callable[[], None],
        ui: MainThreadUi,
    ) -> None:
        super().__init__(master)
        self._services = services
        self._on_complete = on_complete
        self._ui = ui
        self._scale = float(getattr(master, "_hdu_ui_scale", 1.0))
        self._font = body_font(self._scale)
        self._font_title = title_font(self._scale)
        self.title("登录设置")
        self.geometry("560x520")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self._step = 0
        self._body = ctk.CTkFrame(self)
        self._body.pack(fill="both", expand=True, padx=24, pady=24)

        self._student_id = ctk.StringVar(
            value=services.config.get_user_info().get("login_name", "")
        )
        self._lib_pwd = ctk.StringVar()
        self._also_course = ctk.BooleanVar(value=_course_enabled_in_config())
        self._jw_pwd = ctk.StringVar()
        self._jw_row: ctk.CTkFrame | None = None
        self._nav: ctk.CTkFrame | None = None
        self._status: ctk.CTkLabel | None = None

        self._show_step_welcome()

    def _clear_body(self) -> None:
        for w in self._body.winfo_children():
            w.destroy()
        self._jw_row = None
        self._nav = None
        self._status = None

    def _show_step_welcome(self) -> None:
        self._step = 0
        self._clear_body()
        ctk.CTkLabel(self._body, text="杭电图书馆抢座 · 教务抢课", font=self._font_title).pack(
            anchor="w", pady=(0, 12)
        )
        ctk.CTkLabel(
            self._body,
            text="登录信息仅保存在本机 data/ 目录，不会上传。\n"
            "图书馆密码与教务密码分开保存；抢课使用同一学号。",
            justify="left",
            wraplength=480,
            font=self._font,
        ).pack(anchor="w", pady=(0, 24))
        ctk.CTkButton(
            self._body,
            text="开始设置",
            command=self._show_step_account,
            width=160,
            height=38,
            font=self._font,
        ).pack(anchor="e")

    def _show_step_account(self) -> None:
        self._step = 1
        self._clear_body()

        self._nav = ctk.CTkFrame(self._body, fg_color="transparent")
        self._nav.pack(side="bottom", fill="x", pady=(16, 0))
        ctk.CTkButton(
            self._nav,
            text="上一步",
            command=self._show_step_welcome,
            width=100,
            height=38,
            font=self._font,
        ).pack(side="left")
        ctk.CTkButton(
            self._nav,
            text="登录并进入",
            command=self._start_login,
            width=140,
            height=38,
            font=self._font,
        ).pack(side="right")

        form = ctk.CTkFrame(self._body, fg_color="transparent")
        form.pack(fill="both", expand=True)

        ctk.CTkLabel(form, text="账号", font=self._font_title).pack(anchor="w", pady=(0, 8))
        ctk.CTkLabel(
            form,
            text="密码框留空表示沿用已保存的密码（首次使用须填写）。",
            font=self._font,
            text_color=("gray40", "gray65"),
            wraplength=480,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        def row(label: str, var, secret: bool = False, placeholder: str = "") -> None:
            fr = ctk.CTkFrame(form, fg_color="transparent")
            fr.pack(fill="x", pady=8)
            ctk.CTkLabel(fr, text=label, width=110, anchor="w", font=self._font).pack(side="left")
            kw = {"show": "*"} if secret else {}
            ent = ctk.CTkEntry(
                fr,
                textvariable=var,
                height=38,
                font=self._font,
                placeholder_text=placeholder,
                **kw,
            )
            ent.pack(side="left", fill="x", expand=True, padx=(8, 0))

        row("学号", self._student_id)
        row("图书馆密码", self._lib_pwd, secret=True, placeholder="不填则保持已保存")

        ctk.CTkCheckBox(
            form,
            text="我要抢课（学号同上，单独填教务密码）",
            variable=self._also_course,
            command=self._sync_jw_row,
            font=self._font,
        ).pack(anchor="w", pady=(16, 4))

        self._jw_row = ctk.CTkFrame(form, fg_color="transparent")
        fr = ctk.CTkFrame(self._jw_row, fg_color="transparent")
        fr.pack(fill="x", pady=4)
        ctk.CTkLabel(fr, text="教务密码", width=110, anchor="w", font=self._font).pack(side="left")
        ctk.CTkEntry(
            fr,
            textvariable=self._jw_pwd,
            show="*",
            height=38,
            font=self._font,
            placeholder_text="不填则保持已保存",
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        self._status = ctk.CTkLabel(
            form,
            text="",
            text_color=("gray40", "gray70"),
            font=self._font,
            wraplength=480,
        )
        self._status.pack(anchor="w", pady=(12, 0))
        self._sync_jw_row()

    def _sync_jw_row(self) -> None:
        if self._jw_row is None or self._status is None:
            return
        if self._also_course.get():
            self._jw_row.pack(fill="x", pady=6, before=self._status)
        else:
            self._jw_row.pack_forget()

    def _resolve_lib_password(self) -> str:
        typed = self._lib_pwd.get()
        if typed.strip():
            return typed
        return self._services.config.get_user_info().get("password", "") or ""

    def _resolve_jw_password(self, lib_effective: str) -> str:
        typed = self._jw_pwd.get().strip()
        if typed:
            return typed
        try:
            cfg = load_config()
            stored = (cfg.get("newjw_login") or {}).get("password", "") or (
                cfg.get("cas_login") or {}
            ).get("password", "")
            return stored or ""
        except Exception:
            return ""

    def _start_login(self) -> None:
        sid = self._student_id.get().strip()
        if not sid:
            if self._status:
                self._status.configure(text="请填写学号")
            return
        lib_effective = self._resolve_lib_password()
        if not lib_effective:
            if self._status:
                self._status.configure(text="请填写图书馆密码（首次必填）")
            return
        if self._also_course.get():
            jw_effective = self._resolve_jw_password(lib_effective)
            if not jw_effective:
                if self._status:
                    self._status.configure(text="请填写教务密码（首次开启抢课必填）")
                return
        else:
            jw_effective = ""

        if self._status:
            self._status.configure(text="正在登录图书馆…")
        self.update_idletasks()
        lib_typed = self._lib_pwd.get().strip()

        def work() -> None:
            self._services.config.update_user_info(login_name=sid)
            if lib_typed:
                self._services.config.update_user_info(password=lib_typed)
            ok, err = self._services.session.relogin()
            if not ok:
                self._ui.call(
                    self._status.configure,
                    text=f"图书馆登录失败：{err or '请检查密码与网络'}",
                )
                return
            if self._also_course.get():
                self._save_course_credentials(sid, jw_effective)
            self._services.rooms.start_background_refresh()
            self._services.rooms.wait_until_ready(timeout=120)

            def done() -> None:
                prefs = load_ui_prefs()
                prefs["wizard_completed"] = True
                save_ui_prefs(prefs)
                self.grab_release()
                self.destroy()
                self._on_complete()

            self._ui.call(done)

        threading.Thread(target=work, daemon=True).start()

    def _save_course_credentials(self, sid: str, jw_effective: str) -> None:
        try:
            cfg = load_config()
            cfg["cas_login"]["username"] = sid
            cfg["cas_login"]["password"] = jw_effective
            cfg["newjw_login"]["username"] = sid
            cfg["newjw_login"]["password"] = jw_effective
            save_config(cfg)
        except Exception as e:
            self._ui.call(
                lambda: messagebox.showwarning("抢课账号", f"教务配置未写入：{e}", parent=self),
            )
