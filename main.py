"""
HDU 抢课 + 抢座 — 程序入口
"""

from __future__ import annotations

import sys
import traceback

_MIN = (3, 8)


def main() -> None:
    from hdu_killer.bootstrap import format_missing_message, missing_dependencies, prepare
    from hdu_killer.deps_dialog import show_fatal

    prepare()
    if sys.version_info < _MIN:
        sys.exit(f"需要 Python >= {_MIN[0]}.{_MIN[1]}")

    missing = missing_dependencies()
    if missing:
        show_fatal("无法启动", format_missing_message(missing))
        sys.exit(1)

    try:
        if "--classic" in sys.argv:
            from hdu_killer.gui.shell import run
        else:
            from hdu_killer.gui.app_ctk import run

        run()
    except Exception:
        show_fatal("程序异常", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
