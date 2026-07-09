#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XMU Rollcall AstrBot Plugin
~~~~~~~~~~~~~~~~~~~~~~~~~~~

厦门大学 TronClass 自动签到监控插件。
通过聊天命令管理监控、WebUI 配置参数、后台轮询签到，
并在检测到签到/签到成功时发送通知。
"""

import asyncio
import json
import logging
import os
import time
import random
from pathlib import Path
from typing import Optional

import requests

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star
from astrbot.api import AstrBotConfig, logger

from .xmulogin import xmulogin
from .utils import save_session, load_session, verify_session
from .rollcall_handler import process_rollcalls

BASE_URL = "https://lnt.xmu.edu.cn"
ROLLCALLS_URL = f"{BASE_URL}/api/radar/rollcalls"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://ids.xmu.edu.cn/authserver/login",
}

# 退避常量
BACKOFF_BASE = 5
BACKOFF_MAX = 60
REAUTH_THRESHOLD = 3
REAUTH_COOLDOWN = 60


class XMURollcallPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 监控状态
        self._session: Optional[requests.Session] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()

        # 运行统计
        self._start_time: float = 0.0
        self._query_count: int = 0
        self._monitoring: bool = False
        self._last_reauth_time: float = 0.0

        # 触发启动命令的会话 UMO（备用通知目标）
        self._last_trigger_umo: str = ""

        # 数据目录（session 持久化）
        self._data_dir: Path = self._get_data_dir()
        self._cookies_path: Path = self._data_dir / "session.json"

        # logger
        self._log = logger

    # ───────────────── helper ─────────────────

    def _get_data_dir(self) -> Path:
        """获取插件数据目录。"""
        try:
            data_dir = Path(self.context.plugin_data_dir)
        except (AttributeError, TypeError):
            data_dir = Path(__file__).parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    # ───────────────── lifecycle ─────────────────

    async def initialize(self):
        """插件加载时调用。"""
        self._log.info("XMU Rollcall Plugin initializing...")

        # 尝试恢复 session
        await self._load_cached_session()

        # 如果配置了自动启动
        if self.config.get("enabled", False):
            if self._validate_config():
                await self._send_notification("XMU Rollcall Plugin: 自动开始监控")
                await self.start_monitoring()
            else:
                self._log.warning("Auto-start skipped: missing credentials")

    async def terminate(self):
        """插件卸载时调用。"""
        self._log.info("XMU Rollcall Plugin terminating...")
        await self.stop_monitoring()

    # ───────────────── config validation ─────────────────

    def _validate_config(self) -> bool:
        return bool(
            self.config.get("username", "").strip()
            and self.config.get("password", "").strip()
        )

    # ───────────────── session management ─────────────────

    async def _load_cached_session(self):
        """尝试从磁盘恢复 session（async 包装）。"""
        sess = requests.Session()
        if self._cookies_path.exists():
            loaded = await asyncio.to_thread(
                load_session, sess, str(self._cookies_path)
            )
            if loaded:
                profile = await asyncio.to_thread(verify_session, sess)
                if profile:
                    self._session = sess
                    name = profile.get("name", "unknown")
                    self._log.info(f"Session restored for {name}")
                    return
        self._log.info("No valid cached session")

    async def _login(self) -> bool:
        """登录 XMU 统一身份认证（async 包装）。"""
        username = self.config.get("username", "").strip()
        password = self.config.get("password", "").strip()
        if not username or not password:
            self._log.error("Login failed: missing credentials")
            return False

        session = await asyncio.to_thread(
            xmulogin, type=3, username=username, password=password
        )
        if session:
            self._session = session
            await asyncio.to_thread(save_session, session, str(self._cookies_path))
            self._log.info("Login successful, session saved")
            return True
        else:
            self._log.error("Login failed")
            return False

    async def _verify_and_reauth(self) -> bool:
        """验证 session 有效性，若过期则重新登录。"""
        if self._session is None:
            return await self._login()

        profile = await asyncio.to_thread(verify_session, self._session)
        if profile:
            return True

        self._log.warning("Session expired, re-authenticating...")
        await self._send_notification("Session expired, attempting re-login...")
        return await self._login()

    # ───────────────── time window ─────────────────

    def _parse_schedule(self):
        """解析 schedule 配置，返回 list[dict] 或 None（使用默认 start_hour/end_hour）。"""
        raw = self.config.get("schedule", "")
        if not raw or not raw.strip():
            return None
        try:
            schedule = json.loads(raw)
            if not isinstance(schedule, list) or len(schedule) == 0:
                return None
            return schedule
        except (json.JSONDecodeError, TypeError):
            self._log.warning("Invalid schedule JSON, using default hours")
            return None

    def _hour_in_range(self, current_hour: int, start: int, end: int) -> bool:
        """检查小时是否在 [start, end) 范围内，支持跨夜。"""
        if start == end:
            return True
        if start < end:
            return start <= current_hour < end
        else:
            return current_hour >= start or current_hour < end

    def _is_in_time_window(self) -> bool:
        """检查当前时间是否在监控窗口内。优先使用 schedule，否则用默认 start_hour/end_hour。"""
        schedule = self._parse_schedule()
        now = time.localtime()
        current_hour = now.tm_hour
        current_wday = now.tm_wday  # 0=Mon, 1=Tue, ..., 6=Sun

        if schedule:
            for entry in schedule:
                days = entry.get("days", [0, 1, 2, 3, 4, 5, 6])
                start = entry.get("start", entry.get("start_hour", 0))
                end = entry.get("end", entry.get("end_hour", 23))
                if current_wday in days and self._hour_in_range(current_hour, start, end):
                    return True
            return False

        # 回退：使用默认时间窗口
        start_hour = self.config.get("monitor_start_hour", 0)
        end_hour = self.config.get("monitor_end_hour", 23)
        return self._hour_in_range(current_hour, start_hour, end_hour)

    # ───────────────── notification ─────────────────

    async def _send_notification(self, message: str):
        """发送通知到所有配置的目标（若未配置则回退到触发命令的会话）。"""
        targets = self.config.get("notify_chats", [])
        if not targets:
            if self._last_trigger_umo:
                targets = [self._last_trigger_umo]
            else:
                return

        chain = MessageChain().message(message)
        for target_id in targets:
            try:
                await self.context.send_message(target_id, chain)
            except Exception as e:
                self._log.error(f"Failed to send to {target_id}: {e}")

    # ───────────────── monitor loop ─────────────────

    async def start_monitoring(self) -> bool:
        """启动后台监控任务。"""
        if self._monitor_task and not self._monitor_task.done():
            self._log.warning("Monitor already running")
            return False

        if not await self._verify_and_reauth():
            await self._send_notification(
                "ERROR: Cannot start monitoring - login failed. Check credentials."
            )
            return False

        self._stop_event.clear()
        self._start_time = time.time()
        self._query_count = 0
        self._monitoring = True

        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self._log.info("Monitoring started")
        return True

    async def stop_monitoring(self):
        """停止后台监控任务。"""
        if not self._monitoring:
            return

        self._stop_event.set()
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        self._monitoring = False
        self._log.info("Monitoring stopped")

    async def _sleep_with_stop_check(self, seconds: float):
        """分片 sleep，能快速响应 stop 信号。"""
        step = 0.5
        elapsed = 0.0
        while elapsed < seconds:
            if self._stop_event.is_set():
                return
            await asyncio.sleep(min(step, seconds - elapsed))
            elapsed += step

    async def _monitor_loop(self):
        """主监控协程——monitor.py 的 async 版本。"""

        interval = self.config.get("interval", 3)
        last_data = {"rollcalls": []}
        consecutive_errors = 0
        last_reauth_time = 0.0

        while not self._stop_event.is_set():
            try:
                # ── 时间窗口检查 ──
                if not self._is_in_time_window():
                    await self._sleep_with_stop_check(60)
                    continue

                # ── HTTP 请求 ──
                try:
                    res = await asyncio.to_thread(
                        self._session.get,
                        ROLLCALLS_URL,
                        headers=HEADERS,
                        timeout=10,
                    )
                except Exception as e:
                    raise e

                # ── 认证失败 ──
                if res.status_code in (401, 403):
                    consecutive_errors += 1
                    if consecutive_errors >= REAUTH_THRESHOLD:
                        now = time.time()
                        if now - last_reauth_time >= REAUTH_COOLDOWN:
                            last_reauth_time = now
                            if await self._verify_and_reauth():
                                consecutive_errors = 0
                    await self._sleep_with_stop_check(interval * 2)
                    continue

                data = res.json()
                self._query_count += 1
                consecutive_errors = 0

                # ── 检测新签到 ──
                if data != last_data and len(data.get("rollcalls", [])) > 0:
                    await self._handle_new_rollcalls(data, last_data)
                    last_data = data

                # ── 等待下一轮 ──
                await self._sleep_with_stop_check(interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_errors += 1
                backoff = min(
                    BACKOFF_BASE * (2 ** (consecutive_errors - 1)), BACKOFF_MAX
                )
                self._log.error(
                    f"Monitor error (attempt {consecutive_errors}): {e}"
                )

                if consecutive_errors >= REAUTH_THRESHOLD:
                    now = time.time()
                    if now - last_reauth_time >= REAUTH_COOLDOWN:
                        last_reauth_time = now
                        if await self._verify_and_reauth():
                            consecutive_errors = 0

                await self._sleep_with_stop_check(backoff)

        self._log.info("Monitor loop exited normally")

    # ───────────────── rollcall handling ─────────────────

    async def _handle_new_rollcalls(self, data: dict, previous_data: dict):
        """处理新检测到的签到并发送通知。"""

        strategy = {
            "random_delay_max": self.config.get("random_delay_max", 5),
            "number_code_method": self.config.get("number_code_method", 1),
        }

        rollcalls = data.get("rollcalls", [])
        previous_ids = {
            rc.get("rollcall_id") for rc in previous_data.get("rollcalls", [])
        }

        # 通知新签到
        for rc in rollcalls:
            rc_id = rc.get("rollcall_id")
            if rc_id not in previous_ids:
                course = rc.get("course_title", "Unknown")
                teacher = rc.get("department_name", "Unknown")
                created_by = rc.get("created_by_name", "")
                present = rc.get("present_count", 0)
                rc_type = (
                    "Radar"
                    if rc.get("is_radar")
                    else "Number"
                    if rc.get("is_number")
                    else "QRCode"
                )
                await self._send_notification(
                    f"🔔 New rollcall!\n"
                    f"Course: {course}\n"
                    f"Teacher: {teacher} {created_by}\n"
                    f"Type: {rc_type}\n"
                    f"Signed: {present} student(s)"
                )

        # 执行签到（在独立线程中运行同步代码）
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None, process_rollcalls, data, self._session, strategy
        )

        # 通知签到结果
        if results:
            for r in results:
                course = r.get("course_title", "Unknown")
                if r.get("success"):
                    if r.get("type") == "number" and r.get("number_code"):
                        await self._send_notification(
                            f"✅ {course}\n"
                            f"Number code: {r['number_code']}"
                        )
                    elif r.get("type") == "radar":
                        await self._send_notification(
                            f"✅ {course}\nRadar answered"
                        )
                    else:
                        await self._send_notification(
                            f"✅ {course}\n{r.get('message', 'Done')}"
                        )
                else:
                    await self._send_notification(
                        f"❌ {course}\n{r.get('message', 'Failed')}"
                    )

    # ───────────────── commands ─────────────────

    @filter.command("rollcall-start")
    async def cmd_start(self, event: AstrMessageEvent):
        """启动签到监控。"""
        if not self._validate_config():
            yield event.plain_result(
                "Configuration incomplete. "
                "Please set username and password in WebUI."
            )
            return

        if self._monitoring:
            yield event.plain_result("Monitoring is already running.")
            return

        # 记录触发会话，用作通知回退目标
        self._last_trigger_umo = event.unified_msg_origin

        yield event.plain_result("Starting monitor...")

        success = await self.start_monitoring()
        if success:
            yield event.plain_result(
                "Monitoring started.\n"
                f"Account: {self.config.get('username', 'N/A')[:3]}***\n"
                f"Interval: {self.config.get('interval', 3)}s"
            )
        else:
            yield event.plain_result(
                "Failed to start monitoring. Check credentials and try again."
            )

    @filter.command("rollcall-stop")
    async def cmd_stop(self, event: AstrMessageEvent):
        """停止签到监控。"""
        if not self._monitoring:
            yield event.plain_result("Monitoring is not running.")
            return

        await self.stop_monitoring()

        running_time = int(time.time() - self._start_time)
        hours = running_time // 3600
        minutes = (running_time % 3600) // 60
        secs = running_time % 60

        yield event.plain_result(
            "Monitoring stopped.\n"
            f"Total queries: {self._query_count}\n"
            f"Running time: {hours}h {minutes}m {secs}s"
        )

    @filter.command("rollcall-status")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看签到监控状态。"""
        lines = ["=== XMU Rollcall Status ==="]

        if self._monitoring:
            running_time = int(time.time() - self._start_time)
            hours = running_time // 3600
            minutes = (running_time % 3600) // 60
            secs = running_time % 60

            lines.append(f"Status: RUNNING")
            lines.append(f"Running time: {hours}h {minutes}m {secs}s")
            lines.append(f"Query count: {self._query_count}")

            username = self.config.get("username", "N/A")
            lines.append(f"Account: {username[:3]}***")

            schedule = self._parse_schedule()
            if schedule:
                DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
                lines.append("Schedule:")
                for entry in schedule:
                    days = entry.get("days", [0,1,2,3,4,5,6])
                    start = entry.get("start", entry.get("start_hour", 0))
                    end = entry.get("end", entry.get("end_hour", 23))
                    ds = ",".join(DAY_NAMES[d] for d in days if 0 <= d <= 6)
                    lines.append(f"  {ds} {start:02d}:00-{end:02d}:00")
            else:
                start_h = self.config.get("monitor_start_hour", 0)
                end_h = self.config.get("monitor_end_hour", 23)
                if start_h == end_h:
                    lines.append("Time window: 24/7")
                else:
                    lines.append(f"Time window: {start_h:02d}:00 - {end_h:02d}:00")
            in_window = self._is_in_time_window()
            lines.append(f"In window: {'Yes' if in_window else 'No'}")
        else:
            lines.append("Status: STOPPED")

        yield event.plain_result("\n".join(lines))

    @filter.command("rollcall-config")
    async def cmd_config(self, event: AstrMessageEvent):
        """查看当前配置。"""
        method = self.config.get("number_code_method", 1)
        start_h = self.config.get("monitor_start_hour", 0)
        end_h = self.config.get("monitor_end_hour", 23)
        notify_count = len(self.config.get("notify_chats", []))

        lines = [
            "=== XMU Rollcall Configuration ===",
            f"Username: {self.config.get('username', 'N/A')[:3]}***",
            f"Interval: {self.config.get('interval', 3)}s",
            f"Random delay max: {self.config.get('random_delay_max', 5)}s",
            f"Number code method: {'API' if method == 1 else 'BruteForce (0000-9999)'}",
            f"Auto-start: {'Yes' if self.config.get('enabled', False) else 'No'}",
        ]

        schedule = self._parse_schedule()
        if schedule:
            DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            lines.append("Schedule:")
            for entry in schedule:
                days = entry.get("days", [0,1,2,3,4,5,6])
                start = entry.get("start", entry.get("start_hour", 0))
                end = entry.get("end", entry.get("end_hour", 23))
                ds = ",".join(DAY_NAMES[d] for d in days if 0 <= d <= 6)
                lines.append(f"  {ds} {start:02d}:00-{end:02d}:00")
        else:
            if start_h == end_h:
                lines.append("Time window: 24/7")
            else:
                lines.append(f"Time window: {start_h:02d}:00 - {end_h:02d}:00")

        lines.append(f"Notification targets: {notify_count} configured")
        yield event.plain_result("\n".join(lines))

    @filter.command("rollcall-test")
    async def cmd_test(self, event: AstrMessageEvent):
        """测试登录。"""
        if not self._validate_config():
            yield event.plain_result("ERROR: No credentials configured.")
            return

        yield event.plain_result("Testing login...")

        username = self.config.get("username", "")
        password = self.config.get("password", "")

        session = await asyncio.to_thread(
            xmulogin, type=3, username=username, password=password
        )

        if session:
            profile = await asyncio.to_thread(verify_session, session)
            name = profile.get("name", "unknown") if profile else "unknown"
            yield event.plain_result(f"Login successful! Welcome, {name}.")
        else:
            yield event.plain_result("Login FAILED. Check your credentials.")
