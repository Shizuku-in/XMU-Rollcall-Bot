import time
import random
from verify import send_code, send_code_bruteforce, send_radar

def process_rollcalls(data, session, strategy=None):
    """处理签到数据
    
    Args:
        data: 签到数据
        session: 登录会话
        strategy: 自动化策略配置 dict，包含 random_delay_max, number_code_method
    """
    if strategy is None:
        strategy = {}

    random_delay_max = strategy.get("random_delay_max", 0)
    number_code_method = strategy.get("number_code_method", 1)

    result = handle_rollcalls(data, session, random_delay_max, number_code_method)

    # 如果有任何签到未完成（False），返回空数据以便下次循环继续尝试
    if False in result:
        return {'rollcalls': []}
    else:
        return data

def extract_rollcalls(data):
    """提取签到信息"""
    rollcalls = data['rollcalls']
    result = []
    if rollcalls:
        rollcall_count = len(rollcalls)
        for rollcall in rollcalls:
            result.append({
                'course_title': rollcall['course_title'],
                'created_by_name': rollcall['created_by_name'],
                'department_name': rollcall['department_name'],
                'is_expired': rollcall['is_expired'],
                'is_number': rollcall['is_number'],
                'is_radar': rollcall['is_radar'],
                'rollcall_id': rollcall['rollcall_id'],
                'rollcall_status': rollcall['rollcall_status'],
                'scored': rollcall['scored'],
                'status': rollcall['status'],
                'present_count': rollcall.get('present_count', 0),
            })
    else:
        rollcall_count = 0
    return rollcall_count, result

def handle_rollcalls(data, session, random_delay_max=0, number_code_method=1):
    """处理签到流程

    Args:
        data: 签到数据
        session: 登录会话
        random_delay_max: 随机延迟上限（秒）
        number_code_method: 数字签到方式，1=API，2=暴力破解
    """
    count, rollcalls = extract_rollcalls(data)
    answer_status = [False for _ in range(count)]

    if count:
        print(time.strftime("%H:%M:%S", time.localtime()), f"New rollcall(s) found!\n")
        for i in range(count):
            print(f"{i+1} of {count}:")
            print(f"Course name: {rollcalls[i]['course_title']}, rollcall created by {rollcalls[i]['department_name']} {rollcalls[i]['created_by_name']}.")

            if rollcalls[i]['is_radar']:
                temp_str = "Radar rollcall"
            elif rollcalls[i]['is_number']:
                temp_str = "Number rollcall"
            else:
                temp_str = "QRcode rollcall"
            print(f"Rollcall type: {temp_str}")

            present_count = rollcalls[i].get('present_count', 0)
            print(f"Present count: {present_count} student(s) signed")

            # --- 随机延迟 ---
            if random_delay_max > 0:
                wait_time = random.uniform(0.5, random_delay_max)
                print(f"⏱ Random delay: {wait_time:.1f}s ...")
                time.sleep(wait_time)

            print()

            if rollcalls[i]['status'] == 'on_call_fine':
                print("Already answered.")
                answer_status[i] = True
            elif (rollcalls[i]['status'] == 'absent') and rollcalls[i]['is_number'] and not rollcalls[i]['is_radar']:
                if number_code_method == 2:
                    success = send_code_bruteforce(session, rollcalls[i]['rollcall_id'])
                else:
                    success = send_code(session, rollcalls[i]['rollcall_id'])
                
                if success:
                    answer_status[i] = True
                else:
                    print("Answering failed.")
            elif rollcalls[i]['is_radar']:
                if send_radar(session, rollcalls[i]['rollcall_id']):
                    answer_status[i] = True
                else:
                    print("Answering failed.")
            else:
                # TODO: qrcode rollcall
                print("Answering failed. QRcode rollcall not supported yet.")

    return answer_status
