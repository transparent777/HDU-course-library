"""Display utilities: countdown, tables, colored output."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import List


# ANSI color codes
class Color:
    RESET = "\033[0m"
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


def supports_color() -> bool:
    """Check if terminal supports ANSI colors."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def colorize(text: str, color: str) -> str:
    """Apply ANSI color to text."""
    if not supports_color():
        return text
    return f"{color}{text}{Color.RESET}"


def format_countdown(remaining_seconds: int) -> str:
    """Format remaining seconds into human-readable string."""
    if remaining_seconds < 0:
        return "已到达"
    hours = remaining_seconds // 3600
    minutes = (remaining_seconds % 3600) // 60
    seconds = remaining_seconds % 60
    if hours > 0:
        return f"{hours}时{minutes:02d}分{seconds:02d}秒"
    elif minutes > 0:
        return f"{minutes}分{seconds:02d}秒"
    else:
        return f"{seconds}秒"


def format_status_line(trigger_time: datetime, remaining_seconds: int,
                       plan_desc: str) -> str:
    """Format the status bar line shown at terminal bottom."""
    remaining_str = format_countdown(remaining_seconds)
    trigger_str = trigger_time.strftime("%m-%d %H:%M")
    return (
        f"[抢座] 下次预约触发: {trigger_str} | "
        f"剩余: {remaining_str} | 方案: {plan_desc}"
    )


def print_countdown(remaining_seconds: int, trigger_time: datetime,
                    plan_desc: str):
    """Print an in-place countdown line (carriage return)."""
    now = datetime.now().replace(microsecond=0)
    remaining_str = format_countdown(remaining_seconds)
    trigger_str = trigger_time.strftime("%m-%d %H:%M")
    print(
        f"\r[{now.strftime('%H:%M:%S')}] 触发: {trigger_str} | "
        f"剩余: {remaining_str} | {plan_desc}",
        end="", flush=True,
    )


def print_table(headers: List[str], rows: List[List[str]], title: str = None):
    """Print a formatted table using prettytable."""
    from prettytable import PrettyTable
    table = PrettyTable(headers)
    for row in rows:
        table.add_row(row)
    if title:
        print(f"\n{colorize(title, Color.BOLD)}")
    print(table)


def print_success(message: str):
    print(colorize(f"[成功] {message}", Color.GREEN))


def print_error(message: str):
    print(colorize(f"[错误] {message}", Color.RED))


def print_warning(message: str):
    print(colorize(f"[警告] {message}", Color.YELLOW))


def print_info(message: str):
    print(colorize(f"[信息] {message}", Color.CYAN))


WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
