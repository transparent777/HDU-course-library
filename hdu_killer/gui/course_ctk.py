"""教务抢课 CTk 外壳（与图书馆抢座页顶栏一致）."""

from __future__ import annotations

import threading
from typing import Callable, Optional

import tkinter as tk
import customtkinter as ctk

from hdu_killer.course.config import load_config, save_config
from hdu_killer.course.jw_client import JwClient
from hdu_killer.gui.course_tab import CourseTab
from hdu_killer.gui.manual_viewer import COURSE_MANUAL, ManualViewer
from hdu_killer.gui.typography import (
    apply_fonts_to_ctk_tree,
    apply_ttk_scale,
    apply_ttk_theme,
    body_font,
    title_font,
)


class CourseWorkspace(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkFrame,
        tk_root: ctk.CTk,
        on_status: Callable[[str], None],
        on_enter_compact: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._win = tk_root
        self._on_status = on_status
        self._on_enter_compact = on_enter_compact
        self._scale = float(getattr(tk_root, "_hdu_ui_scale", 1.0))
        self._font = body_font(self._scale)
        self._font_title = title_font(self._scale)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        self._account_label = ctk.CTkLabel(top, text="未设置教务账号", anchor="w", font=self._font)
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

        colors = apply_ttk_theme(self._win)
        self._tk_host = tk.Frame(self, bg=colors["bg"], highlightthickness=0)
        self._tk_host.pack(fill="both", expand=True)
        apply_ttk_theme(self._win)
        apply_ttk_scale(self._win, self._scale)

        self._tab = CourseTab(self._tk_host, self._win, on_status)
        self._tab.pack(fill=tk.BOTH, expand=True)
        self._tab.apply_text_theme(colors)

        self.refresh_account()

    def refresh_account(self) -> None:
        try:
            cfg = load_config()
            sid = (cfg.get("newjw_login") or {}).get("username", "").strip()
            if sid:
                self._account_label.configure(text=f"教务学号 {sid}")
            else:
                self._account_label.configure(text="未设置教务账号（请登录 / 切换）")
        except Exception:
            self._account_label.configure(text="未设置教务账号")

    def apply_ui_scale(self, scale: float) -> None:
        self._scale = float(scale)
        self._font = body_font(self._scale)
        self._font_title = title_font(self._scale)
        apply_fonts_to_ctk_tree(self, self._scale)
        colors = apply_ttk_theme(self._win)
        apply_ttk_scale(self._win, self._scale)
        self._tk_host.configure(bg=colors["bg"])
        self._tab.apply_text_theme(colors)

    def apply_theme(self) -> None:
        colors = apply_ttk_theme(self._win)
        apply_ttk_scale(self._win, self._scale)
        self._tk_host.configure(bg=colors["bg"])
        self._tab.apply_text_theme(colors)

    def shutdown(self) -> None:
        self._tab.shutdown()

    def _open_manual(self) -> None:
        ManualViewer.open(
            self._win,
            self._scale,
            manual_rel=COURSE_MANUAL,
            title="教务抢课 · 使用说明",
        )

    def _request_compact(self) -> None:
        if self._on_enter_compact:
            self._on_enter_compact()

    def _stored_jw_password(self) -> str:
        try:
            cfg = load_config()
            return (cfg.get("newjw_login") or {}).get("password", "") or (
                cfg.get("cas_login") or {}
            ).get("password", "") or ""
        except Exception:
            return ""

    def _write_credentials(self, sid: str, password: str) -> None:
        cfg = load_config()
        cfg.setdefault("cas_login", {})["username"] = sid
        cfg.setdefault("newjw_login", {})["username"] = sid
        if password:
            cfg["cas_login"]["password"] = password
            cfg["newjw_login"]["password"] = password
        save_config(cfg)

    def _login_dialog(self) -> None:
        dlg = ctk.CTkToplevel(self._win)
        dlg.title("教务登录")
        dlg.geometry("520x300")
        dlg.minsize(520, 300)
        dlg.transient(self._win)
        dlg.grab_set()

        cfg = load_config()
        sid = ctk.StringVar(value=(cfg.get("newjw_login") or {}).get("username", "").strip())
        pwd = ctk.StringVar(value=self._stored_jw_password())
        st = ctk.StringVar()

        box = ctk.CTkFrame(dlg)
        box.pack(fill="both", expand=True, padx=28, pady=24)

        ctk.CTkLabel(box, text="教务系统账号登录", font=self._font_title).pack(anchor="w", pady=(0, 16))

        def field(label: str, var: ctk.StringVar, secret: bool = False) -> None:
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", pady=10)
            ctk.CTkLabel(row, text=label, width=110, anchor="w", font=self._font).pack(side="left")
            kw = {"show": "*"} if secret else {}
            ctk.CTkEntry(row, textvariable=var, height=38, font=self._font, **kw).pack(
                side="left", fill="x", expand=True, padx=(8, 0)
            )

        field("学号", sid)
        field("教务密码", pwd, secret=True)

        ctk.CTkLabel(box, textvariable=st, text_color="orange", font=self._font, wraplength=440).pack(
            anchor="w", pady=(8, 0)
        )

        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(fill="x", pady=(20, 0))

        ui = getattr(self._win, "_hdu_ui", None)

        def do_login() -> None:
            student = sid.get().strip()
            if not student:
                st.set("请填写学号")
                return
            typed = pwd.get()
            effective = typed if typed.strip() else self._stored_jw_password()
            if not effective:
                st.set("请填写教务密码（首次必填）")
                return
            st.set("登录中…")
            dlg.update_idletasks()
            self._write_credentials(student, typed.strip())

            def work() -> None:
                try:
                    cfg2 = load_config()
                    client = JwClient()
                    client.login_flow(cfg2)
                    save_config(cfg2)
                except Exception as e:
                    msg = f"失败：{e}"
                    if ui is not None:
                        ui.call(st.set, msg)
                    else:
                        dlg.after(0, lambda: st.set(msg))
                    return

                def done() -> None:
                    self.refresh_account()
                    self._on_status("教务已登录")
                    dlg.destroy()

                if ui is not None:
                    ui.call(done)
                else:
                    dlg.after(0, done)

            threading.Thread(target=work, daemon=True).start()

        ctk.CTkButton(btns, text="取消", width=100, height=38, font=self._font, command=dlg.destroy).pack(
            side="left"
        )
        ctk.CTkButton(btns, text="登录", width=120, height=38, font=self._font, command=do_login).pack(
            side="right"
        )
