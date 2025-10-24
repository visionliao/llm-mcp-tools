import uvicorn
from typing import List, Union, Optional, Any
import datetime
import re
import threading
import time
# 导入 FastMCP 框架
# from mcp.server.fastmcp import FastMCP  # 这是MCP官方Inspector 方式，主要用来调试
from fastmcp import FastMCP

'''
如果使用mcp.server.fastmcp，可以通过 pip install mcp[cli] 这个官方工具，进行本地浏览器调试。
    1. 使用from mcp.server.fastmcp import FastMCP
    2. 必须安装mcp[cli]工具，可使用pip install mcp[cli] 来进行安装
    3. 运行服务器，python main.py
    4. 运行mcp[cli] mcp dev main.py
    好处是开发MCP服务端的人员不用关注客户端的实现，只要专注开发服务端的功能即可，因为通过这个浏览器调试界面可以调试任何服务端的问题。
'''


from services.calculate_occupancy import calculate_occupancy_rate, format_result_to_string
from services.room import analyze_room_type_performance, format_analysis_to_string
from services.query_checkins import query_checkin_records, format_records_to_string
from services.query_by_room import query_records_by_room, format_string as format_room_query_string
from services.query_orders import search_by_rmno, format_results_string
from services.advanced_query import search_orders_advanced, format_to_string
from services.data_loader import get_lease_service_orders
from services.data_loader import get_master_guest_df
from services.query_guest_data import get_query_result_as_string
from services.data_loader import get_master_base_df
from services.constants import (
    ROOM_TYPE_COUNTS, ROOM_TYPE_AREAS, ROOM_TYPE_NAMES,
    SERVICE_CODE_MAP, LOCATION_CODE_MAP
)

# 全局初始化状态管理
server_initialized = False
initialization_lock = threading.Lock()
initialization_error = None

def check_initialization():
    """检查服务器是否已完成初始化"""
    global server_initialized, initialization_error

    if server_initialized:
        if initialization_error:
            return False, f"服务器初始化失败: {initialization_error}"
        return True, "服务器已就绪"

    return False, "服务器初始化中，请稍后重试..."

def initialize_server_data():
    """预加载所有数据文件以确保服务器完全初始化"""
    global server_initialized, initialization_error

    try:
        with initialization_lock:
            if server_initialized:
                return

            print("--- 开始服务器数据预加载 ---")

            # 预加载所有数据文件
            from services.data_loader import get_master_base_df, get_master_guest_df, get_lease_service_orders

            # 加载master_base.xml
            print("正在加载 master_base.xml...")
            master_base_df = get_master_base_df()
            if master_base_df is None:
                raise Exception("master_base.xml 加载失败")
            print(f"✓ master_base.xml 加载成功，共 {len(master_base_df)} 条记录")

            # 加载master_guest.xml
            print("正在加载 master_guest.xml...")
            master_guest_df = get_master_guest_df()
            if master_guest_df is None:
                raise Exception("master_guest.xml 加载失败")
            print(f"✓ master_guest.xml 加载成功，共 {len(master_guest_df)} 条记录")

            # 加载lease_service_order.xml
            print("正在加载 lease_service_order.xml...")
            service_orders = get_lease_service_orders()
            if service_orders is None:
                raise Exception("lease_service_order.xml 加载失败")
            print(f"✓ lease_service_order.xml 加载成功，共 {len(service_orders)} 条记录")

            server_initialized = True
            initialization_error = None
            print("--- 服务器数据预加载完成 ---")

    except Exception as e:
        initialization_error = str(e)
        server_initialized = True  # 标记为已初始化，但有错误
        print(f"--- 服务器初始化失败: {e} ---")

# 初始化 FastMCP 应用 ---
mcp = FastMCP(name="公寓数据查询工具集 (FastMCP v1.0)", host="0.0.0.0", port=8001)

# --- 1. 查询现在的系统时间 ---
@mcp.tool()
def get_current_time(format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    获取当前的系统日期和时间。
    - format_str (str): 可选参数，用于指定返回时间的格式，默认为 '%Y-%m-%d %H:%M:%S'。
    """
    # 检查服务器初始化状态
    is_ready, message = check_initialization()
    if not is_ready:
        return message
    return datetime.datetime.now().strftime(format_str)


# --- 2. 通用计算工具函数 ---
@mcp.tool()
def calculate_expression(expression: str) -> Any:
    """
    执行一个字符串形式的基础数学表达式。
    支持加、减、乘、除、幂（**）和括号运算。仅限于安全的基础数学计算。
    - expression (str): 需要计算的数学表达式，例如 "10 * (5 + 3)"。
    """
    try:
        # 限制`eval`的上下文，只允许基础的数学计算
        # 创建一个只包含安全函数的字典
        allowed_names = {
            'abs': abs, 'max': max, 'min': min, 'pow': pow, 'round': round,
            # 可以根据需要添加更多安全的数学函数
        }
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return result
    except (SyntaxError, NameError, TypeError, ZeroDivisionError) as e:
        return f"计算错误: {e}"

@mcp.tool()
def calculate_occupancy(start: str, end: str, details: str):
    """
    计算指定日期范围内的总体入住率和出租率。
    返回一个包含总体统计数据的摘要，如总可用房晚、实际入住房晚和最终的出租率百分比。
    - start (str): 开始日期，格式为 'YYYY-MM-DD'。
    - end (str): 结束日期，格式为 'YYYY-MM-DD'。
    - details (str): 是否返回每日明细。传入 'y' 获取每日详情，传入 'n' 只获取总体摘要。
    【提示】: 此工具用于获取高层级的总体数据。如需按房型分析详细的经营表现，请使用 'occupancy_details' 工具。
    """
    # 检查服务器初始化状态
    is_ready, message = check_initialization()
    if not is_ready:
        return message

    TOTAL_ROOMS = 579

    print("--- 入住率计算 ---")

    start_input = start
    end_input = end
    details_input = details.lower()

    show_details_flag = True if details_input == 'y' else False

    # 函数现在返回两个值：一个字典（数据）和一个字符串（日志）
    result_dict, details_string = calculate_occupancy_rate(
        start_input, end_input, TOTAL_ROOMS, show_details=show_details_flag
    )

    # 检查是否有错误发生
    if result_dict is None:
        # 如果出错，details_string 会包含错误信息
        return details_string
    else:
        # --- 将所有输出格式化并存入一个字符串变量 ---
        final_report_string = format_result_to_string(result_dict, details_string)

        return final_report_string

@mcp.tool()
def occupancy_details(start_time: str, end_time: str) -> str:
    """
    获取指定日期范围内，按房型分类的详细经营业绩分析。
    对于每种房型，返回关键指标，如坪效、空置率、总租金、平均日租金，以及最高和最低租金的合同信息。
    - start_time (str): 开始日期，格式为 'YYYY-MM-DD'。
    - end_time (str): 结束日期，格式为 'YYYY-MM-DD'。
    【提示】: 此工具用于深入分析不同房型的表现。如只需查询总体的出租率，请使用 'calculate_occupancy' 工具。
    """
    # 检查服务器初始化状态
    is_ready, message = check_initialization()
    if not is_ready:
        return message

    print("--- 户型经营表现分析工具 ---")

    start_date_input = start_time
    end_date_input = end_time

    # 1. 调用计算函数，获取原始数据结果
    results_list = analyze_room_type_performance(
        start_date_input,
        end_date_input,
        ROOM_TYPE_COUNTS,
        ROOM_TYPE_AREAS
    )

    if not isinstance(results_list, list):
        # 假设如果出错，返回的是一个包含错误信息的字符串
        return str(results_list)

    # 2. 调用格式化函数，将结果存入字符串变量
    final_report_string = format_analysis_to_string(
        results_list,
        start_date_input,
        end_date_input,
        ROOM_TYPE_NAMES
    )

    # 3. 打印字符串变量
    return final_report_string

@mcp.tool()
def query_guest(id: str):
    """
    根据用户ID查询并返回该用户的详细个人资料信息。
    返回信息包括姓名、联系方式、国籍和证件号码等。
    - id (str): 用户的唯一数字ID。此ID可从 'occupancy_details' 等工具的返回结果中获得。
    """
    # 检查服务器初始化状态
    is_ready, message = check_initialization()
    if not is_ready:
        return message

    # 1. 从缓存中获取已处理好的DataFrame
    guest_df = get_master_guest_df()

    if guest_df is None:
        return "错误：客户数据服务当前不可用，请检查服务日志。"
    
    # 2. 验证输入ID并转换为整数
    try:
        query_id = int(id)
    except (ValueError, TypeError):
        return f"输入错误：ID '{id}' 不是一个有效的数字ID。"
        
    # 3. 调用纯业务逻辑函数，传入数据和查询ID
    return get_query_result_as_string(guest_df, query_id)

@mcp.tool()
def query_checkins(start: str, end: str, choice: str='ALL'):
    """
    查询指定日期范围和状态下的入住记录。
    返回一个列表，包含每条记录的入住/离店日期、房号、房型、租金、状态和用户ID等信息。
    - start (str): 开始日期，格式为 'YYYY-MM-DD'。
    - end (str): 结束日期，格式为 'YYYY-MM-DD'。
    - choice (str): 查询的状态。'1'代表在住(I), '2'代表结账(O), '3'代表取消(X), '4'代表预订(R), '5'代表所有状态(ALL)。
    """
    # 检查服务器初始化状态
    is_ready, message = check_initialization()
    if not is_ready:
        return message

    # 1. 从缓存加载数据
    master_df = get_master_base_df()
    if master_df is None:
        return "错误：核心入住数据服务当前不可用，请检查服务日志。"

    # 2. 准备参数
    status_map = {'1': 'I', '2': 'O', '3': 'X', '4': 'R', '5': 'ALL'}
    selected_status = status_map.get(choice, 'ALL')

    # 3. 调用纯业务逻辑函数
    found_records = query_checkin_records(master_df, start, end, status_filter=selected_status)

    # 4. 调用格式化函数（它能处理错误字符串或DataFrame）
    #    从中央常量文件传入 ROOM_TYPE_NAMES
    return format_records_to_string(found_records, start, end, ROOM_TYPE_NAMES, status_filter=selected_status)

@mcp.tool()
def query_by_room(rooms: Union[str, List[str]]):
    """
    根据一个或多个房间号查询相关的入住历史记录。
    返回这些房间的所有相关记录，包括入住/离店日期、租金、状态和用户ID等。
    - rooms (Union[str, List[str]]): 单个房间号（如 "A312"）或一个房间号列表（如 ["A312", "B1510"]）。
    """
    # 检查服务器初始化状态
    is_ready, message = check_initialization()
    if not is_ready:
        return message

    # 1. 解析输入参数 (这是工具层的职责)
    final_room_list: List[str] = []
    if isinstance(rooms, list):
        final_room_list = [str(item).strip().upper() for item in rooms if str(item).strip()]
    elif isinstance(rooms, str):
        final_room_list = [r.strip().upper() for r in re.split(r'[\s,]+', rooms) if r.strip()]

    if not final_room_list:
        return "输入错误：未能从输入中解析出有效的房间号。"

    # 2. 从缓存加载数据
    master_df = get_master_base_df()
    if master_df is None:
        return "错误：核心入住数据服务当前不可用，请检查服务日志。"

    # 3. 调用纯业务逻辑函数
    found_records = query_records_by_room(master_df, final_room_list)

    # 4. 调用格式化函数
    #    从中央常量文件传入 ROOM_TYPE_NAMES
    return format_room_query_string(
        found_records,
        final_room_list,
        ROOM_TYPE_NAMES
    )

@mcp.tool()
def query_orders(room: str):
    """
    根据房间号查询该房间的所有历史服务工单。
    返回一个工单列表，包含工单ID、服务项目、需求描述、状态和处理结果等信息。
    - room (str): 需要查询的房间号。
    """
    # 检查服务器初始化状态
    is_ready, message = check_initialization()
    if not is_ready:
        return message

    # 1. 从缓存加载所有工单数据
    all_orders = get_lease_service_orders() # 此函数已在data_loader中定义
    if all_orders is None:
        return "错误：工单数据服务当前不可用，请检查服务日志。"

    # 2. 调用纯业务逻辑函数进行筛选
    found_orders = search_by_rmno(all_orders, room)

    # 3. 调用格式化函数
    return format_results_string(found_orders)

@mcp.tool()
def advanced_query_service(
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
    service_code: Optional[str] = None,
    location_code: Optional[str] = None
) -> str:
    """
    根据多个条件（时间范围、服务项目代码、位置代码）高级搜索历史服务工单。
    这是一个功能更强大的工单搜索工具，适用于复杂的筛选场景。
    - start_date_str (str, optional): 开始日期, 格式 'YYYY-MM-DD'。
    - end_date_str (str, optional): 结束日期, 格式 'YYYY-MM-DD'。
    - service_code (str, optional): 服务项目代码, 例如 'B501' 代表电源插座。
    - location_code (str, optional): 具体位置代码, 例如 '004' 代表厨房。
    【提示】: 如果只是根据房间号查询工单，使用 'query_orders' 工具更简单。
    """
    # 检查服务器初始化状态
    is_ready, message = check_initialization()
    if not is_ready:
        return message

    all_orders_data = get_lease_service_orders()
    if all_orders_data is None:
        return "错误: 无法加载工单数据，请检查服务日志。"

    # --- 处理和验证输入 ---
    try:
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    except ValueError:
        return "输入错误：日期格式不正确，请使用 'YYYY-MM-DD' 格式。"

    # --- 执行查询并格式化结果 ---
    found_orders = search_orders_advanced(all_orders_data, start_date, end_date, service_code, location_code)

    service_desc = SERVICE_CODE_MAP.get(service_code, '不限') if service_code is not None else '不限'
    location_desc = LOCATION_CODE_MAP.get(location_code, '不限') if location_code is not None else '不限'
    # 构建查询条件描述字符串
    criteria_desc = (
        f"时间范围: [{start_date_str or '不限'} 至 {end_date_str or '不限'}], "
        f"服务项目: [{service_desc}], "
        f"具体位置: [{location_desc}]"
    )

    return format_to_string(found_orders, criteria_desc)

if __name__ == "__main__":
    print(f"Starting native FastMCP server on http://{mcp.settings.host}:{mcp.settings.port}")

    # 在后台线程中启动数据初始化
    import threading
    init_thread = threading.Thread(target=initialize_server_data, daemon=True)
    init_thread.start()

    # 根据源代码，'streamable-http' 是用于通用HTTP交互的模式
    mcp.run(transport="sse")