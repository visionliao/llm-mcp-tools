import uvicorn
from typing import List, Union, Optional, Any
import datetime
import re
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

# 初始化 FastMCP 应用 ---
mcp = FastMCP(name="公寓数据查询工具集 (FastMCP v1.0)", host="0.0.0.0", port=8001)

# --- 1. 查询现在的系统时间 ---
@mcp.tool()
def get_current_time(format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    获取当前系统时间，并按照 年-月-日 时:分:秒 的格式返回。
    """
    return datetime.datetime.now().strftime(format_str)


# --- 2. 通用计算工具函数 ---
@mcp.tool()
def calculate_expression(expression: str) -> Any:
    """
    工具名称 (tool_name): calculate_expression
    功能描述 (description): 用于执行一个字符串形式的数学计算。适用于需要进行加、减、乘、除、括号等运算的场景。
    【重要提示】: 此工具仅限于基础数学运算 (+, -, *, /, **) 和几个安全函数 (abs, max, min, pow, round)。它无法执行更复杂的代数或微积分运算。
    输入参数 (parameters):
    name: expression
    type: string
    description: 需要被计算的数学表达式。例如: "10 * (5 + 3)"。
    required: true (必需)
    返回结果 (returns):
    type: number | string
    description: 返回计算结果（数字类型）。如果表达式语法错误或计算出错（如除以零），则返回一个描述错误的字符串。
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
    功能描述 (description): 一个用于获取指定时间内的入住率以及出租率的工具

    输入参数 (parameters):
    start (Optional[str]): 时间区间起点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'
    end (Optional[str]): 时间区间终点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'
    details (Optional[str]): 选择是否获取详细的记录，可选值为'y'/'n'，默认为 'n'


    返回结果 (returns):
    下面是一个调用返回示例：
    print(calculate_occupancy("2025-08-01", "2025-08-05", "y"))
    返回：
    '
    --- 每日入住与预定详情 ---
    日期: 2025-08-01 | 在住房间数: 150 | 预定房间数: 0   | 出租情况 Roomnights occ: 25.91% Application occ: 25.91%
    日期: 2025-08-02 | 在住房间数: 151 | 预定房间数: 0   | 出租情况 Roomnights occ: 26.08% Application occ: 26.08%
    日期: 2025-08-03 | 在住房间数: 151 | 预定房间数: 0   | 出租情况 Roomnights occ: 26.08% Application occ: 26.08%
    日期: 2025-08-04 | 在住房间数: 154 | 预定房间数: 0   | 出租情况 Roomnights occ: 26.60% Application occ: 26.60%
    日期: 2025-08-05 | 在住房间数: 155 | 预定房间数: 0   | 出租情况 Roomnights occ: 26.77% Application occ: 26.77%

    --- 计算结果 ---
    查询范围: 2025-08-01 到 2025-08-05 (5 天)
    总可用房晚数: 2,895
    实际入住房晚数: 761
    预定房晚数: 0
    ------------------
    --- 出租情况 ---
    Roomnights occ (不包含签约但未入住): 26.29%
    Application occ (包含签约但未入住): 26.29%
    ------------------
    '
    """

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
        功能描述 (description): 一个用于获取指定时间段内的不同房型型的出租情况（租金，坪效，空置率）的工具，同时还可获得不同房型的最高租金与最低租金，以及对应的用户ID

        输入参数 (parameters):
        start_time (Optional[str]): 时间区间起点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'
        end_time (Optional[str]): 时间区间终点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'

        返回结果 (returns):
        下面是一个调用返回示例：
        print(occupancy_details("2025-08-01", "2025-08-31"))
        返回：
        '
        --- 户型经营表现分析工具 ---
        --- 各户型经营表现分析 (数据范围: 2025-08-01 至 2025-08-31) ---

        ==================== 户型: 一房豪华式公寓 ====================
        期末供应与占用: 总数 150 间, 期末在租 58 间 (其中期末付费 58 间)
        期末空置率    : 61.33%
        ---
        期间房晚数    : 总入住房晚数 1,610 晚, 总付费房晚数 1,610 晚
        期间空置率    : 65.38%
        ---
        期间租金表现  : 期间总租金 718,410.88 元, 期间平均日租金 446.22 元
        坪效表现      : 6.11 元/m²/日 (按户型面积 73 m² 计算)
        ---
        最高月租金    : 21,029.00 元 (记录ID: 2773, 入住: 2025-01-06, 离店: 2026-01-06)
        最低月租金    : 8,250.00 元 (记录ID: 2911, 入住: 2025-05-27, 离店: 2026-05-27)

        ==================== 户型: 一房行政豪华式公寓 ====================
        期末供应与占用: 总数 19 间, 期末在租 6 间 (其中期末付费 6 间)
        期末空置率    : 68.42%
        ---
        期间房晚数    : 总入住房晚数 186 晚, 总付费房晚数 186 晚
        期间空置率    : 68.42%
        ---
        期间租金表现  : 期间总租金 114,002.29 元, 期间平均日租金 612.92 元
        坪效表现      : 6.96 元/m²/日 (按户型面积 88 m² 计算)
        ---
        最高月租金    : 24,000.00 元 (记录ID: 3385, 入住: 2025-07-22, 离店: 2026-07-22)
        最低月租金    : 12,484.80 元 (记录ID: 2867, 入住: 2025-03-04, 离店: 2026-03-04)

        ==================== 户型: 两房行政公寓 ====================
        期末供应与占用: 总数 15 间, 期末在租 3 间 (其中期末付费 3 间)
        期末空置率    : 80.00%
        ---
        期间房晚数    : 总入住房晚数 68 晚, 总付费房晚数 68 晚
        期间空置率    : 85.38%
        ---
        期间租金表现  : 期间总租金 53,570.00 元, 期间平均日租金 787.79 元
        坪效表现      : 7.29 元/m²/日 (按户型面积 108 m² 计算)
        ---
        最高月租金    : 24,220.00 元 (记录ID: 3311, 入住: 2025-07-15, 离店: 2026-07-15)
        最低月租金    : 20,160.00 元 (记录ID: 3677, 入住: 2025-08-26, 离店: 2025-10-13)

        ==================== 户型: 三房公寓 ====================
        期末供应与占用: 总数 1 间, 期末在租 0 间 (其中期末付费 0 间)
        期末空置率    : 100.00%
        ---
        期间房晚数    : 总入住房晚数 0 晚, 总付费房晚数 0 晚
        期间空置率    : 100.00%
        ---
        期间租金表现  : 期间总租金 0.00 元, 期间平均日租金 0.00 元
        坪效表现      : 0.00 元/m²/日 (按户型面积 134 m² 计算)
        ---
        最高月租金    : N/A (期间无付费记录)
        最低月租金    : N/A (期间无付费记录)

        ==================== 户型: 豪华单间公寓 ====================
        期末供应与占用: 总数 22 间, 期末在租 7 间 (其中期末付费 7 间)
        期末空置率    : 68.18%
        ---
        期间房晚数    : 总入住房晚数 160 晚, 总付费房晚数 160 晚
        期间空置率    : 76.54%
        ---
        期间租金表现  : 期间总租金 37,177.47 元, 期间平均日租金 232.36 元
        坪效表现      : 5.16 元/m²/日 (按户型面积 45 m² 计算)
        ---
        最高月租金    : 8,530.00 元 (记录ID: 2507, 入住: 2024-11-05, 离店: 2025-11-05)
        最低月租金    : 5,050.20 元 (记录ID: 2940, 入住: 2025-04-01, 离店: 2026-04-01)

        ==================== 户型: 行政单间公寓 ====================
        期末供应与占用: 总数 360 间, 期末在租 119 间 (其中期末付费 117 间)
        期末空置率    : 66.94%
        ---
        期间房晚数    : 总入住房晚数 3,152 晚, 总付费房晚数 3,100 晚
        期间空置率    : 71.76%
        ---
        期间租金表现  : 期间总租金 850,342.33 元, 期间平均日租金 274.30 元
        坪效表现      : 4.57 元/m²/日 (按户型面积 60 m² 计算)
        ---
        最高月租金    : 13,705.00 元 (记录ID: 2849, 入住: 2025-02-26, 离店: 2026-02-26)
        最低月租金    : 6,600.00 元 (记录ID: 3232, 入住: 2025-06-07, 离店: 2026-06-07)

        ==================== 户型: 豪华行政单间 ====================
        期末供应与占用: 总数 12 间, 期末在租 1 间 (其中期末付费 1 间)
        期末空置率    : 91.67%
        ---
        期间房晚数    : 总入住房晚数 31 晚, 总付费房晚数 31 晚
        期间空置率    : 91.67%
        ---
        期间租金表现  : 期间总租金 7,192.00 元, 期间平均日租金 232.00 元
        坪效表现      : 3.46 元/m²/日 (按户型面积 67 m² 计算)
        ---
        最高月租金    : 6,960.00 元 (记录ID: 3267, 入住: 2025-06-15, 离店: 2026-06-15)
        最低月租金    : 6,960.00 元 (记录ID: 3267, 入住: 2025-06-15, 离店: 2026-06-15)

        ==================== 总体概要 ====================
        所有户型期间总平均日租金: 345.43 元 (基于 5,155 晚期间总付费房晚数计算)

        ========================================================
        '
        """
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
    功能描述 (description): 一个用于获取指定用户ID的用户信息

    输入参数 (parameters):
    id (Optional[str]): 用户ID，可使用从如occupancy_details等其他工具中获取的ID；例如: '3664'

    返回结果 (returns):
    下面是一个调用返回示例：
    print(query_guest("3664"))
    返回：
    '
    成功加载并处理了 501 条记录。
    --- ID: 3664 的核心数据 ---
    主键ID         : 3664
    客户档案ID     : 2522
    姓名           : 晏**
    推断性别       : 男
    出生日期       : 2003-11-02 01:00:00
    语言代码       : C
    手机           : [空]
    电子邮件       : 1**********@163.com
    国籍代码       : CN
    国家代码       : CN
    省份/州代码    : JX
    街道地址       : 江***
    证件类型代码   : 01
    证件号码       : 3****************2
    酒店ID         : 11
    客户档案类型   : GUEST
    入住次数       : 0
    创建用户       : JACQUELINELIANG
    创建时间       : 2025-08-11 16:38:58
    修改用户       : SHINZHANG
    修改时间       : 2025-08-11 17:03:41
    ----------------------------
    '
    """

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
def query_checkins(start: str, end: str, choice: str):
    """
    功能描述 (description): 一个用于获取指定时间段内的入住信息，可获得的具体字段有：入住日期、离店日期、房号、房型、租金、状态、用户ID、备注、交班信息

    输入参数 (parameters):
    start (Optional[str]): 时间区间起点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'
    end (Optional[str]): 时间区间终点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'
    choice (Optional[str]): 选择是要查询的入住状态，可选值为"'1': I (在住) '2': O (结帐) '3': X (取消) '4': R (预订) '5': ALL (所有状态，默认)"，默认为 'ALL'

    返回结果 (returns):
    下面是一个调用返回示例：
    print(query_checkins('2025-08-08', '2025-08-12', '1'))
    返回：
    '
    --- 入住记录查询结果 (2025-08-08 到 2025-08-12, 状态: I) ---
    共找到 7 条（去重后）记录。

          入住日期       离店日期    房号      房型        租金 状态  用户ID                                    备注 交班信息
    2025-08-08 2026-08-08  A608  行政单间公寓  7,011.00  I  3548 年租押二付一/已经支付了11685元的押金/8.8办理入住/包500元水电
    2025-08-09 2025-11-09 B1510 一房豪华式公寓 10,800.00  I  3617
    2025-08-10 2026-08-10 A1008  行政单间公寓  6,600.00  I  3575                   POA11000/月 押2付1 6+6
    2025-08-11 2025-10-11 A1105  行政单间公寓  7,984.20  I  3663                         POA13307 押一付一
    2025-08-11 2025-09-10  A212  行政单间公寓      0.00  I  3664                           马总朋友，IT协助项目
    2025-08-11 2025-11-11  A515  行政单间公寓  8,383.20  I  3642         客户押一付一/已支付一个月押金13972元/带一只小狗入住
    2025-08-12 2026-08-12 A1723 一房豪华式公寓 11,192.40  I  3660                          18654/月，押二付一

    --------------------------------------------------------------------------------
    '
    """
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
    功能描述 (description): 一个用于获取指定房间号的入住信息，可获得的具体字段有：入住日期、离店日期、房号、房型、租金、状态、用户ID、备注、交班信息

    输入参数 (parameters):
    rooms (Union[str, List[str]]): 需要查询的一个或多个房间号。
        - 推荐的标准格式 (列表): ["A312", "A313", "B1510"]
        - 兼容的格式 (字符串): "A312"

    返回结果 (returns):
    下面是一个调用返回示例：
    print(query_by_room("A312,A313"))
    返回：
    '
    --- 房间号查询结果 (A312, A313) ---
    共找到 4 条相关记录。

          入住日期       离店日期   房号     房型        租金 状态   用户ID                备注 交班信息
    2025-06-16 2025-09-16 A313 行政单间公寓  9,021.00  I 3296 客户预计需要租赁1个月+15天左右
    2025-06-16 2025-08-03 A312 行政单间公寓 10,144.80  O 3306       预计还需要再租赁15天
    2025-06-16 2025-09-16 A313 行政单间公寓      0.00  I 3356
    2025-06-16 2025-08-03 A312 行政单间公寓      0.00  O 3577
    '
    状态对应为 I (在住)  O (结帐)  X (取消)  R (预订)
    """
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
        功能描述 (description): 一个用于获取指定房间号的历史工单信息，可获得的具体字段有：工单ID、房号、服务项目、需求描述、具体位置、优先级、进入房间指引/注意事项、服务状态、服务人员、处理结果、创建时间、完成时间

        输入参数 (parameters):
        room (Optional[str]): 房间号


        返回结果 (returns):
        下面是一个调用返回示例：
        print(query_orders('A513'))
        返回：
        '
          工单ID:     3422
          房号:       A513
          服务项目:   拖线板 (B506)
          需求描述:   浴室淋浴房漏水 需要第二次修补 漏水太厉害
          具体位置:   客厅 (009)
          优先级:   低
          进入房间指引/注意事项:   室内无人 需前台陪同
          服务状态:   O
          服务人员:   工程刘
          处理结果:   已处理
          创建时间:   2025-07-13 22:17:33
          完成时间:   2025-07-14 18:47:44
        '
    """
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
    功能描述 (description):
    一个用于根据时间范围、服务项目和具体位置等条件，查询历史工单信息的服务函数。
    可获得的具体字段有：工单ID、房号、服务项目、具体位置、需求描述、优先级、进入指引、服务状态、服务人员、处理结果、创建时间、完成时间。

    输入参数 (parameters):
    start_date_str (Optional[str]): 开始日期, 格式为 'YYYY-MM-DD'
    end_date_str (Optional[str]):   结束日期, 格式为 'YYYY-MM-DD'
    service_code (Optional[str]):   服务项目代码 (例如 'B501' 代表电源插座)。默认为None (不限)。
    location_code (Optional[str]):  具体位置代码 (例如 '004' 代表厨房)。默认为None (不限)。

    具体服务项目代码与具体位置代码为：
    SERVICE_CODE_MAP = {
        'A01': '更换布草', 'A02': '家具保洁', 'A03': '地面保洁', 'A04': '家电保洁',
        'A05': '洁具保洁', 'A06': '客用品更换', 'A07': '杀虫', 'B1001': '电梯',
        'B101': '冰箱', 'B102': '微波炉', 'B103': '烘干机', 'B104': '电视',
        'B105': '洗衣机', 'B106': '空气净化器', 'B107': '抽湿机', 'B108': '油烟机',
        'B110': '电风扇', 'B114': '取暖机', 'B117': '投影仪', 'B119': '屏幕',
        'B120': '热水器', 'B121': '洗碗机', 'B122': '电磁炉', 'B123': '烤箱',
        'B124': '排气扇', 'B201': '烟雾报警器', 'B202': '手动报警器',
        'B203': '消防喷淋', 'B204': '消防应急灯', 'B301': '暖气片', 'B302': '通风管',
        'B303': '空调', 'B401': '毛巾架', 'B402': '龙头', 'B403': '室内门把手/门锁',
        'B404': '窗户', 'B405': '铰链', 'B501': '电源插座', 'B502': '开关',
        'B503': '灯具', 'B504': '电灯泡', 'B505': '灭蝇灯', 'B506': '拖线板',
        'B601': '家具', 'B602': '橱柜', 'B603': '天花板', 'B604': '地板',
        'B605': '墙', 'B606': '百叶窗', 'B607': '脚板', 'B701': '排水',
        'B702': '浴盆', 'B703': '镜子', 'B704': '瓷砖', 'B705': '水槽',
        'B706': '花洒', 'B707': '马桶', 'B708': '台盆', 'B801': '其他',
        'B901': '网络设备'
    }
    LOCATION_CODE_MAP = {
        '002': '卧室', '004': '厨房', '008': '卫生间', '009': '客厅',
        '001': '公寓外围', '003': '工区走道', '005': '后场区域', '006': '前场区域',
        '011': '电梯厅-后', '010': '电梯厅-前', '007': '停车场', '012': '消防楼梯',
    }

    返回结果 (returns):
    str: 一个包含所有查询结果的、格式化好的字符串。如果未找到结果，则返回相应的提示信息。
        下面是一个调用返回示例：
        print(advanced_query_service(start_date_str='2025-07-01', service_code='B701'))
        返回：
        '''
        查询条件: 时间范围: [2025-07-01 至 不限], 服务项目: [排水], 具体位置: [不限]
        --- 共找到 2 条相关工单 ---

        【记录 1】
        工单ID:     2639
        房号:       B902
        服务项目:   排水 (B701)
        具体位置:   卫生间 (008)
        需求描述:   浴室下水慢，密封胶条开裂
        优先级:     低
        进入指引:   未提供
        服务状态:   O
        服务人员:   Junfeng Wu
        处理结果:   完成
        创建时间:   2025-05-06 10:29:28
        完成时间:   2025-05-06 11:29:43

        【记录 2】
        工单ID:     3251
        房号:       B911
        服务项目:   排水 (B701)
        具体位置:   未提供 (无代码)
        需求描述:   浴室下水慢
        优先级:     LOW
        进入指引:   未提供
        服务状态:   O
        服务人员:   leonhu
        处理结果:   修复
        创建时间:   2025-07-03 12:12:09
        完成时间:   2025-07-03 12:39:36
        '''
    """
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
    # 根据源代码，'streamable-http' 是用于通用HTTP交互的模式
    mcp.run(transport="sse")