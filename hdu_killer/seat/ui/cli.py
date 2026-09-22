"""Interactive CLI menu - rewrite of main.py UserInterface.

Supports:
- Interactive mode: full menu, scheduler runs in background
- Menu remains available while scheduler is active
"""

from __future__ import annotations

import os
import sys
import logging
from datetime import datetime
from time import sleep

from pwinput import pwinput

from hdu_killer.seat.config.manager import ConfigManager
from hdu_killer.seat.auth.session_manager import SessionManager
from hdu_killer.seat.api.client import ApiClient
from hdu_killer.seat.api.room_cache import RoomCache
from hdu_killer.seat.scheduler.engine import SchedulerEngine
from hdu_killer.seat.scheduler.booking_runner import BookingRunner
from hdu_killer.seat.models.plan import Plan, SeatInfo
from hdu_killer.seat.models.schedule import Schedule, DateMapping
from hdu_killer.seat.models.booking_result import BookingResult
from hdu_killer.seat.ui.display import (
    Color, colorize, print_table, print_success, print_error,
    print_warning, print_info, print_countdown, WEEKDAY_NAMES,
)
from hdu_killer.seat.platform_.paths import get_app_dir
from hdu_killer.seat.logging_.history import HistoryLogger

logger = logging.getLogger("hdu_killer.seat.ui")


class CliUI:
    """抢座命令行交互。"""

    def __init__(self, config_manager: ConfigManager,
                 session_manager: SessionManager,
                 api_client: ApiClient,
                 room_cache: RoomCache):
        self.config = config_manager
        self.session_mgr = session_manager
        self.api = api_client
        self.room_cache = room_cache

        # Create booking runner and scheduler engine
        settings = self.config.get_settings()
        self.runner = BookingRunner(
            api_client=self.api,
            session_manager=self.session_mgr,
            interval=settings["interval"],
            max_try_times=settings["max_try_times"],
        )
        self.engine = SchedulerEngine(
            config_manager=self.config,
            session_manager=self.session_mgr,
            booking_runner=self.runner,
        )
        self.history = HistoryLogger()

        # Engine callbacks
        self.engine.on_countdown_tick = self._on_countdown_tick
        self.engine.on_booking_result = self._on_booking_result
        self.engine.on_booking_start = self._on_booking_start
        self.engine.on_error = self._on_engine_error

    def login(self):
        """Handle login flow with retry logic."""
        flag = False
        network_retry_count = 0
        max_network_retries = 5

        while not flag:
            user = self.config.get_user_info()
            if user.get("login_name") and user.get("password"):
                success, err_type = self.session_mgr.login()
                if success:
                    print_success("登录成功")
                    self.config.save()
                    # Start room data refresh in background
                    self.room_cache.start_background_refresh()
                    flag = True
                elif err_type == "network":
                    network_retry_count += 1
                    if network_retry_count <= max_network_retries:
                        wait = min(network_retry_count * 5, 30)
                        print_warning(f"网络连接失败，{wait}秒后第{network_retry_count}次重试...")
                        sleep(wait)
                    else:
                        print_error(f"网络连接持续失败，已重试{max_network_retries}次。")
                        print("可能的原因：")
                        print("  1. 不在校园网环境内（需要连接HDU校园网或VPN）")
                        print("  2. 图书馆服务器暂时不可用")
                        print("  3. 网络防火墙拦截了连接")
                        retry = input("是否继续重试？(y/n): ").strip().lower()
                        if retry == "y":
                            network_retry_count = 0
                        else:
                            sys.exit(1)
                else:
                    print_error("账号密码错误，请重新输入")
                    self._set_user_info()
            else:
                self._set_user_info()

    def show_menu(self):
        """Display main menu."""
        print("\n" + "=" * 40)
        status = ""
        if self.engine.is_running:
            status = colorize(" [调度运行中]", Color.GREEN)
        print(colorize(f"图书馆抢座 主菜单{status}", Color.BOLD))
        print("=" * 40)
        print("1. 查看/添加/删除座位方案")
        print("2. 批量修改方案预约时间")
        print("3. 立即开始抢座")
        print("4. 启动/管理定时调度")
        print("5. 查看调度状态")
        print("6. 修改请求间隔和次数")
        print("7. 使用帮助")
        print("8. 退出")

    def run(self):
        """Main menu loop."""
        while True:
            self.show_menu()
            try:
                choice = input("请输入选项：").strip()
                if not choice:
                    continue
                choice = int(choice)
                if choice == 1:
                    self._manage_plans()
                elif choice == 2:
                    self._change_time()
                elif choice == 3:
                    self._start_now()
                elif choice == 4:
                    self._manage_schedules()
                elif choice == 5:
                    self._show_status()
                elif choice == 6:
                    self._set_settings()
                elif choice == 7:
                    self._help()
                elif choice == 8:
                    self._exit()
                else:
                    print_error("输入错误，请重新输入")
            except ValueError:
                print_error("请输入数字")
            except KeyboardInterrupt:
                print("\n")
                self._exit()

    # --- Plan management ---

    def _manage_plans(self):
        """View/add/delete plans."""
        self._show_plans()
        while True:
            print("\n1. 添加方案")
            print("2. 删除方案")
            print("3. 返回上一级")
            try:
                choice = int(input("请输入选项："))
                if choice == 1:
                    self._add_plan()
                elif choice == 2:
                    self._delete_plan()
                elif choice == 3:
                    break
                else:
                    print_error("输入错误")
            except ValueError:
                print_error("请输入数字")
            except KeyboardInterrupt:
                print("\n已取消")
                return

    def _show_plans(self):
        """Display all plans in a table."""
        plans = self.config.get_plans()
        print_info(f"当前共有{len(plans)}个预约方案")
        if not plans:
            return
        headers = ["序号", "方案ID", "房间名", "楼层名", "座位号", "开始时间", "时长"]
        rows = []
        for i, plan in enumerate(plans):
            seats_str = ",".join(s.seat_num for s in plan.seats)
            rows.append([
                str(i + 1), plan.id, plan.room_name, plan.floor_name,
                seats_str, plan.begin_time, f"{plan.duration_hours}小时"
            ])
        print_table(headers, rows)

    def _add_plan(self):
        """Interactively add a new plan."""
        try:
            print("请根据系统提示填写座位预约信息，过程中可随时使用Ctrl+C取消。")

            # Wait for room data
            if not self.room_cache.is_ready:
                print_info("正在加载房间信息，请稍候...")
                self.room_cache.refresh()

            rooms = self.room_cache.rooms
            if not rooms:
                print_error("无法获取房间信息，请检查网络连接")
                return

            room_names = list(rooms.keys())
            for i, name in enumerate(room_names):
                print(f"  {i + 1}. {name}")
            room_idx = int(input(f"请选择房间类型(1-{len(room_names)})：")) - 1
            if room_idx < 0 or room_idx >= len(room_names):
                print_error("房间类型不合法")
                return
            room_name = room_names[room_idx]
            room_data = rooms[room_name]

            floors = self.room_cache.get_floor_names(room_name)
            if not floors:
                print_error(f"{room_name}没有开放楼层")
                return
            for i, f in enumerate(floors):
                print(f"  {i + 1}. {f}")
            floor_idx = int(input(f"请选择楼层(1-{len(floors)})：")) - 1
            if floor_idx < 0 or floor_idx >= len(floors):
                print_error("楼层不合法")
                return
            floor_name = floors[floor_idx]

            # Show room hours
            range_info = room_data.get("range", {})
            min_hour = range_info.get("minBeginTime", 0)
            max_hour = range_info.get("maxEndTime", 24)
            print_info(f"开放时间: {min_hour}:00-{max_hour}:00")

            time_str = input("请输入开始时间（HH:MM:SS，如 08:00:00）：").strip()
            hour = int(time_str.split(":")[0])
            if hour < min_hour or hour > max_hour:
                print_error(f"开始时间不在房间开放时间内({min_hour}:00-{max_hour}:00)")
                return

            max_duration = max_hour - hour
            duration = int(input(f"请输入使用时长（1-{max_duration}小时）："))
            if duration < 1 or duration > max_duration:
                print_error(f"使用时长不合法")
                return
            if hour + duration > 22:
                print_error(
                    f"开始时间({hour}:00) + 使用时长({duration}小时) = "
                    f"{hour + duration}:00，超过了图书馆最晚预约时间22:00"
                )
                return

            # Select seats
            seats_info = self.room_cache.get_seats(room_name, floor_name)
            seats_input = input("请输入座位号（多个用逗号隔开，如1,2,3）：")
            seat_nums = [s.strip() for s in seats_input.split(",") if s.strip()]

            seat_list = []
            for seat_num in seat_nums:
                matched = [s for s in seats_info if s["title"] == seat_num]
                if not matched:
                    print_error(f"{floor_name}中座位{seat_num}不存在")
                    return
                if len(matched) > 1:
                    print_error(f"座位{seat_num}存在多个匹配")
                    return
                seat_list.append(SeatInfo(
                    seat_id=str(matched[0]["id"]),
                    seat_num=matched[0]["title"],
                ))

            plan_id = input("请输入方案ID（用于标识，如 morning_A42）：").strip()
            if not plan_id:
                plan_id = f"plan_{datetime.now().strftime('%H%M%S')}"

            plan = Plan(
                id=plan_id,
                room_name=room_name,
                floor_name=floor_name,
                begin_time=time_str,
                duration_hours=duration,
                seats=seat_list,
            )
            self.config.add_plan(plan)
            print_success(f"方案 '{plan_id}' 添加成功")
            self._show_plans()

        except KeyboardInterrupt:
            print("\n已取消")
        except Exception as e:
            print_error(str(e))
            print("输入错误，取消本次操作")

    def _delete_plan(self):
        """Delete plans by index."""
        self._show_plans()
        try:
            index_str = input("请输入要删除的方案序号（多个用逗号隔开，如1,2,3）：")
            indices = [int(x.strip()) for x in index_str.split(",") if x.strip()]
            plans = self.config.get_plans()
            for idx in indices:
                if idx < 1 or idx > len(plans):
                    print_error(f"序号{idx}超出范围")
                    return
            # Delete in reverse order
            plan_ids = [plans[idx - 1].id for idx in indices]
            for pid in plan_ids:
                self.config.delete_plan(pid)
            print_success("删除成功")
            self._show_plans()
        except ValueError:
            print_error("请输入有效数字")
        except Exception as e:
            print_error(str(e))

    def _change_time(self):
        """Batch modify plan times."""
        self._show_plans()
        try:
            index_str = input("请输入要修改的方案序号（多个用逗号隔开，输入0表示全部）：")
            indices = [int(x.strip()) for x in index_str.split(",") if x.strip()]
            plans = self.config.get_plans()
            if 0 in indices:
                indices = list(range(1, len(plans) + 1))
            if any(idx < 1 or idx > len(plans) for idx in indices):
                print_error("序号超出范围")
                return

            print_warning("错误的时间可能导致封号一周，请仔细检查。")
            time_str = input("请输入开始时间（HH:MM:SS，如 08:00:00）：").strip()
            # Validate time format
            import re
            if not re.match(r"^\d{2}:\d{2}:\d{2}$", time_str):
                print_error("时间格式不正确，请使用 HH:MM:SS 格式")
                return
            duration = int(input("请输入使用时长（小时）："))
            if duration < 1:
                print_error("时长不能小于1")
                return
            batch_hour = int(time_str.split(":")[0])
            if batch_hour + duration > 22:
                print_error(
                    f"开始时间({batch_hour}:00) + 使用时长({duration}小时) = "
                    f"{batch_hour + duration}:00，超过了图书馆最晚预约时间22:00"
                )
                return

            all_plans = self.config.config.get("plans", [])
            for idx in indices:
                all_plans[idx - 1]["begin_time"] = time_str
                all_plans[idx - 1]["duration_hours"] = duration
            self.config.save()
            print_success("修改成功")
            self._show_plans()
        except Exception as e:
            print_error(str(e))

    # --- Booking ---

    def _start_now(self, prompt="按回车键继续"):
        """Execute immediate booking. Tries all plans per round, stops on first success."""
        plans = self.config.get_plans()
        if not plans:
            print_error("没有预约方案，请先添加方案")
            return
        # Pre-run validation
        errors = []
        for plan in plans:
            errors.extend(plan.validate())
        if errors:
            for err in errors:
                print_error(err)
            return

        settings = self.config.get_settings()
        for retry in range(settings["max_try_times"]):
            print_info(f"第{retry + 1}次尝试")
            for i, plan in enumerate(plans):
                # Build datetime from plan template + today
                now = datetime.now()
                h, m, s = (int(x) for x in plan.begin_time.split(":"))
                begin_time = now.replace(hour=h, minute=m, second=s, microsecond=0)

                seat_ids = [seat.seat_id for seat in plan.seats]
                booker_uids = [self.session_mgr.uid] * len(plan.seats)

                resp = self.api.book_seat(begin_time, plan.duration_hours, seat_ids, booker_uids)
                result = BookingResult.from_api_response(resp, plan_id=plan.id)
                self.history.log(result)

                if result.success:
                    print_success("座位预约成功！")
                    headers = ["房间名", "楼层名", "座位号", "开始时间", "时长"]
                    rows = [[
                        plan.room_name, plan.floor_name,
                        ",".join(s.seat_num for s in plan.seats),
                        plan.begin_time, f"{plan.duration_hours}小时"
                    ]]
                    print_table(headers, rows)
                    input(prompt)
                    return
                else:
                    print_error(f"方案{plan.id}预约失败: {result.message}")

            # Sleep between retry rounds, not between individual plans
            if retry < settings["max_try_times"] - 1:
                sleep(settings["interval"])

    # --- Schedule management ---

    def _manage_schedules(self):
        """Manage schedules: add, view, start/stop."""
        while True:
            print("\n--- 调度管理 ---")
            if self.engine.is_running:
                print(colorize("[调度引擎运行中]", Color.GREEN))
            print("1. 启动自动调度（读取配置文件中的调度表）")
            print("2. 停止自动调度")
            print("3. 添加按星期几调度")
            print("4. 添加按日期调度")
            print("5. 查看已保存的调度")
            print("6. 删除调度")
            print("7. 返回上一级")
            try:
                choice = int(input("请输入选项："))
                if choice == 1:
                    self._start_scheduler()
                elif choice == 2:
                    self._stop_scheduler()
                elif choice == 3:
                    self._add_weekday_schedule()
                elif choice == 4:
                    self._add_date_schedule()
                elif choice == 5:
                    self._show_schedules()
                elif choice == 6:
                    self._delete_schedule()
                elif choice == 7:
                    break
                else:
                    print_error("输入错误")
            except ValueError:
                print_error("请输入数字")
            except KeyboardInterrupt:
                print("\n已取消")
                return

    def _start_scheduler(self):
        """Start the scheduler engine."""
        schedules = self.config.get_schedules()
        if not schedules:
            print_warning("没有配置调度表，请先添加调度")
            return
        active = [s for s in schedules if s.enabled]
        if not active:
            print_warning("所有调度都已禁用")
            return

        plans = self.config.get_plans()
        if not plans:
            print_warning("没有预约方案，请先添加方案")
            return
        # Pre-run validation
        errors = []
        for plan in plans:
            errors.extend(plan.validate())
        if errors:
            for err in errors:
                print_error(err)
            return

        print_info("启动调度引擎...")
        self.engine.start()
        print_success("调度引擎已启动")

    def _stop_scheduler(self):
        """Stop the scheduler engine."""
        if self.engine.is_running:
            self.engine.stop()
            print_success("调度引擎已停止")
        else:
            print_info("调度引擎未在运行")

    def _add_weekday_schedule(self):
        """Add a weekday-based schedule."""
        try:
            print("当前方案：")
            self._show_plans()

            weekdays_input = input("请输入要使用座位的星期几（1-7，对应周一到周日，多个用逗号隔开，如1,3,5）：")
            weekdays_input = weekdays_input.strip().replace("，", ",")
            weekdays = []
            for w in weekdays_input.split(","):
                w = w.strip()
                if not w:
                    continue
                w = int(w)
                if w < 1 or w > 7:
                    print_error(f"星期{w}不合法，请输入1-7之间的数字")
                    return
                weekdays.append(w)
            if not weekdays:
                print_error("至少需要选择一天")
                return
            weekdays = sorted(set(weekdays))

            plan_ids_input = input("请输入要绑定的方案ID（多个用逗号隔开）：")
            plan_ids = [p.strip() for p in plan_ids_input.split(",") if p.strip()]

            # Validate plan IDs exist
            all_plans = self.config.get_plans()
            valid_ids = {p.id for p in all_plans}
            for pid in plan_ids:
                if pid not in valid_ids:
                    print_error(f"方案ID '{pid}' 不存在")
                    return

            schedule = Schedule(
                mode="weekdays",
                target_weekdays=weekdays,
                plan_ids=plan_ids,
            )
            schedules = self.config.get_schedules()
            schedules.append(schedule)
            self.config.save_schedules(schedules)
            print_success("按星期调度添加成功")

        except KeyboardInterrupt:
            print("\n已取消")
        except Exception as e:
            print_error(str(e))

    def _add_date_schedule(self):
        """Add a date-based schedule."""
        try:
            print("当前方案：")
            self._show_plans()

            dates_input = input("请输入要使用座位的日期（YYYY-MM-DD，多个用逗号隔开）：")
            dates_input = dates_input.strip().replace("，", ",")
            dates = [d.strip() for d in dates_input.split(",") if d.strip()]
            if not dates:
                print_error("请输入至少一个日期")
                return

            # Validate dates
            for d in dates:
                datetime.strptime(d, "%Y-%m-%d")

            plan_ids_input = input("请输入要绑定的方案ID（多个用逗号隔开）：")
            plan_ids = [p.strip() for p in plan_ids_input.split(",") if p.strip()]

            all_plans = self.config.get_plans()
            valid_ids = {p.id for p in all_plans}
            for pid in plan_ids:
                if pid not in valid_ids:
                    print_error(f"方案ID '{pid}' 不存在")
                    return

            mappings = [DateMapping(target_date=d, plan_ids=plan_ids) for d in dates]
            schedule = Schedule(mode="dates", mappings=mappings)
            schedules = self.config.get_schedules()
            schedules.append(schedule)
            self.config.save_schedules(schedules)
            print_success("按日期调度添加成功")

        except KeyboardInterrupt:
            print("\n已取消")
        except Exception as e:
            print_error(str(e))

    def _show_schedules(self):
        """Display all saved schedules."""
        schedules = self.config.get_schedules()
        if not schedules:
            print_info("暂无已保存的调度")
            return

        # Build plan id -> plan lookup for detailed display
        plan_map = {p.id: p for p in self.config.get_plans()}

        print_info(f"当前共有{len(schedules)}个调度：")
        for i, s in enumerate(schedules):
            status = colorize("启用", Color.GREEN) if s.enabled else colorize("禁用", Color.RED)
            # Build detailed plan description
            plan_descs = []
            for pid in s.plan_ids if s.mode == "weekdays" else []:
                plan = plan_map.get(pid)
                if plan:
                    seats_str = ",".join(seat.seat_num for seat in plan.seats)
                    plan_descs.append(f"{pid}({plan.room_name} {seats_str}号 {plan.begin_time} {plan.duration_hours}h)")
                else:
                    plan_descs.append(f"{pid}(方案不存在)")
            if s.mode == "weekdays":
                days_str = ", ".join(WEEKDAY_NAMES[w - 1] for w in s.target_weekdays)
                print(f"  {i + 1}. [按星期] {days_str} | {status}")
                for desc in plan_descs:
                    print(f"      方案: {desc}")
            elif s.mode == "dates":
                for m in s.mappings:
                    date_descs = []
                    for pid in m.plan_ids:
                        plan = plan_map.get(pid)
                        if plan:
                            seats_str = ",".join(seat.seat_num for seat in plan.seats)
                            date_descs.append(f"{pid}({plan.room_name} {seats_str}号 {plan.begin_time} {plan.duration_hours}h)")
                        else:
                            date_descs.append(f"{pid}(方案不存在)")
                    print(f"  {i + 1}. [按日期] {m.target_date} | {status}")
                    for desc in date_descs:
                        print(f"      方案: {desc}")

    def _delete_schedule(self):
        """Delete a schedule by index."""
        self._show_schedules()
        schedules = self.config.get_schedules()
        if not schedules:
            return
        try:
            idx = int(input(f"请输入要删除的调度序号(1-{len(schedules)})："))
            if idx < 1 or idx > len(schedules):
                print_error("序号超出范围")
                return
            schedules.pop(idx - 1)
            self.config.save_schedules(schedules)
            print_success("删除成功")
        except ValueError:
            print_error("请输入有效数字")

    def _show_status(self):
        """Show scheduler engine status."""
        if not self.engine.is_running:
            print_info("调度引擎未运行")
            return

        status = self.engine.get_status()
        remaining = status.get("remaining_seconds")
        trigger = status.get("trigger_time")
        plan_ids = status.get("plan_ids", [])

        if remaining is not None and trigger is not None:
            from hdu_killer.seat.ui.display import format_countdown
            remaining_str = format_countdown(remaining)
            print_info(f"下次触发: {trigger.strftime('%Y-%m-%d %H:%M:%S')} | 剩余: {remaining_str}")
            print_info(f"方案: {', '.join(plan_ids)}")
        else:
            print_info("等待下一个调度周期...")

    # --- Settings ---

    def _set_settings(self):
        """Modify request interval and max attempts."""
        try:
            settings = self.config.get_settings()
            print_info(f"当前设置：")
            print(f"  重试间隔：{settings['interval']}秒")
            print(f"  最大重试次数：{settings['max_try_times']}次")

            interval = input(f"请输入重试间隔（秒，建议不小于5）：").strip()
            max_times = input("请输入最大重试次数：").strip()

            self.config.update_settings(
                interval=int(interval) if interval else None,
                max_try_times=int(max_times) if max_times else None,
            )

            # Update runner settings
            settings = self.config.get_settings()
            self.runner.interval = settings["interval"]
            self.runner.max_try_times = settings["max_try_times"]

            print_success("设置已更新")
        except Exception as e:
            print_error(str(e))

    # --- Help ---

    def _help(self):
        """Display help documentation."""
        from hdu_killer.paths import get_seat_manual_path

        help_path = str(get_seat_manual_path())
        if not os.path.exists(help_path):
            print_warning("使用手册未找到（docs/图书馆抢座使用手册.txt）")
            input("按回车键返回")
            return
        if sys.platform == "win32":
            try:
                os.startfile(help_path)
            except OSError:
                with open(help_path, "r", encoding="utf-8") as f:
                    print(f.read())
        else:
            with open(help_path, "r", encoding="utf-8") as f:
                print(f.read())
        input("按回车键返回")

    # --- Engine callbacks ---

    def _on_countdown_tick(self, remaining, trigger_time, plan_desc):
        """Engine callback: countdown tick."""
        print_countdown(remaining, trigger_time, plan_desc)

    def _on_booking_result(self, result: BookingResult):
        """Engine callback: booking result."""
        self.history.log(result)
        if result.success:
            print(f"\n")
            print_success(str(result))
        else:
            print(f"\n")
            print_warning(f"预约失败: {result.message}")

    def _on_booking_start(self, target_date, plan_ids):
        """Engine callback: booking starting."""
        print(f"\n")
        print_info(f"预约开放时间已到达，正在为{target_date.strftime('%Y-%m-%d')}执行预约...")

    def _on_engine_error(self, error):
        """Engine callback: error."""
        print_error(f"调度引擎错误: {error}")

    # --- User info ---

    def _set_user_info(self):
        """Prompt for user credentials."""
        login_name = input("请输入学号：")
        password = pwinput("请输入密码：")
        self.config.update_user_info(login_name=login_name, password=password)

    # --- Exit ---

    def _exit(self):
        """Clean shutdown."""
        if self.engine.is_running:
            print_info("正在停止调度引擎...")
            self.engine.stop()
        if self.room_cache.is_ready:
            self.room_cache.stop_background_refresh()
        print_info("再见！")
        sys.exit(0)
