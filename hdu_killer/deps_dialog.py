from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox


def show_fatal(title: str, message: str) -> None:
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message, parent=root)
        root.destroy()
    except tk.TclError:
        print(title, message, file=sys.stderr)
