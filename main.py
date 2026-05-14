import sys
from xmulogin import xmulogin
from config import (
    load_config, save_config, is_config_complete, get_cookies_path,
    add_account, get_all_accounts, get_current_account, set_current_account,
    get_account_by_id, CONFIG_FILE, delete_account, perform_account_deletion
)
from monitor import start_monitor, base_url, headers

__version__ = "3.4.1"

# ANSI Color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    GRAY = '\033[90m'


def print_help():
    print(f"{Colors.OKCYAN}{Colors.BOLD}XMU Rollcall Bot CLI v{__version__}{Colors.ENDC}")
    print(f"\nUsage: python main.py <command>")
    print(f"  config    Configure credentials and add accounts")
    print(f"  switch    Switch between accounts")
    print(f"  start     Start monitoring rollcalls")
    print(f"  refresh   Refresh the login status")
    print(f"  --help    Show this message")


def cmd_config():
    """配置账号：添加、删除账号"""
    print(f"\n{Colors.BOLD}{Colors.OKCYAN}=== XMU Rollcall Configuration ==={Colors.ENDC}\n")

    current_config = load_config()

    def show_accounts():
        """显示账号列表"""
        accounts = get_all_accounts(current_config)
        if accounts:
            print(f"{Colors.BOLD}Existing accounts:{Colors.ENDC}")
            current_account = get_current_account(current_config)
            for acc in accounts:
                current_marker = f" {Colors.OKGREEN}(current){Colors.ENDC}" if current_account and acc.get("id") == current_account.get("id") else ""
                print(f"  {acc.get('id')}: {acc.get('name') or acc.get('username')}{current_marker}")
            print()
        else:
            print(f"{Colors.GRAY}No accounts configured.{Colors.ENDC}\n")

    def add_new_account():
        """添加新账号"""
        print(f"{Colors.BOLD}Adding a new account...{Colors.ENDC}\n")

        # 输入新账号信息
        username = input(f"{Colors.BOLD}Username: {Colors.ENDC}")
        password = input(f"{Colors.BOLD}Password: {Colors.ENDC}")

        # 验证登录
        print(f"\n{Colors.OKCYAN}Validating credentials...{Colors.ENDC}")
        try:
            session = xmulogin(type=3, username=username, password=password)
            if session:
                print(f"{Colors.OKGREEN}✓ Login successful!{Colors.ENDC}")

                # 获取用户姓名
                print(f"{Colors.OKCYAN}Fetching user profile...{Colors.ENDC}")
                try:
                    profile = session.get(f"{base_url}/api/profile", headers=headers).json()
                    name = profile.get("name", "")
                    print(f"{Colors.OKGREEN}✓ Welcome, {name}!{Colors.ENDC}")
                except Exception:
                    print(f"{Colors.WARNING}⚠ Could not fetch profile, using username as name{Colors.ENDC}")
                    name = username

                # 添加账号
                try:
                    account_id = add_account(current_config, username, password, name)
                    save_config(current_config)

                    print(f"{Colors.OKGREEN}✓ Account added successfully! (ID: {account_id}){Colors.ENDC}")
                    print(f"{Colors.GRAY}Configuration file: {CONFIG_FILE}{Colors.ENDC}\n")
                except RuntimeError as e:
                    print(f"{Colors.FAIL}✗ Failed to save configuration: {str(e)}{Colors.ENDC}")
                    print(f"{Colors.WARNING}Tip: In sandboxed environments (like a-Shell), set environment variable:{Colors.ENDC}")
                    print(f"  export XMU_ROLLCALL_CONFIG_DIR=~/Documents/.xmu_rollcall")
            else:
                print(f"{Colors.FAIL}✗ Login failed. Please check your credentials.{Colors.ENDC}")
        except Exception as e:
            print(f"{Colors.FAIL}✗ Error during login validation: {str(e)}{Colors.ENDC}")

    def delete_existing_account():
        """删除账号"""
        accounts = get_all_accounts(current_config)
        if not accounts:
            print(f"{Colors.WARNING}No accounts to delete.{Colors.ENDC}\n")
            return

        show_accounts()

        # 让用户选择要删除的账号
        valid_ids = [str(acc.get("id")) for acc in accounts]
        selected_id = input(f"{Colors.BOLD}Enter account ID to delete ({'/'.join(valid_ids)}): {Colors.ENDC}")

        if selected_id not in valid_ids:
            print(f"{Colors.FAIL}✗ Invalid account ID.{Colors.ENDC}\n")
            return

        selected_id = int(selected_id)
        selected_account = get_account_by_id(current_config, selected_id)

        if selected_account:
            # 确认删除
            confirm = input(
                f"{Colors.WARNING}Are you sure you want to delete account '{selected_account.get('name') or selected_account.get('username')}' (ID: {selected_id})? (y/n, default: n): {Colors.ENDC}"
            )

            if confirm.lower() == 'y':
                # 执行删除
                success, cookies_to_delete, cookies_to_rename = delete_account(current_config, selected_id)

                if success:
                    # 保存配置
                    save_config(current_config)

                    # 处理cookies文件
                    perform_account_deletion(cookies_to_delete, cookies_to_rename)

                    print(f"{Colors.OKGREEN}✓ Account deleted successfully!{Colors.ENDC}")

                    # 显示ID变更提示
                    if cookies_to_rename:
                        print(f"{Colors.GRAY}Note: Account IDs have been re-assigned.{Colors.ENDC}")
                    print()
                else:
                    print(f"{Colors.FAIL}✗ Failed to delete account.{Colors.ENDC}\n")
            else:
                print(f"{Colors.GRAY}Deletion cancelled.{Colors.ENDC}\n")
        else:
            print(f"{Colors.FAIL}✗ Account not found.{Colors.ENDC}\n")

    # 主循环
    while True:
        show_accounts()

        print(f"{Colors.BOLD}Choose an action:{Colors.ENDC}")
        print(f"  {Colors.OKCYAN}n{Colors.ENDC} - Add new account")
        print(f"  {Colors.OKCYAN}d{Colors.ENDC} - Delete account")
        print(f"  {Colors.OKCYAN}q{Colors.ENDC} - Quit")

        action = input(f"\n{Colors.BOLD}Action (n/d/q, default: q): {Colors.ENDC}").strip().lower()

        if not action:
            action = 'q'

        print()

        if action == 'n':
            add_new_account()
        elif action == 'd':
            delete_existing_account()
        elif action == 'q':
            # 退出前显示最终账号列表
            accounts = get_all_accounts(current_config)
            if accounts:
                print(f"{Colors.BOLD}Final account list:{Colors.ENDC}")
                current_account = get_current_account(current_config)
                for acc in accounts:
                    current_marker = f" {Colors.OKGREEN}(current){Colors.ENDC}" if current_account and acc.get("id") == current_account.get("id") else ""
                    print(f"  {acc.get('id')}: {acc.get('name') or acc.get('username')}{current_marker}")
                print(f"\n{Colors.GRAY}You can run: {Colors.BOLD}python main.py switch{Colors.ENDC}{Colors.GRAY} to switch between accounts{Colors.ENDC}")
                print(f"{Colors.GRAY}You can run: {Colors.BOLD}python main.py start{Colors.ENDC}{Colors.GRAY} to start monitoring{Colors.ENDC}")
            break
        else:
            print(f"{Colors.WARNING}Invalid action. Please choose n, d, or q.{Colors.ENDC}\n")


def cmd_start():
    """启动签到监控"""
    # 加载配置
    config_data = load_config()

    # 检查配置是否完整
    if not is_config_complete(config_data):
        print(f"{Colors.FAIL}✗ Configuration incomplete!{Colors.ENDC}")
        print(f"Please run: {Colors.BOLD}python main.py config{Colors.ENDC}")
        sys.exit(1)

    # 获取当前账号
    current_account = get_current_account(config_data)
    print(f"{Colors.OKCYAN}Using account: {current_account.get('name') or current_account.get('username')} (ID: {current_account.get('id')}){Colors.ENDC}")

    # 启动监控
    try:
        start_monitor(current_account)
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Shutting down...{Colors.ENDC}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.FAIL}Error: {str(e)}{Colors.ENDC}")
        sys.exit(1)


def cmd_refresh():
    """清除当前账号的登录缓存"""
    config_data = load_config()
    current_account = get_current_account(config_data)

    if not current_account:
        print(f"{Colors.FAIL}✗ No account configured!{Colors.ENDC}")
        print(f"Please run: {Colors.BOLD}python main.py config{Colors.ENDC}")
        sys.exit(1)

    account_id = current_account.get("id")
    cookies_path = get_cookies_path(account_id)
    try:
        print(f"\n{Colors.WARNING}Deleting cookies for account {account_id} ({current_account.get('name')})...{Colors.ENDC}")
        # delete cookies file
        import os
        if os.path.exists(cookies_path):
            os.remove(cookies_path)
            print(f"{Colors.OKGREEN}✓ Cookies deleted successfully.{Colors.ENDC}")
        else:
            print(f"{Colors.GRAY}No cookies file found to delete.{Colors.ENDC}")
        sys.exit(0)
    except Exception as e:
        print(f"{Colors.FAIL}✗ Failed to delete cookies: {str(e)}{Colors.ENDC}")
        sys.exit(1)


def cmd_switch():
    """切换当前使用的账号"""
    print(f"\n{Colors.BOLD}{Colors.OKCYAN}=== Switch Account ==={Colors.ENDC}\n")

    config_data = load_config()
    accounts = get_all_accounts(config_data)

    if not accounts:
        print(f"{Colors.FAIL}✗ No accounts configured!{Colors.ENDC}")
        print(f"Please run: {Colors.BOLD}python main.py config{Colors.ENDC}")
        sys.exit(1)

    current_account = get_current_account(config_data)
    current_id = current_account.get("id") if current_account else None

    # 显示账号列表
    print(f"{Colors.BOLD}Available accounts:{Colors.ENDC}")
    for acc in accounts:
        current_marker = f" {Colors.OKGREEN}(current){Colors.ENDC}" if acc.get("id") == current_id else ""
        print(f"  {acc.get('id')}: {acc.get('name') or acc.get('username')}{current_marker}")

    print()

    # 让用户选择账号
    valid_ids = [str(acc.get("id")) for acc in accounts]
    selected_id = input(f"{Colors.BOLD}Enter account ID to switch to ({'/'.join(valid_ids)}): {Colors.ENDC}")

    if selected_id not in valid_ids:
        print(f"{Colors.FAIL}✗ Invalid account ID!{Colors.ENDC}")
        sys.exit(1)

    selected_id = int(selected_id)
    selected_account = get_account_by_id(config_data, selected_id)

    if selected_account:
        set_current_account(config_data, selected_id)
        save_config(config_data)
        print(f"\n{Colors.OKGREEN}✓ Switched to account: {selected_account.get('name') or selected_account.get('username')} (ID: {selected_id}){Colors.ENDC}")
        print(f"{Colors.GRAY}You can now run: {Colors.BOLD}python main.py start{Colors.ENDC}")
    else:
        print(f"{Colors.FAIL}✗ Account not found!{Colors.ENDC}")
        sys.exit(1)


def main():
    args = sys.argv[1:]

    if not args or args[0] in ('--help', '-h', 'help'):
        print_help()
        return

    command = args[0].lower()

    if command == 'config':
        cmd_config()
    elif command == 'start':
        cmd_start()
    elif command == 'refresh':
        cmd_refresh()
    elif command == 'switch':
        cmd_switch()
    else:
        print(f"{Colors.FAIL}Unknown command: {args[0]}{Colors.ENDC}")
        print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
