"""教学班名称解析与学年学期校验。"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

# 例: (2026-2027-1)-C2301270-14 → 学年 2026，学期 1
JXBMC_TIME = re.compile(r"^\((\d{4})-\d{4}-(\d)\)-")


def parse_jxbmc_time(jxbmc: str) -> tuple[str, str] | None:
    m = JXBMC_TIME.match((jxbmc or "").strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def cfg_for_jxbmc_query(cfg: dict[str, Any], jxbmc: str) -> dict[str, Any]:
    """查询某教学班时，学年学期以教学班名中的为准。"""
    parsed = parse_jxbmc_time(jxbmc)
    if not parsed:
        return cfg
    xn, xq = parsed
    out = deepcopy(cfg)
    out["time"] = {"XueNian": xn, "XueQi": xq}
    return out


def time_mismatch_hint(cfg: dict[str, Any]) -> str | None:
    tm = cfg.get("time", {})
    for jxbmc in cfg.get("course", {}):
        parsed = parse_jxbmc_time(jxbmc)
        if not parsed:
            continue
        xn, xq = parsed
        if tm.get("XueNian") != xn or tm.get("XueQi") != xq:
            return (
                f"教学班「{jxbmc}」表示 {xn} 学年第 {xq} 学期，"
                f"但配置里学年为 {tm.get('XueNian')}、学期为 {tm.get('XueQi')}。"
                f"请在「定时/蹲课」页改为 {xn} / {xq}，或保持教学班名与学年一致。"
            )
    return None
