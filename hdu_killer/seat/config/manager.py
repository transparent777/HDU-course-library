"""Configuration manager: load, save, validate, migrate."""

from __future__ import annotations

import os
import shutil
import logging
from typing import Optional, List, Dict, Any

import yaml

from hdu_killer.seat.config.schema import get_default_config, V1_INDICATORS
from hdu_killer.seat.models.plan import Plan
from hdu_killer.seat.models.schedule import Schedule

logger = logging.getLogger("hdu_killer.seat.config")


class ConfigManager:
    """Manages the V2 config.yaml lifecycle."""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self._config: Optional[Dict[str, Any]] = None

    @property
    def config(self) -> Dict[str, Any]:
        if self._config is None:
            raise RuntimeError("Config not loaded. Call load() first.")
        return self._config

    @property
    def config_dir(self) -> str:
        return os.path.dirname(self.config_path)

    def load(self) -> Dict[str, Any]:
        """Load config from file, creating or migrating as needed."""
        if not os.path.exists(self.config_path):
            logger.info("Config file not found, creating default: %s", self.config_path)
            self._create_default()
            return self._config

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if raw is None:
            raw = {}

        # Detect V1 format and migrate
        if self._is_v1(raw):
            logger.info("Detected V1 config format, migrating to V2...")
            raw = self._migrate_v1_to_v2(raw)

        self._config = raw
        return self._config

    def save(self):
        """Save current config to file."""
        if self._config is None:
            return
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, encoding="utf-8", allow_unicode=True, default_flow_style=False)

    def get_plans(self) -> List[Plan]:
        """Get all plans from config."""
        raw_plans = self.config.get("plans", [])
        return [Plan.from_dict(p) for p in raw_plans]

    def get_plan_by_id(self, plan_id: str) -> Optional[Plan]:
        """Get a specific plan by ID."""
        for plan in self.get_plans():
            if plan.id == plan_id:
                return plan
        return None

    def get_schedules(self) -> List[Schedule]:
        """Get all schedules from config."""
        raw_schedules = self.config.get("schedules", [])
        schedules = []
        for i, raw in enumerate(raw_schedules):
            try:
                schedules.append(Schedule.from_dict(raw))
            except (ValueError, KeyError) as e:
                logger.warning("跳过无效的调度配置 #%d: %s (错误: %s)", i + 1, raw, e)
        return schedules

    def get_user_info(self) -> Dict[str, str]:
        """Get user credentials."""
        return self.config.get("user", {})

    def get_settings(self) -> Dict[str, Any]:
        """Get settings with defaults."""
        defaults = {"interval": 5, "max_try_times": 10, "auto_relogin": True}
        settings = self.config.get("settings", {})
        return {**defaults, **settings}

    def get_api_base_url(self) -> str:
        """Get API base URL."""
        api = self.config.get("api", {})
        return api.get("base_url", "https://hdu.huitu.zhishulib.com")

    def get_session_config(self) -> Dict[str, Any]:
        """Get session configuration."""
        return self.config.get("session", {})

    def save_plans(self, plans: List[Plan]):
        """Save plans list to config."""
        self.config["plans"] = [p.to_dict() for p in plans]
        self.save()

    def add_plan(self, plan: Plan):
        """Add a plan to config."""
        plans = self.config.get("plans", [])
        plans.append(plan.to_dict())
        self.config["plans"] = plans
        self.save()

    def delete_plan(self, plan_id: str) -> bool:
        """Delete a plan by ID. Returns True if deleted."""
        plans = self.config.get("plans", [])
        new_plans = [p for p in plans if p.get("id") != plan_id]
        if len(new_plans) == len(plans):
            return False
        self.config["plans"] = new_plans
        self.save()
        return True

    def replace_plan(self, plan: Plan) -> bool:
        """按方案 id 覆盖保存；id 不存在则返回 False。"""
        raw = self.config.get("plans", [])
        found = False
        for i, p in enumerate(raw):
            if p.get("id") == plan.id:
                raw[i] = plan.to_dict()
                found = True
                break
        if not found:
            return False
        self.config["plans"] = raw
        self.save()
        return True

    def save_schedules(self, schedules: List[Schedule]):
        """Save schedules list to config."""
        self.config["schedules"] = [s.to_dict() for s in schedules]
        self.save()

    def update_user_info(self, login_name: str = None, password: str = None):
        """Update user credentials."""
        user = self.config.get("user", {})
        if login_name is not None:
            user["login_name"] = login_name
        if password is not None:
            user["password"] = password
        self.config["user"] = user
        self.save()

    def update_settings(self, interval: int = None, max_try_times: int = None):
        """Update settings."""
        settings = self.config.get("settings", {})
        if interval is not None:
            settings["interval"] = interval
        if max_try_times is not None:
            settings["max_try_times"] = max_try_times
        self.config["settings"] = settings
        self.save()

    def _create_default(self):
        """Create default config file."""
        self._config = get_default_config()
        self.save()

    def _is_v1(self, raw: dict) -> bool:
        """Detect V1 config format."""
        return any(key in raw for key in V1_INDICATORS)

    def _migrate_v1_to_v2(self, raw: dict) -> dict:
        """Migrate V1 config to V2 format."""
        # Backup old file
        backup_path = self.config_path + ".v1.bak"
        if not os.path.exists(backup_path):
            shutil.copy2(self.config_path, backup_path)
            logger.info("V1 config backed up to: %s", backup_path)

        # Build V2 config
        v2 = get_default_config()

        # Migrate user info
        old_user = raw.get("user_info", {})
        v2["user"] = {
            "login_name": old_user.get("login_name", ""),
            "password": old_user.get("password", ""),
            "org_id": old_user.get("org_id", "104"),
        }

        # Migrate settings
        old_settings = raw.get("settings", {})
        v2["settings"] = {
            "interval": old_settings.get("interval", 5),
            "max_try_times": old_settings.get("max_try_times", 10),
            "auto_relogin": True,
        }

        # Migrate session config
        old_session = raw.get("session", {})
        if old_session:
            v2["session"] = old_session

        # Migrate API base URL from old URLs
        old_urls = raw.get("urls", {})
        if old_urls.get("query_rooms"):
            from urllib.parse import urlparse
            parsed = urlparse(old_urls["query_rooms"])
            v2["api"]["base_url"] = f"{parsed.scheme}://{parsed.netloc}"

        # Migrate plans: V1 plans have datetime objects, convert to time-only templates
        old_plans = raw.get("plans", [])
        new_plans = []
        for i, old_plan in enumerate(old_plans):
            begin_time = old_plan.get("beginTime")
            if isinstance(begin_time, str):
                # Try to parse datetime string
                from datetime import datetime
                try:
                    dt_obj = datetime.strptime(begin_time, "%Y-%m-%d %H:%M:%S")
                    time_str = dt_obj.strftime("%H:%M:%S")
                except ValueError:
                    time_str = "08:00:00"
            elif hasattr(begin_time, "hour"):
                # It's a datetime object
                time_str = begin_time.strftime("%H:%M:%S")
            else:
                time_str = "08:00:00"

            seats_info = old_plan.get("seatsInfo", [])
            seats = []
            for s in seats_info:
                seats.append({
                    "seat_id": str(s.get("seatId", s.get("id", ""))),
                    "seat_num": str(s.get("seatNum", s.get("title", ""))),
                })

            new_plan = {
                "id": f"migrated_plan_{i + 1}",
                "room_name": old_plan.get("roomName", ""),
                "floor_name": seats_info[0].get("floorName", "") if seats_info else "",
                "begin_time": time_str,
                "duration_hours": int(old_plan.get("duration", 4)),
                "seats": seats,
            }
            new_plans.append(new_plan)

        v2["plans"] = new_plans
        v2["schedules"] = []

        # Save migrated config
        self._config = v2
        self.save()
        logger.info("V1 config migrated to V2 successfully")
        return v2
