import time
import os
import sys
import requests
import shutil
import re
import concurrent.futures
from xmulogin import xmulogin
from utils import clear_screen, save_session, load_session, verify_session
from rollcall_handler import process_rollcalls
from config import get_cookies_path, get_strategy

__version__ = "3.5.0"

base_url = "https://lnt.xmu.edu.cn"

# 重连/退避常量
BACKOFF_BASE = 5       # 初始退避秒数
BACKOFF_MAX = 60       # 最大退避秒数
REAUTH_THRESHOLD = 3   # 连续失败多少次后尝试重新登录
REAUTH_COOLDOWN = 60   # reauth 失败后的冷却秒数，防止轰炸认证服务器
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://ids.xmu.edu.cn/authserver/login",
}

# ANSI Color codes
class Colors:
    __slots__ = ()
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    GRAY = '\033[90m'
    WHITE = '\033[97m'
    BG_BLUE = '\033[44m'
    BG_GREEN = '\033[42m'
    BG_CYAN = '\033[46m'

BOLD_LABEL = f"{Colors.BOLD}"
CYAN_TEXT = f"{Colors.OKCYAN}"
GREEN_TEXT = f"{Colors.OKGREEN}"
YELLOW_TEXT = f"{Colors.WARNING}"
END = Colors.ENDC


class MonitorStartupError(RuntimeError):
    """Raised when monitoring cannot be initialized and should be retried."""

def get_terminal_width():
    """获取终端宽度"""
    try:
        return shutil.get_terminal_size().columns
    except OSError:
        return 80

_ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi(text):
    """移除ANSI颜色代码以计算实际文本长度"""
    return _ANSI_ESCAPE.sub('', text)

def center_text(text, width=None):
    """居中文本"""
    if width is None:
        width = get_terminal_width()
    text_len = len(strip_ansi(text))
    if text_len >= width:
        return text
    left_padding = (width - text_len) // 2
    return ' ' * left_padding + text

def print_banner(strategy=None):
    """打印美化的横幅"""
    width = get_terminal_width()
    line = '=' * width

    title1 = "XMU Rollcall Bot CLI"
    title2 = f"Version {__version__}"

    print(f"{Colors.OKCYAN}{line}{Colors.ENDC}")
    print(center_text(f"{Colors.BOLD}{title1}{Colors.ENDC}"))
    print(center_text(f"{Colors.GRAY}{title2}{Colors.ENDC}"))
    if strategy:
        interval = strategy.get('interval', 3)
        delay = strategy.get('random_delay_max', 0)
        method = strategy.get('number_code_method', 1)
        info = f"Interval: {interval}s | Delay: {delay}s | Num Method: {method}"
        print(center_text(f"{Colors.GRAY}{info}{Colors.ENDC}"))
    print(f"{Colors.OKCYAN}{line}{Colors.ENDC}")

def print_separator(char="-"):
    """打印分隔线"""
    width = get_terminal_width()
    print(f"{Colors.GRAY}{char * width}{Colors.ENDC}")

def format_time(seconds):
    """格式化时间显示"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

_COLOR_PALETTE = (
    Colors.FAIL,
    Colors.WARNING,
    Colors.OKGREEN,
    Colors.OKCYAN,
    Colors.OKBLUE,
    Colors.HEADER
)
_COLOR_COUNT = len(_COLOR_PALETTE)

def get_colorful_text(text, color_offset=0):
    """为文本的每个字符应用不同的颜色"""
    return ''.join(
        _COLOR_PALETTE[(i + color_offset) % _COLOR_COUNT] + char
        for i, char in enumerate(text)
    ) + Colors.ENDC

def print_footer_text(color_offset=0):
    """打印底部彩色文字"""
    text = "XMU-Rollcall-Bot @ KrsMt & gkouen"
    colored = get_colorful_text(text, color_offset)
    print(center_text(colored))

def print_dashboard(name, start_time, query_count, strategy=None, banner_frame=0, show_banner=True):
    """打印主仪表板"""
    clear_screen()
    print_banner(strategy)

    local_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    interval = strategy.get('interval', 3) if strategy else 3

    if time.localtime().tm_hour < 12 and time.localtime().tm_hour >= 5:
        greeting = "Good morning"
    elif time.localtime().tm_hour < 18 and time.localtime().tm_hour >= 12:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    now = time.time()
    running_time = int(now - start_time)

    print(f"\n{Colors.OKGREEN}{Colors.BOLD}{greeting}, {name}!{Colors.ENDC}\n")

    print(f"{Colors.BOLD}SYSTEM STATUS{Colors.ENDC}")
    print_separator()
    print(f"{Colors.BOLD}Current Time:{Colors.ENDC}    {Colors.OKCYAN}{local_time}{Colors.ENDC}")
    print(f"{Colors.BOLD}Running Time:{Colors.ENDC}    {Colors.OKGREEN}{format_time(running_time)}{Colors.ENDC}")
    print(f"{Colors.BOLD}Query Count:{Colors.ENDC}     {Colors.WARNING}{query_count}{Colors.ENDC}")

    print(f"\n{Colors.BOLD}ROLLCALL MONITOR{Colors.ENDC}")
    print_separator()
    print(f"{Colors.OKGREEN}Status:{Colors.ENDC} Active - Monitoring for new rollcalls...")
    print(f"{Colors.GRAY}Checking every {interval} second(s){Colors.ENDC}")
    print(f"{Colors.GRAY}Press Ctrl+C to exit{Colors.ENDC}\n")
    print_separator()

    if show_banner:
        print()
        print_footer_text(banner_frame)

def print_login_status(message, is_success=True):
    """打印登录状态"""
    if is_success:
        print(f"{Colors.OKGREEN}[SUCCESS]{Colors.ENDC} {message}")
    else:
        print(f"{Colors.FAIL}[FAILED]{Colors.ENDC} {message}")

def try_reauth(session, username, password, cookies_path):
    """尝试重新登录以恢复 session

    Args:
        session: 当前的 requests.Session 对象
        username: 登录用户名
        password: 登录密码
        cookies_path: cookies 文件路径

    Returns:
        新的 session 对象（成功时），或 None（失败时）
    """
    print(f"{Colors.WARNING}[REAUTH] Session may have expired, attempting re-login...{Colors.ENDC}")
    new_session = xmulogin(type=3, username=username, password=password)
    if new_session:
        save_session(new_session, cookies_path)
        print(f"{Colors.OKGREEN}[REAUTH] Re-login successful{Colors.ENDC}")
        return new_session
    else:
        print(f"{Colors.FAIL}[REAUTH] Re-login failed{Colors.ENDC}")
        return None

TIME_LINE = 11
RUNTIME_LINE = 12
QUERY_LINE = 13
FOOTER_LINE = 22

def update_status_line(line_num, label, value, color):
    """更新指定行的状态信息，不清屏"""
    sys.stdout.write("\033[?25l")
    sys.stdout.write("\033[s")
    sys.stdout.write(f"\033[{line_num};0H")
    sys.stdout.write("\033[2K")
    sys.stdout.write(f"{Colors.BOLD}{label}{Colors.ENDC}    {color}{value}{Colors.ENDC}")
    sys.stdout.write("\033[u")
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()

def update_footer_text():
    """更新底部彩色文字，不清屏"""
    text = "XMU-Rollcall-Bot @ KrsMt & gkouen"
    colored = get_colorful_text(text, 0)
    width = get_terminal_width()

    sys.stdout.write("\033[?25l")
    sys.stdout.write("\033[s")
    sys.stdout.write(f"\033[{FOOTER_LINE};0H")
    sys.stdout.write("\033[2K")

    text_len = len(text)
    left_padding = (width - text_len) // 2
    sys.stdout.write(' ' * left_padding + colored)

    sys.stdout.write("\033[u")
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()

def start_monitor(account, strategy=None):
    """启动监控程序"""
    USERNAME = account['username']
    PASSWORD = account['password']
    ACCOUNT_ID = account.get('id', 1)
    ACCOUNT_NAME = account.get('name', '')

    if strategy is None:
        strategy = {}

    interval = strategy.get('interval', 3)

    cookies_path = get_cookies_path(ACCOUNT_ID)
    rollcalls_url = f"{base_url}/api/radar/rollcalls"
    session = None

    # 初始化
    clear_screen()
    print_banner(strategy)
    print(f"\n{Colors.BOLD}Initializing XMU Rollcall Bot...{Colors.ENDC}\n")
    print_separator()

    print(f"\n{Colors.OKCYAN}[Step 1/3]{Colors.ENDC} Checking credentials...")

    if os.path.exists(cookies_path):
        print(f"{Colors.OKCYAN}[Step 2/3]{Colors.ENDC} Found cached session, attempting to restore...")
        session_candidate = requests.Session()
        if load_session(session_candidate, cookies_path):
            profile = verify_session(session_candidate)
            if profile:
                session = session_candidate
                print_login_status("Session restored successfully", True)
            else:
                print_login_status("Session expired, will re-login", False)
        else:
            print_login_status("Failed to load session", False)

    if not session:
        print(f"{Colors.OKCYAN}[Step 2/3]{Colors.ENDC} Logging in with credentials...")
        time.sleep(2)
        session = xmulogin(type=3, username=USERNAME, password=PASSWORD)
        if session:
            save_session(session, cookies_path)
            print_login_status("Login successful", True)
        else:
            print_login_status("Login unavailable. The credentials or authentication service may be unavailable", False)
            raise MonitorStartupError("Unable to log in to the teaching platform")

    print(f"{Colors.OKCYAN}[Step 3/3]{Colors.ENDC} Fetching user profile...")
    print_login_status(f"Welcome, {ACCOUNT_NAME}", True)

    print(f"\n{Colors.OKGREEN}{Colors.BOLD}Initialization complete{Colors.ENDC}")
    print(f"\n{Colors.GRAY}Starting monitor in 3 seconds...{Colors.ENDC}")
    time.sleep(3)

    # 主循环
    temp_data = {'rollcalls': []}
    query_count = 0
    start_time = time.time()
    consecutive_errors = 0
    last_reauth_time = 0  # 上次尝试 reauth 的时间戳

    print_dashboard(ACCOUNT_NAME, start_time, query_count, strategy, 0, show_banner=False)

    footer_initialized = False
    _next_query_time = time.time()
    
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    current_future = None

    try:
        while True:
            try:
                time.sleep(0.1)
            except KeyboardInterrupt:
                raise

            try:
                current_time = time.time()

                if not footer_initialized:
                    footer_initialized = True
                    update_footer_text()

                elapsed = int(current_time - start_time)
                local_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                running_time = format_time(elapsed)

                update_status_line(TIME_LINE, "Current Time:", local_time, Colors.OKCYAN)
                update_status_line(RUNTIME_LINE, "Running Time:", running_time, Colors.OKGREEN)

                if current_time >= _next_query_time and current_future is None:
                    _next_query_time = current_time + interval
                    current_future = executor.submit(session.get, rollcalls_url, headers=headers, timeout=10)
                    
                if current_future and current_future.done():
                    data_success = False
                    error_msg = None
                    auth_failed = False
                    try:
                        res = current_future.result()
                        # 检测 HTTP 认证失败（401/403）
                        if res.status_code in (401, 403):
                            auth_failed = True
                            error_msg = f"HTTP {res.status_code}"
                        else:
                            data = res.json()
                            data_success = True
                            query_count += 1
                    except Exception as e:
                        error_msg = type(e).__name__

                    current_future = None

                    # 成功时重置连续错误计数
                    if data_success:
                        consecutive_errors = 0
                    else:
                        consecutive_errors += 1

                    query_display = str(query_count)
                    if error_msg:
                        query_display += f"    {Colors.FAIL}[Error: {error_msg}]{Colors.ENDC}"

                    update_status_line(QUERY_LINE, "Query Count: ", query_display, Colors.WARNING)

                    # HTTP 401/403 或连续失败达到阈值时，尝试重新登录（受冷却保护）
                    if (auth_failed or consecutive_errors >= REAUTH_THRESHOLD) and consecutive_errors > 0:
                        now = time.time()
                        if now - last_reauth_time >= REAUTH_COOLDOWN:
                            last_reauth_time = now
                            new_session = try_reauth(session, USERNAME, PASSWORD, cookies_path)
                            if new_session:
                                session = new_session
                                consecutive_errors = 0

                    if data_success and temp_data != data:
                        temp_data = data
                        if len(temp_data['rollcalls']) > 0:
                            clear_screen()
                            width = get_terminal_width()
                            print(f"\n{Colors.WARNING}{Colors.BOLD}{'!' * width}{Colors.ENDC}")
                            print(center_text(f"{Colors.WARNING}{Colors.BOLD}NEW ROLLCALL DETECTED{Colors.ENDC}"))
                            print(f"{Colors.WARNING}{Colors.BOLD}{'!' * width}{Colors.ENDC}\n")
                            temp_data = process_rollcalls(temp_data, session, strategy)
                            print_separator("=")
                            print(f"\n{center_text(f'{Colors.GRAY}Press Ctrl+C to exit, continuing monitor...{Colors.ENDC}')}\n")
                            try:
                                time.sleep(3)
                            except KeyboardInterrupt:
                                raise
                            print_dashboard(ACCOUNT_NAME, start_time, query_count, strategy, 0)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                consecutive_errors += 1
                # 指数退避：5s, 10s, 20s, 40s, 60s, 60s, ...
                backoff = min(BACKOFF_BASE * (2 ** (consecutive_errors - 1)), BACKOFF_MAX)
                clear_screen()
                print(f"\n{center_text(f'{Colors.FAIL}{Colors.BOLD}Error occurred:{Colors.ENDC} {str(e)}')}")
                print(f"{center_text(f'{Colors.WARNING}Retrying in {backoff}s... (attempt {consecutive_errors}){Colors.ENDC}')}\n")

                # 连续失败达到阈值时，尝试重新登录（受冷却保护）
                if consecutive_errors >= REAUTH_THRESHOLD:
                    now = time.time()
                    if now - last_reauth_time >= REAUTH_COOLDOWN:
                        last_reauth_time = now
                        new_session = try_reauth(session, USERNAME, PASSWORD, cookies_path)
                        if new_session:
                            session = new_session
                            consecutive_errors = 0

                time.sleep(backoff)
                print_dashboard(ACCOUNT_NAME, start_time, query_count, strategy, 0, show_banner=False)
                _next_query_time = time.time() + interval
    except KeyboardInterrupt:
        clear_screen()
        print(f"\n{center_text(f'{Colors.WARNING}Shutting down gracefully...{Colors.ENDC}')}")
        print(f"{center_text(f'{Colors.GRAY}Total queries performed: {query_count}{Colors.ENDC}')}")
        print(f"{center_text(f'{Colors.GRAY}Total running time: {format_time(int(time.time() - start_time))}{Colors.ENDC}')}")
        print(f"\n{center_text(f'{Colors.OKGREEN}Goodbye{Colors.ENDC}')}\n")
        return
    finally:
        executor.shutdown(wait=False)
