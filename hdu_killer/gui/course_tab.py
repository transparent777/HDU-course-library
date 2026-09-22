"""In-process course selection tab."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from hdu_killer.course.config import (
    course_items,
    load_config,
    save_config,
    set_course_items,
)
from hdu_killer.course.runner import CourseRunner
from hdu_killer.paths import get_course_data_dir


class CourseTab(ttk.Frame):
    def __init__(self, master: tk.Misc, root: tk.Tk, on_status) -> None:
        super().__init__(master)
        self._win = root
        self._scale = float(getattr(root, "_hdu_ui_scale", 1.0))
        self._text_size = max(12, int(13 * self._scale))
        self._on_status = on_status
        self._runner = CourseRunner()
        self._data = load_config()
        self._vars: dict[str, tk.Variable] = {}
        self._build_ui()
        self._load_form()

    def _build_ui(self) -> None:
        paned = ttk.Panedwindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        form = ttk.Frame(paned)
        log_frame = ttk.LabelFrame(paned, text="运行日志")
        paned.add(form, weight=3)
        paned.add(log_frame, weight=2)

        bar = ttk.LabelFrame(form, text="抢课操作", padding=8)
        bar.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(bar, text="开始抢课", command=self._start).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bar, text="停止", command=self._stop).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="保存配置", command=self._save).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="打开数据目录", command=self._open_dir).pack(side=tk.RIGHT, padx=4)

        nb = ttk.Notebook(form)
        nb.pack(fill=tk.BOTH, expand=True)
        t_course, t_adv = ttk.Frame(nb, padding=8), ttk.Frame(nb, padding=8)
        nb.add(t_course, text="课程")
        nb.add(t_adv, text="定时 / 蹲课")
        self._build_courses(t_course)
        self._build_advanced(t_adv)

        self._log = tk.Text(
            log_frame,
            height=12,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Microsoft YaHei UI", self._text_size),
        )
        sb = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    def _row(self, parent: ttk.Frame, label: str, key: str, show: str | None = None) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=label, width=16).pack(side=tk.LEFT, padx=(0, 8))
        var = tk.StringVar()
        self._vars[key] = var
        ttk.Entry(row, textvariable=var, show=show).pack(side=tk.LEFT, fill=tk.X, expand=True)

    @staticmethod
    def _action_label(flag: str) -> str:
        return "选课" if str(flag).strip() in ("1", "选课") else "退课"

    @staticmethod
    def _action_code(label: str) -> str:
        s = str(label).strip()
        if s in ("1", "选课"):
            return "1"
        if s in ("0", "退课"):
            return "0"
        return "1"

    def _sync_run_mode_fields(self) -> None:
        lurk = self._vars["run_mode"].get() == "wait"
        if lurk:
            self._start_row.pack_forget()
            self._interval_row.pack(fill=tk.X, pady=2)
        else:
            self._interval_row.pack_forget()
            self._start_row.pack(fill=tk.X, pady=2)

    def _build_advanced(self, p: ttk.Frame) -> None:
        ttk.Label(
            p,
            text="学年学期须与教学班括号内一致，详见右上角「使用手册」。",
            style="TMuted.TLabel",
            font=("Microsoft YaHei UI", self._text_size),
        ).pack(anchor=tk.W, pady=(0, 10))
        self._row(p, "学年", "xuenian")
        self._row(p, "学期", "xueqi")

        mode_box = ttk.LabelFrame(p, text="抢课方式", padding=8)
        mode_box.pack(fill=tk.X, pady=(4, 10))
        self._vars["run_mode"] = tk.StringVar(value="schedule")
        ttk.Radiobutton(
            mode_box,
            text="定时到点 — 等到「开始时间」，按课程列表选/退一轮",
            variable=self._vars["run_mode"],
            value="schedule",
            command=self._sync_run_mode_fields,
        ).pack(anchor=tk.W)
        ttk.Radiobutton(
            mode_box,
            text="蹲课 — 循环查余量，有名额再选（只处理列表里标记「选课」的班）",
            variable=self._vars["run_mode"],
            value="wait",
            command=self._sync_run_mode_fields,
        ).pack(anchor=tk.W, pady=(6, 0))

        self._start_row = ttk.Frame(p)
        self._vars["start_time"] = tk.StringVar()
        ttk.Label(self._start_row, text="开始时间", width=16).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Entry(self._start_row, textvariable=self._vars["start_time"]).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Label(
            self._start_row,
            text="格式 YYYY-MM-DD HH:MM:SS",
            style="TMuted.TLabel",
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._interval_row = ttk.Frame(p)
        self._vars["wait_interval"] = tk.StringVar(value="60")
        ttk.Label(self._interval_row, text="查询间隔(秒)", width=16).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Entry(self._interval_row, textvariable=self._vars["wait_interval"], width=12).pack(side=tk.LEFT)

    def _build_courses(self, p: ttk.Frame) -> None:
        btns = ttk.Frame(p)
        btns.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(btns, text="添加", command=self._add_course).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="编辑选中", command=self._edit_course).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="删除选中", command=self._del_course).pack(side=tk.LEFT)

        cols = ("name", "action")
        self._tree = ttk.Treeview(p, columns=cols, show="headings", height=8)
        self._tree.heading("name", text="教学班")
        self._tree.heading("action", text="操作")
        self._tree.column("name", width=520, minwidth=240, stretch=True)
        self._tree.column("action", width=72, minwidth=72, stretch=False, anchor=tk.CENTER)
        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>", lambda _e: self._edit_course())

    def _load_form(self) -> None:
        d = self._data
        self._vars["xuenian"].set(d["time"].get("XueNian", ""))
        self._vars["xueqi"].set(d["time"].get("XueQi", ""))
        self._vars["start_time"].set(d.get("start_time", ""))
        enabled = str(d.get("wait_course", {}).get("enabled", "0"))
        self._vars["run_mode"].set("wait" if enabled == "1" else "schedule")
        self._vars["wait_interval"].set(str(d.get("wait_course", {}).get("interval", 60)))
        self._sync_run_mode_fields()
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for n, a in course_items(d):
            self._tree.insert("", tk.END, values=(n, self._action_label(a)))

    def _collect(self) -> dict:
        d = load_config()
        d["time"]["XueNian"] = self._vars["xuenian"].get().strip()
        d["time"]["XueQi"] = self._vars["xueqi"].get().strip()
        d["start_time"] = self._vars["start_time"].get().strip()
        d["wait_course"]["enabled"] = "1" if self._vars["run_mode"].get() == "wait" else "0"
        try:
            d["wait_course"]["interval"] = int(self._vars["wait_interval"].get())
        except ValueError:
            d["wait_course"]["interval"] = 60
        items = []
        for iid in self._tree.get_children():
            v = self._tree.item(iid, "values")
            if len(v) >= 2:
                items.append((str(v[0]).strip(), self._action_code(str(v[1]))))
        return set_course_items(d, items)

    def _save(self) -> None:
        data = self._collect()
        save_config(data)
        self._data = data
        self._log_line("已保存 data/course/config.json")
        self._on_status("配置已保存")

    def _add_course(self) -> None:
        self._course_dialog(None)

    def _edit_course(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选中要编辑的课程", parent=self._win)
            return
        iid = sel[0]
        v = self._tree.item(iid, "values")
        name = str(v[0]) if v else ""
        act = self._action_label(str(v[1])) if len(v) > 1 else "选课"
        self._course_dialog(iid, name, act)

    def _course_dialog(
        self,
        iid: str | None,
        initial_name: str = "",
        initial_act: str = "选课",
    ) -> None:
        dlg = tk.Toplevel(self._win)
        dlg.title("编辑课程" if iid else "添加课程")
        dlg.transient(self._win)
        dlg.grab_set()
        name, act = tk.StringVar(value=initial_name), tk.StringVar(value=self._action_label(initial_act))
        pad = {"padx": 8, "pady": 4}
        ttk.Label(dlg, text="教学班").grid(row=0, column=0, sticky=tk.W, **pad)
        ttk.Entry(dlg, textvariable=name, width=56).grid(row=0, column=1, **pad)
        ttk.Label(dlg, text="操作").grid(row=1, column=0, sticky=tk.W, **pad)
        ttk.Combobox(dlg, textvariable=act, values=("选课", "退课"), width=8, state="readonly").grid(
            row=1, column=1, sticky=tk.W, **pad
        )

        def ok() -> None:
            n = name.get().strip()
            if not n:
                messagebox.showwarning("提示", "教学班名称不能为空", parent=dlg)
                return
            a = self._action_label(act.get().strip() or "选课")
            if iid:
                self._tree.item(iid, values=(n, a))
            else:
                self._tree.insert("", tk.END, values=(n, a))
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.grid(row=2, column=1, sticky=tk.E, pady=8)
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="确定", command=ok).pack(side=tk.LEFT)

    def _del_course(self) -> None:
        for iid in self._tree.selection():
            self._tree.delete(iid)

    def apply_text_theme(self, colors: dict[str, str]) -> None:
        self._log.configure(
            bg=colors["field"],
            fg=colors["fg"],
            insertbackground=colors["fg"],
        )

    def _log_line(self, line: str) -> None:
        self._log.configure(state=tk.NORMAL)
        self._log.insert(tk.END, line + "\n")
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def _start(self) -> None:
        if self._runner.is_running:
            messagebox.showinfo("提示", "任务已在运行")
            return
        cfg = load_config()
        sid = (cfg.get("newjw_login") or {}).get("username", "").strip()
        pwd = (cfg.get("newjw_login") or {}).get("password", "")
        if not sid or not pwd:
            messagebox.showwarning(
                "未设置抢课账号",
                "请先点右上角「登录 / 切换」填写教务学号与密码。",
                parent=self._win,
            )
            return
        self._save()
        try:
            ui = getattr(self._win, "_hdu_ui", None)

            def on_log(m: str) -> None:
                if ui is not None:
                    ui.call(self._log_line, m)
                else:
                    self._win.after(0, lambda: self._log_line(m))

            self._runner.start(on_log=on_log)
        except RuntimeError as e:
            messagebox.showerror("无法启动", str(e))
            return
        self._log_line("--- 开始执行抢课任务 ---")
        self._on_status("抢课运行中")

    def _stop(self) -> None:
        self._runner.stop()
        self._log_line("--- 已请求停止 ---")

    def _open_dir(self) -> None:
        path = str(get_course_data_dir())
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)

    def shutdown(self) -> None:
        self._stop()
