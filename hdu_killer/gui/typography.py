"""界面字号（gui_prefs.ui_scale）；与 CTk 全局 scaling 分开，避免「调了没感觉」."""

from __future__ import annotations

import customtkinter as ctk

DEFAULT_UI_SCALE = 1.0
BASE_BODY = 15
BASE_TITLE = 18


def apply_ctk_scale(scale: float) -> None:
    """字号由 CTkFont 控制；勿改 window_scaling，否则窗口会突然变大。"""
    ctk.set_widget_scaling(1.0)
    ctk.set_window_scaling(1.0)


def body_font(scale: float = DEFAULT_UI_SCALE) -> ctk.CTkFont:
    s = max(0.85, min(1.75, float(scale)))
    return ctk.CTkFont(family="Microsoft YaHei UI", size=max(12, int(round(BASE_BODY * s))))


def title_font(scale: float = DEFAULT_UI_SCALE) -> ctk.CTkFont:
    s = max(0.85, min(1.75, float(scale)))
    return ctk.CTkFont(
        family="Microsoft YaHei UI",
        size=max(14, int(round(BASE_TITLE * s))),
        weight="bold",
    )


def appearance_is_dark(root=None) -> bool:
    m = ctk.get_appearance_mode().lower()
    if m == "dark":
        return True
    if m == "light":
        return False
    if root is not None:
        try:
            fg = root.cget("fg_color")
            if isinstance(fg, (tuple, list)):
                fg = fg[1] if ctk.get_appearance_mode().lower() == "dark" else fg[0]
            if isinstance(fg, str) and fg.startswith("#") and len(fg) >= 7:
                r, g, b = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
                return (r + g + b) < 420
        except Exception:
            pass
    return False


def ttk_theme_colors(dark: bool) -> dict[str, str]:
    if dark:
        return {
            "bg": "#2b2b2b",
            "fg": "#e8e8e8",
            "field": "#343434",
            "heading": "#3d3d3d",
            "tab": "#3a3a3a",
            "tab_sel": "#1f538d",
            "muted": "#a0a0a0",
        }
    return {
        "bg": "#f2f2f2",
        "fg": "#1a1a1a",
        "field": "#ffffff",
        "heading": "#e4e4e4",
        "tab": "#e0e0e0",
        "tab_sel": "#ffffff",
        "muted": "#555555",
    }


def apply_ttk_theme(root, dark: bool | None = None) -> dict[str, str]:
    from tkinter import ttk

    if dark is None:
        dark = appearance_is_dark(root)
    c = ttk_theme_colors(dark)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    font_cfg = style.configure(".") or {}
    family = font_cfg.get("font", ("Microsoft YaHei UI", 12))[0] if font_cfg.get("font") else "Microsoft YaHei UI"
    style.configure(
        ".",
        background=c["bg"],
        foreground=c["fg"],
        fieldbackground=c["field"],
    )
    style.configure("TFrame", background=c["bg"])
    style.configure("TLabel", background=c["bg"], foreground=c["fg"])
    style.configure("TMuted.TLabel", background=c["bg"], foreground=c["muted"])
    style.configure("TLabelframe", background=c["bg"], foreground=c["fg"])
    style.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"])
    style.configure("TNotebook", background=c["bg"], borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=c["tab"],
        foreground=c["fg"],
        padding=(12, 6),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", c["tab_sel"])],
        foreground=[("selected", c["fg"])],
    )
    # 行高由 apply_ttk_scale 按字号设置；此处勿写死 28，否则中文会被裁切
    style.configure(
        "Treeview",
        background=c["field"],
        foreground=c["fg"],
        fieldbackground=c["field"],
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background=c["heading"],
        foreground=c["fg"],
        relief="flat",
    )
    style.map("Treeview", background=[("selected", "#1f538d")], foreground=[("selected", "#ffffff")])
    style.configure("TButton", background=c["heading"], foreground=c["fg"])
    style.map("TButton", background=[("active", c["tab"])])
    style.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"], insertcolor=c["fg"])
    style.configure(
        "TCombobox",
        fieldbackground=c["field"],
        background=c["field"],
        foreground=c["fg"],
        arrowcolor=c["fg"],
    )
    style.configure("TPanedwindow", background=c["bg"])
    style.configure("Vertical.TScrollbar", background=c["heading"], troughcolor=c["bg"])
    return c


def apply_ttk_scale(root, scale: float = DEFAULT_UI_SCALE) -> tuple[str, int]:
    from tkinter import ttk

    s = max(0.85, min(1.75, float(scale)))
    size = max(12, int(round(BASE_BODY * s)))
    row_h = max(34, int(round(size * 2.25)))
    family = "Microsoft YaHei UI"
    font = (family, size)
    style = ttk.Style(root)
    style.configure(".", font=font)
    style.configure("TNotebook.Tab", font=font, padding=(14, 8))
    style.configure("TButton", font=font, padding=(8, 5))
    style.configure("Treeview", font=font, rowheight=row_h)
    style.configure("Treeview.Heading", font=(family, size, "bold"))
    style.configure("TLabelframe.Label", font=(family, size, "bold"))
    return family, size


_CTK_FONT_WIDGETS = (
    ctk.CTkLabel,
    ctk.CTkButton,
    ctk.CTkEntry,
    ctk.CTkTextbox,
    ctk.CTkSegmentedButton,
    ctk.CTkCheckBox,
    ctk.CTkRadioButton,
    ctk.CTkOptionMenu,
    ctk.CTkComboBox,
)


def apply_fonts_to_ctk_tree(widget, scale: float, title_widgets: set | None = None) -> None:
    """已创建的 CTk 控件刷新 font（标题控件可放进 title_widgets 用 title_font）。"""
    title_widgets = title_widgets or set()
    bf = body_font(scale)
    tf = title_font(scale)
    try:
        children = widget.winfo_children()
    except Exception:
        return
    for child in children:
        if isinstance(child, _CTK_FONT_WIDGETS):
            try:
                child.configure(font=tf if child in title_widgets else bf)
            except Exception:
                pass
        apply_fonts_to_ctk_tree(child, scale, title_widgets)


def reapply_all(root, scale: float) -> None:
    """滑块调整后立即生效。"""
    apply_ctk_scale(scale)
    apply_ttk_theme(root)
    apply_ttk_scale(root, scale)
    root._hdu_ui_scale = scale  # noqa: SLF001
