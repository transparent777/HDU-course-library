"""Logging configuration: file + console, rotating logs."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(log_dir: str = None, level: int = logging.INFO) -> logging.Logger:
    """Configure the hdu_killer.seat logger with console and file output.

    Args:
        log_dir: Directory for log files. If None, uses default.
        level: Logging level.

    Returns:
        The configured root hdu_killer.seat logger.
    """
    if log_dir is None:
        from hdu_killer.seat.platform_.paths import get_log_dir
        log_dir = get_log_dir()

    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("hdu_killer.seat")
    logger.setLevel(level)

    # Avoid adding duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # File handler with rotation (5MB x 3 files)
    log_file = os.path.join(log_dir, "hdu_killer.seat.log")
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    return logger
