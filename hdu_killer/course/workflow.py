"""选课 / 退课 / 蹲课流程."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from hdu_killer.course.config import save_config
from hdu_killer.course.jxbmc import cfg_for_jxbmc_query, time_mismatch_hint
from hdu_killer.course.jw_client import JwClient, KKLX_MAP
from hdu_killer.paths import get_course_data_dir

LogFn = Callable[[str], None]


def format_jw_error(exc: BaseException, *, will_retry: bool = False) -> str:
    """把 requests/教务异常转成界面日志用的中文说明。"""
    name = type(exc).__name__
    text = str(exc).lower()
    is_timeout = (
        "timed out" in text
        or "timeout" in name.lower()
        or name in ("ReadTimeout", "ConnectTimeout", "Timeout")
    )
    if is_timeout:
        if will_retry:
            return "教务响应超时，将下一轮重试（请确认校园网/VPN）"
        return "教务响应超时，请确认校园网/VPN 后重试"
    if "connection" in text or name in (
        "ConnectionError",
        "ConnectionResetError",
        "ProxyError",
    ):
        if will_retry:
            return "无法连接教务系统，将下一轮重试"
        return "无法连接教务系统，请检查网络"
    if "统一身份认证" in str(exc):
        return "登录可能已过期，请重新登录后重试"
    detail = str(exc).strip()
    if will_retry:
        if detail:
            return f"教务请求失败，将下一轮重试（{detail}）"
        return "教务请求失败，将下一轮重试"
    return detail or "教务请求失败"


def _course_json_path() -> Path:
    return get_course_data_dir() / "course.json"


def load_local_courses() -> dict[str, Any] | None:
    p = _course_json_path()
    if not p.is_file():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def save_local_courses(data: dict[str, Any]) -> None:
    with _course_json_path().open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_catalog(client: JwClient, cfg: dict[str, Any], log: LogFn) -> dict[str, Any]:
    local = load_local_courses()
    if local and local.get("items"):
        return local
    targets = [k for k in cfg.get("course", {}) if k]
    hint = time_mismatch_hint(cfg)
    if hint:
        log(f"注意：{hint}")
    if targets:
        client.fetch_stu_info(cfg_for_jxbmc_query(cfg, targets[0]))
        log(
            f"本地无 course.json，按配置中的 {len(targets)} 个教学班在线查询（比全量快）…"
        )
        items: list[dict[str, Any]] = []
        for jxbmc in targets:
            qcfg = cfg_for_jxbmc_query(cfg, jxbmc)
            tm = qcfg["time"]
            log(
                f"查询教学班: {jxbmc}（{tm['XueNian']} 学年第 {tm['XueQi']} 学期）"
            )
            part = client.fetch_courses_online(qcfg, jxbmc=jxbmc)
            hit = _find_item(part, jxbmc)
            if hit:
                items.append(hit)
            else:
                for row in part.get("items", []):
                    if row.get("jxbmc") == jxbmc:
                        items.append(row)
                        break
                if not hit and not any(
                    row.get("jxbmc") == jxbmc for row in part.get("items", [])
                ):
                    n = len(part.get("items") or [])
                    log(f"  教务返回 {n} 条，未包含该教学班名称")
        if not items:
            extra = f" {hint}" if hint else ""
            raise RuntimeError(
                "未查到配置中的教学班：请核对教学班是否从教务「任务落实查询」完整复制；"
                "学年学期需与括号内一致，例如 (2026-2027-1) 对应学年 2026、学期 1。"
                f"{extra}"
            )
        data = {"items": items}
        save_local_courses(data)
        log(f"已保存 course.json（{len(items)} 条）")
        return data

    client.fetch_stu_info(cfg)
    log("本地无 course.json，正在全量拉取任务落实课程（可能需数分钟，请保持校园网/VPN）…")
    try:
        data = client.fetch_courses_online(cfg)
    except Exception as e:
        if "timed out" in str(e).lower() or "Timeout" in type(e).__name__:
            raise RuntimeError(
                "拉取课程列表超时：请连接校园网或 VPN 后重试；"
                "或在 config 里先填写教学班名称，或将 course.json 放到 data/course/"
            ) from e
        raise
    save_local_courses(data)
    log(f"已保存 course.json（{len(data.get('items', []))} 条）")
    return data


def _find_item(catalog: dict[str, Any], jxbmc: str) -> dict[str, Any] | None:
    for item in catalog.get("items", []):
        if item.get("jxbmc") == jxbmc:
            return item
    return None


def resolve_item(
    client: JwClient,
    cfg: dict[str, Any],
    catalog: dict[str, Any],
    jxbmc: str,
    log: LogFn,
) -> dict[str, Any]:
    """本地 course.json 有则用缓存，否则按教学班名在线查询并写入缓存。"""
    item = _find_item(catalog, jxbmc)
    if item:
        return item
    log(f"{jxbmc} 尝试在线查询…")
    online = client.fetch_courses_online(cfg_for_jxbmc_query(cfg, jxbmc), jxbmc=jxbmc)
    item = _find_item(online, jxbmc)
    if not item:
        raise RuntimeError(f"未找到教学班: {jxbmc}")
    catalog.setdefault("items", []).append(item)
    save_local_courses(catalog)
    return item


def handle_one(
    client: JwClient,
    cfg: dict[str, Any],
    catalog: dict[str, Any],
    jxbmc: str,
    select_flag: str,
    log: LogFn,
) -> None:
    item = resolve_item(client, cfg, catalog, jxbmc, log)

    kklx = KKLX_MAP.get(item.get("kklxmc", ""))
    if not kklx:
        raise RuntimeError(f"未知课程类型: {item.get('kklxmc')}")

    log(f"处理 {jxbmc} | {item.get('kcmc')} | {item.get('sksj')}")
    do_id = client.get_do_jxb_id(cfg, item, kklx)
    if select_flag == "1":
        res = client.select_course(cfg, do_id, item["kch_id"], kklx, item.get("jxbzc", ""))
        if res.get("flag") == "1":
            log("选课成功")
        else:
            log(f"选课结果: {res.get('msg', res)}")
    else:
        raw = client.cancel_course(cfg, do_id, item["kch_id"])
        log(f"退课结果: {raw}")


def run_scheduled(
    client: JwClient,
    cfg: dict[str, Any],
    catalog: dict[str, Any],
    log: LogFn,
    cancel: Callable[[], bool],
) -> None:
    start = cfg.get("start_time", "")
    if not start:
        raise ValueError("请设置 start_time")
    target = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
    log(f"等待开始时间: {target}")
    while datetime.now() < target:
        if cancel():
            return
        time.sleep(0.5)

    log("时间到，开始选退课…")
    client.fetch_body_config()
    for jxbmc, flag in cfg.get("course", {}).items():
        if cancel():
            return
        log("-" * 40)
        try:
            handle_one(client, cfg, catalog, jxbmc, str(flag), log)
        except Exception as e:
            log(f"失败: {format_jw_error(e)}")


def run_wait(
    client: JwClient,
    cfg: dict[str, Any],
    catalog: dict[str, Any],
    log: LogFn,
    cancel: Callable[[], bool],
) -> None:
    interval = int(cfg.get("wait_course", {}).get("interval", 60))
    cfg.setdefault("cookies", {})["enabled"] = "0"
    client.fetch_body_config()
    log("蹲课模式已启动")

    round_no = 0
    while not cancel():
        round_no += 1
        log(f"第 {round_no} 轮扫描…")
        for jxbmc, flag in cfg.get("course", {}).items():
            if flag != "1" or cancel():
                continue
            try:
                item = resolve_item(client, cfg, catalog, jxbmc, log)
            except Exception as e:
                log(f"{jxbmc} 查询失败: {format_jw_error(e, will_retry=True)}")
                continue
            kklx = KKLX_MAP.get(item.get("kklxmc", ""))
            if not kklx:
                log(f"{jxbmc} 未知课程类型: {item.get('kklxmc')}")
                continue
            try:
                if client.search_course_has_seat(cfg, kklx, jxbmc):
                    log(f"{jxbmc} 有余量，尝试选课…")
                    handle_one(client, cfg, catalog, jxbmc, "1", log)
                    cfg["course"][jxbmc] = "0"
                    save_config(cfg)
                    return
                log(f"{jxbmc} 暂无余量")
            except Exception as e:
                log(f"{jxbmc} {format_jw_error(e, will_retry=True)}")
        for _ in range(interval):
            if cancel():
                return
            time.sleep(1)
