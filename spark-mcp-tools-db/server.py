import os
import datetime
import logging
from dotenv import load_dotenv
from fastmcp import FastMCP
from typing import List, Union, Optional, Any, Dict
from utils.occupancy import calculate_occupancy_logic
from utils.occupancy_details import get_occupancy_details_logic
from utils.room_guest_query import search_occupancy_logic
from utils.checkins import query_checkins_logic
from utils.orders import query_orders_logic
from utils.advanced_service import search_work_orders_logic
from utils.distribution import query_distribution_report_logic
from utils.statistics import get_guest_statistics_logic
from utils.guest_details import get_filtered_details_logic
from utils.nearby import nearby_report_logic
from utils.apartment_search import find_apartments_logic
from utils.daily_occupancy import analyze_occupancy_logic
from utils.geo_navigation import plan_route_logic
from utils.image_finder import get_image_list_logic

load_dotenv()
# ==========================================
# 1. 配置日志与环境变量
# ==========================================

# 设置日志格式，使其更易读
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("ApartmentDBServer")

GAODE_API_KEY = os.getenv("GAODE_API_KEY")
if not GAODE_API_KEY:
    logger.warning("⚠️ 高德地图 API Key 未设置（GAODE_API_KEY），amap_search 工具将不可用。")

# ==========================================
# 2. 初始化 FastMCP
# ==========================================

mcp = FastMCP(
    name="Apartment DB Assistant", 
    host="0.0.0.0", 
    port=8003
)

# --- 1. 查询现在的系统时间 ---
@mcp.tool()
def get_current_time(format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    获取当前系统时间，并按指定格式返回

    返回结果 (returns):
    下面是一个调用返回示例：
    get_current_time()
    返回：
    2025-10-22 16:24:21
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


# --- 3. 出租率工具函数 ---
# @mcp.tool()
def calculate_occupancy(start: str, end: str, calc_method: str = 'period_avg'):
    """
    功能描述 (description): 一个用于获取指定时间内的入住率以及出租率的工具。
    支持两种计算模式，分别适用于财务分析(period_avg)和运营库存查询(end_point)。

    输入参数 (parameters):
    start (Optional[str]): 时间区间起点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'
    end (Optional[str]): 时间区间终点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'
    calc_method (str): 计算方式 (默认为 'period_avg')。
        - 'period_avg': [期间加权平均]
           计算公式：总实际入住房晚 / 总可用房晚。
           适用场景：财务月报、经营情况分析、查看一段时间的整体表现。
        - 'end_point': [期末时点快照]
           计算公式：结束日当天的在住房间数 / 总房间数。
           适用场景：运营查房、查看当前/未来的瞬时库存压力、销售查看某天还剩多少房。

    返回结果 (returns):
    下面是调用返回示例：
    calculate_occupancy("2025-11-01", "2025-11-30", "period_avg")
    返回：
    '
    统计范围: 2025-11-01 至 2025-11-30 (30 天)
    总房间数: 579
    总可用房晚: 17,370
    实际占有用房晚: 8,082
    ------------------------------
    实际入住率 (Occupancy): 46.53%
    广义出租率 (Application): 47.53%
    (注: 广义出租率包含已签约但未入住的预定)
    '

    calculate_occupancy("2025-11-01", "2025-11-30", "end_point")
    返回：
    '
    统计范围: 时点: 2025-11-30
    总房间数: 579
    ------------------------------
    当前在住房间数: 262
    广义占用房间数: 262 (含预定)
    ------------------------------
    即时入住率: 45.25%
    即时出租率: 45.25%
    '
    """

    print(f"--- 入住率计算 (Database Mode) --- 参数: {start} 至 {end}, 统计方式 {calc_method}")
    return calculate_occupancy_logic(start, end, calc_method)


# --- 户型经营表现分析工具 ---
# @mcp.tool()
def occupancy_details(start_time: str, end_time: str, calc_method: str = 'period_avg') -> str:
    """
    功能描述 (description): 一个用于获取指定时间段内的不同房型的出租情况（租金，坪效，空置率）的工具，同时还可获得不同房型的最高租金与最低租金，以及对应的用户ID

    输入参数 (parameters):
    start_time (Optional[str]): 时间区间起点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'
    end_time (Optional[str]): 时间区间终点，必须按照YYYY-MM-DD格式填写；例如: '2025-05-01'
    calc_method (str): 统计方式 (默认为 'period_avg')。
        - 'period_avg': [期间加权] 统计整个时间段内的总房晚、总营收、平均出租率。
        - 'end_point': [期末时点] 仅统计结束日期当天的在租房间数、实时月租金流水、空置率。

    返回结果 (returns):
    下面是一个调用返回示例：
    occupancy_details("2024-11-01", "2024-11-30")
    返回：
    '
    --- 各户型经营表现分析 (数据范围: 2024-11-01 至 2024-11-30) ---
    ==================== 户型: 一房豪华式公寓 ====================
    期末供应与占用: 总数 150 间, 期末在租 11 间 (期末付费 11 间)
    期末空置率    : 92.67%
    ---
    期间房晚数    : 总入住房晚数 311 晚
    期间空置率    : 93.09%
    ---
    期间租金表现  : 期间总租金 181,602.33 元, ADR 583.93 元
    坪效表现      : 8.00 元/m²/日
    ---
    最高月租金    : 17,990.00 元 (合同: 2411030041)
    最低月租金    : 12,570.00 元 (合同: 2410220021)
    ...
    '
    """
    print(f"--- 户型经营表现分析 (DB Direct) --- {start_time} 至 {end_time} 统计方式 {calc_method}")
    return get_occupancy_details_logic(start_time, end_time, calc_method)

# --- 出租率工具 和 户型经营表现分析工具 聚合函数 ---
@mcp.tool()
def analyze_occupancy(start_date: str, end_date: str, calc_method: str = 'period_avg'):
    """
    功能描述 (description): 
    一个用于获取指定时间内的入住率以及出租率、不同房型的出租情况（租金，坪效，空置率）、总租金的工具，同时还可获得不同房型的最高租金与最低租金，以及对应的住户的房间号。

    输入参数 (parameters):
    start_date (str): 统计开始日期，格式必须是'YYYY-MM-DD'
    end_date (str): 统计结束日期，格式必须是'YYYY-MM-DD'
    calc_method (str): 统计方式，默认为 'period_avg'。
        - 'period_avg': 期间累计/平均，适用于财务月报/季报。统计整个时间段内的总收入、总房晚。
        - 'end_point': 期末时点快照，适用于运营盘点/库存查询。仅统计 end_date 当天的在住情况。

    返回结果 (returns):
    下面是一个调用返回示例：
    analyze_occupancy("2025-11-01", "2025-11-30", "period_avg")
    返回：
    '
    统计范围: 2025-11-01 至 2025-11-30 (共 30 天)
    总房间数: 579 间
    总可用房晚：17,370
    实际在住房晚: 8,107
    出租率 (Occ): 46.67%
    空置率 (Vac): 53.33%
    坪效最高房间：A2211，面积：72.0，坪效：10.08
    坪效最低房间：A220，面积：57.0，坪效：2.61
    日租金最高房间: A1622，面积：108.0，日租金：990.18
    月租金最高房间：A1622，面积：108.0，月租金：30118.00
    日租金最低房间: B308，面积：42.0，日租金：166.03
    月租金最低房间：B308，面积：42.0，月租金：5050.20
    ...
    '
    """
    return analyze_occupancy_logic(start_date, end_date, calc_method)


@mcp.tool()
def query_room_guest(query: Union[str, List[str]]):
    """
    功能描述 (description): 通用住客与房间查询工具。
    支持通过【房间号】查询该房间的历史入住记录，或通过【住客ID/账号】查询特定住客的详细档案。
    返回信息包含：房号、住客姓名、ID、当前状态、房型、租金、租期时间、住客画像(年龄/国籍)及备注。

    输入参数 (parameters):
    query (Union[str, List[str]]): 查询关键词列表。
        - 输入房号 (如 "A1001")：返回该房间的所有历史住客记录。
        - 输入ID (如 "4044")：返回该住客的详细档案。
        - 支持混合输入 (如 "A1001, 4044")。

    返回结果 (returns):
    返回包含住客姓名、状态、房号、房型、生日、性别、国籍、租期及备注等详细信息的文本。
    下面是一个调用返回示例：
    query_guest("A212,A215,3808")
    返回：
    '
    共找到 11 条记录 (含续租)。
    --------------------------------------------------------------------------------
    房号: A212 | 在住 (I) | 租金: N/A/月
    房型: 行政单间公寓
    租期: 2025-11-10 至 2025-12-10
    家庭入住: 晏**(3664) [男, 22岁, 中国], 晏**(3121)
    备注: 马总朋友，IT协助项目
    ...

    房号: A213 | 在住 (I) | 租金: N/A/月
    房型: 行政单间公寓
    租期: 2025-11-10 至 2025-12-10
    住客: 廖**(3808) [男, 35岁, 中国]
    ...
    '
    """
    return search_occupancy_logic(query)


@mcp.tool()
def query_checkins(start: str, end: str, status: str = 'ALL'):
    """
    功能描述 (description): 用于查询指定时间段内的公寓在住(入住)、预订、离店、未来一周离店、未来一周入住等历史记录。
    支持通过具体的业务状态代码进行精确筛选。

    输入参数 (parameters):
    start (str): 查询起始日期，格式必须为'YYYY-MM-DD'
    end (str): 查询结束日期，格式必须为'YYYY-MM-DD'
    status (str): 状态代码筛选 (默认为 'ALL')。可选值如下：
        'I' : 在住(入住) (In House) - 当前租户状、入住日期
        'R' : 预定 (Reservation) - 已预定但未入住
        'O' : 结账 (Checked Out) - 正常离店结账
        'S' : 挂账 (Suspended) - 已离店但有未清账务
        'P' : 预离 (Pre-departure) - 未来一段时间(1周)即将离店
        'A' : 将到 (Arriving) - 未来一段时间(1周)即将入住
        'ALL': 显示以上所有状态

    返回结果 (returns):
    返回一个格式化的文本表格，包含入住日期、离店日期、房号、房型、住客ID、租金及状态描述。
    """
    return query_checkins_logic(start, end, status)


@mcp.tool()
def get_statistical_summary(
        name: Optional[str] = None,
        room_number: Optional[str] = None,
        gender: Optional[str] = None,
        status: Union[str, List[str]] = None,
        nation: Optional[str] = None,
        min_age: Optional[int] = None,
        max_age: Optional[int] = None,
        min_rent: Optional[float] = None,
        max_rent: Optional[float] = None,
        start_arr_date: Optional[Any] = None,
        end_arr_date: Optional[Any] = None,
        room_type: Optional[Union[str, List[str]]] = None
) -> Dict[str, Any]:
    """
    住客数据计分析工具,根据筛选条件对住客入住数据进行统计分析。
    可以使用这个工具获取到公寓住客的统计信息，包括各房型入住人数和占比、年龄段统计、各年龄段租金贡献率、性别比例统计、性别租金贡献率、国籍分布、各国籍租客男女占比、租金范围占比、宠物租户数量和占比等数据。
    根据用户需求自由组合参数查询最合理的结果。

    输入参数 (parameters):
        name (str): 按住客姓名进行模糊搜索。
        room_number (str): 按房号进行精确匹配。
        gender (str): 性别筛选，必须精确匹配 "男" 或 "女"。查询"女性"、"男性"数据时请务必使用此字段。
        status (str/List): 住户状态，支持参数：'I'(在住), 'O'(离店), 'R'(预定), 'S'(挂账), 'X'(取消), 'D'(删除), 'W'(在住未送签)
        nation (str): 国籍 (如 "中国", "日本")，**严禁**在此字段填入性别（如"男"、"女"），性别请务必使用 gender 字段。
        min_age (int): 最小年龄
        max_age (int): 最大年龄
        min_rent (float): 最低租金
        max_rent (float): 最高租金
        start_arr_date (str): 开始日期, 格式必须为'YYYY-MM-DD'，默认为None(不限制)
        end_arr_date (str): 结束日期，格式必须是'YYYY-MM-DD'，默认为None(不限制)
        room_type (str/List): 房型 ('行政单间', '行政豪华单间', '豪华单间', '一房豪华式公寓', '一房行政豪华式公寓', '两房豪华式公寓', '三房式公寓'),注意单间也都属于一房类的户型。

    Returns:
        Dict: 包含总数和各维度分布统计的字典。
    调用示例：
    当前在住的住客中，按性别分类，查询不同年龄段的住客数量：
    get_guest_statistics_logic(status='I')

    当前在住的住客中，男性与女性中不同国籍的住客的数量：
    get_guest_statistics_logic(status='I')

    告诉我8月份新入住的住客的男女比例:
    get_guest_statistics_logic(start_arr_date='2025-08-01', end_arr_date='2025-08-31')
    """
    return get_guest_statistics_logic(
        name=name, room_number=room_number, gender=gender, status=status,
        nation=nation, min_age=min_age, max_age=max_age,
        min_rent=min_rent, max_rent=max_rent,
        start_arr_date=start_arr_date, end_arr_date=end_arr_date,
        room_type=room_type
    )


@mcp.tool()
def get_filtered_details(
        name: Optional[str] = None,
        room_number: Optional[str] = None,
        gender: Optional[str] = None,
        status: Union[str, List[str]] = None,
        nation: Optional[str] = None,
        min_age: Optional[int] = None,
        max_age: Optional[int] = None,
        min_rent: Optional[float] = None,
        max_rent: Optional[float] = None,
        start_arr_date: Optional[Any] = None,
        end_arr_date: Optional[Any] = None,
        pet: Optional[str] = None,
        room_type: Optional[Union[str, List[str]]] = None
) -> str:
    """
    根据筛选条件获取详细的住客个人信息列表。
    与 'get_statistical_summary(住客数据计分析工具)' 不同，此工具返回具体的名单详情。例如可以使用这个工具获取到公寓住客的详细信息，包括住户姓名、年龄、国籍、房间号、房型、在住状态、宠物信息、租期、月租金、备注。
    根据用户需求自由组合参数查询最合理的结果。

    输入参数 (parameters):
        name (str): 按住客姓名进行模糊搜索。
        room_number (str): 按房号进行精确匹配。
        gender (str): 性别筛选，必须精确匹配 "男" 或 "女"。查询"女性"、"男性"数据时请务必使用此字段。
        status (str/List): 住户状态，支持参数：'I'(在住), 'O'(离店), 'R'(预定), 'S'(挂账), 'X'(取消), 'D'(删除), 'W'(在住未送签)
        nation (str): 国籍 (如 "中国", "日本")，**严禁**在此字段填入性别（如"男"、"女"），性别请务必使用 gender 字段。
        min_age (int): 最小年龄
        max_age (int): 最大年龄
        min_rent (float): 最低租金
        max_rent (float): 最高租金
        start_arr_date (str): 入住起始日期，格式必须是'YYYY-MM-DD'
        end_arr_date (str): 入住结束日期，格式必须是'YYYY-MM-DD'
        pet (str): 是否有宠物。
            - 'yes': 仅查询有宠物的住客。
            - 'no': 仅查询无宠物的住客。
            - None: 默认，不限制
        room_type (str/List): 房型 ('行政单间', '行政豪华单间', '豪华单间', '一房豪华式公寓', '一房行政豪华式公寓', '两房豪华式公寓', '三房式公寓'),注意单间也都属于一房类的户型。

    Returns:
        str: 格式化后的住客详细信息列表字符串。
    调用示例：
    当前在住用户有哪些租户有宠物：
    get_filtered_details_logic(status='I',pet='yes')
    """
    return get_filtered_details_logic(
        name=name, room_number=room_number, gender=gender, status=status,
        nation=nation, min_age=min_age, max_age=max_age,
        min_rent=min_rent, max_rent=max_rent,
        start_arr_date=start_arr_date, end_arr_date=end_arr_date,
        pet=pet, room_type=room_type
    )


@mcp.tool()
def nearby_report(room: Optional[str]):
    """
    功能描述 (description): 一个用于获取指定房间与其周围房间的入住情况，可获得的周围房间信息有：入住日期、离店日期、房号、房型、租金、用户ID、备注

    输入参数 (parameters):
    room (Optional[str]): 需要查询的房间号。
        - 兼容的格式 (字符串): "A312"

    返回结果 (returns):
    下面是一个调用返回示例：
    print(nearby_report("A213"))
    返回：
    '
    共找到 3 个相邻房间。
    ----------------------------------------
    房间: A313 [楼上]
    房型: 行政单间
    状态: 空置
    租金: 13,922 (挂牌参考)
    ----------------------------------------
    房间: A212 [左邻]
    房型: 行政单间
    状态: 在住 (I)
    租金: 15,700 (挂牌参考)
    住客: 晏**
    ID:   3664
    租期: 2025-08-11 至 2025-12-10
    备注: 马总朋友，IT协助项目
    ----------------------------------------
    房间: A215 [右舍]
    房型: 行政单间
    状态: 在住 (I)
    租金: 13,872 (挂牌参考)
    住客: 王*
    ID:   3134
    租期: 2025-05-17 至 2025-12-10
    备注: 马总朋友 IT协助 预授权押金1000元
    ----------------------------------------
    """
    return nearby_report_logic(room)

@mcp.tool()
def find_apartments(
        room_number: Optional[str] = None,
        building_no: Optional[Union[str, List[str]]] = None,
        room_code_desc: Optional[Union[str, List[str]]] = None,
        orientation: Optional[Union[str, List[str]]] = None,
        floor_range: Optional[Union[str, List[int]]] = None,
        area_sqm_range: Optional[Union[str, List[float]]] = None,
        price_range: Optional[Union[str, List[float]]] = None,
        sort_by: str = 'monthly_rent',
        sort_order: str = 'asc',
        aggregation: Optional[str] = None,
        limit: int = 10
) -> dict:
    """
    查询公寓物理房间基本信息数据，可获取房间面积、朝向、楼层、房型、参考租金以及符合对应查询条件的房间信息。理论上高楼层意味着视野好，可通过该方法给用户推荐房间。
    根据用户需求自由组合参数查询最合理的结果。

    输入参数 (parameters):
        room_number (str): 精确查询的房号 (例如 'A1001')。
        building_no (Union[str, List[str]]): 楼栋 ('A', 'B')，默认为None(不限楼栋)。
        room_code_desc (Union[str, List[str]]): 房型 ('行政单间', '行政豪华单间', '豪华单间', '一房豪华式公寓', '一房行政豪华式公寓', '两房豪华式公寓', '三房式公寓'),注意单间也都属于一房类的户型, 默认为None(不限房型)。
        orientation (Union[str, List[str]]): 房间朝向 ('南', '东 南', '东', '东 北', '北', '西', '西 南', '西 北'),默认为None(不限房间朝向)。
        floor_range (Union[str, List[int]]): 楼层范围 (min_floor, max_floor),默认为None(不限楼层)。
        area_sqm_range (Union[str, List[float]]): 面积范围 (min_area, max_area)，默认为None(不限面积)。
        price_range (Union[str, List[float]]): 参考价格范围 (min_price, max_price)，默认为None(不限租金)。
        sort_by (str): 排序依据。默认为 'monthly_rent'。可选值: 'monthly_rent', 'area_sqm', 'floor'。
        sort_order (str): 排序顺序。默认为 'asc' (升序)。可选值: 'asc', 'desc'。
        aggregation (str): 传 'count' 只返回符合条件的房源总数。
        limit (int): 返回结果的最大数量。默认为 10。

    Returns:
        dict: 包含房源列表的结果。

    调用示例：
    查询参考月租金最低的5个朝南行政单间：
    find_apartments(room_code_desc=['行政单间'],orientation=['南', '东南', '西南'],sort_by='monthly_rent',sort_order='asc',limit=5)

    查询A栋、15层以上、朝南、月租金2万5以内、面积最大的'一房'公寓，并且只需要房间号、参考月租金、面积、朝向信息：
    find_apartments(building_no=['A'],floor_range=(15, 100),orientation=['南'],room_code_desc=['一房'],price_range=(0, 25000),sort_by='area_sqm',sort_order='desc')

    能否提供更多详细房间信息，例如房间类型、面积：
    find_apartments_logic(room_code_desc=['行政单间', '行政豪华单间', '豪华单间', '一房豪华式公寓', '一房行政豪华式公寓', '两房豪华式公寓', '三房式公寓'])
    """
    return find_apartments_logic(
        room_number=room_number,
        building_no=building_no,
        room_code_desc=room_code_desc,
        orientation=orientation,
        floor_range=floor_range,
        area_sqm_range=area_sqm_range,
        price_range=price_range,
        sort_by=sort_by,
        sort_order=sort_order,
        aggregation=aggregation,
        limit=limit
    )


@mcp.tool()
def query_orders(
        start_date_str: Optional[str] = None,
        end_date_str: Optional[str] = None,
        room_number: Optional[str] = None,
        service_code: Optional[str] = None,
        location_code: Optional[str] = None,
        status_code: Optional[str] = None
) -> str:
    """
    功能描述 (description):
    一个用于根据时间范围、房间号、服务项目和具体位置等条件，查询历史工单信息的服务函数。生成工单统计汇总报告。包含总体数据、Top榜单、时间分布趋势（年/月/周/时段）、以及按楼栋/楼层的详细分布层级。
    可获得的具体字段有：工单ID、房号、服务项目、具体位置、需求描述、优先级、进入指引、服务状态、服务人员、处理结果、创建时间、完成时间。

    输入参数 (parameters):
    start_date_str (Optional[str]): 开始日期, 格式必须为'YYYY-MM-DD'，默认为None(不限开始时间)
    end_date_str (Optional[str]):   结束日期, 格式必须为'YYYY-MM-DD'，默认为None(不限结束时间)
    room_number (Optional[str]):    房间号，支持单个或多个 (如 "A1001" 或 "A1001, B205")。默认为None(不限)。
    service_code (Optional[str]):   服务项目代码 (例如 'B501' 代表电源插座)。默认为None (不限)。
    location_code (Optional[str]):  具体位置代码 (例如 '004' 代表厨房)。默认为None (不限)。
    status_code (Optional[str]):    工单状态代码，默认为None (不限)，可选值：
        - 'C' : 已完成 (Completed)
        - 'U' : 未完成 (Unfinished)
        - 'X' : 已取消 (Cancelled)

    参数代码对照表：
    [1. 服务项目代码 (service_code)]
    --- 保洁类 ---
    A01: 更换布草, A02: 家具保洁, A03: 地面保洁, A04: 家电保洁, A05: 洁具保洁, A06: 客用品更换, A07: 杀虫

    --- 家电类 ---
    B101: 冰箱, B102: 微波炉, B103: 烘干机, B104: 电视, B105: 洗衣机,
    B106: 空气净化器, B107: 抽湿机, B108: 油烟机, B110: 电风扇,
    B114: 取暖机, B117: 投影仪, B119: 屏幕, B120: 热水器, B121: 洗碗机,
    B122: 电磁炉, B123: 烤箱, B124: 排气扇

    --- 消防/安防 ---
    B201: 烟雾报警器, B202: 手动报警器, B203: 消防喷淋, B204: 消防应急灯

    --- 暖通/空调 ---
    B301: 暖气片, B302: 通风管, B303: 空调

    --- 五金/门窗 ---
    B401: 毛巾架, B402: 龙头, B403: 室内门把手/门锁, B404: 窗户, B405: 铰链

    --- 强电/照明 ---
    B501: 电源插座, B502: 开关, B503: 灯具, B504: 电灯泡, B505: 灭蝇灯, B506: 拖线板

    --- 硬装/结构 ---
    B601: 家具, B602: 橱柜, B603: 天花板, B604: 地板, B605: 墙, B606: 百叶窗, B607: 脚板

    --- 卫浴/水路 ---
    B701: 排水, B702: 浴盆, B703: 镜子, B704: 瓷砖, B705: 水槽,
    B706: 花洒, B707: 马桶, B708: 台盆

    --- 其他 ---
    B1001: 电梯, B801: 其他, B901: 网络设备

    [2. 具体位置代码 (location_code)]
    001: 公寓外围, 002: 卧室, 003: 工区走道, 004: 厨房,
    005: 后场区域, 006: 前场区域, 007: 停车场, 008: 卫生间,
    009: 客厅, 010: 电梯厅-前, 011: 电梯厅-后, 012: 消防楼梯

    返回结果 (returns):
    str: 一个包含所有查询结果的、格式化好的字符串。如果未找到结果，则返回相应的提示信息。

    下面是一个调用返回示例：
    advanced_query_service(start_date_str='2025-07-01', service_code='B701')
    返回：
    '''
    查询条件: 时间范围: [2025-07-01 至 不限], 房间号：[不限], 服务项目: [排水], 具体位置: [不限]
    --- 共找到 1 条相关工单 ---

    【记录 1】
    工单ID:     GD202505040007
    房号:       A1209
    服务项目:   电磁炉 (维修)
    具体位置:   ROOM 厨房
    申请人:     魔法部 (电话: 13051352536)
    服务状态:   已完成
    处理人:     王元辰
    创建时间:   2025-05-04 16:06:52
    更新时间:   2025-07-15 10:14:47
    '''
    """
    return search_work_orders_logic(
        start_date_str, end_date_str, room_number, service_code, location_code, status_code
    )


@mcp.tool()
def plan_route_between(
    origin: str,
    destination: str,
    mode: str = "transit"
) -> str:
    """
    功能描述 (description): 
    基于高德地图的智能路径规划工具，用于查询两个地点之间的最佳通勤方案。
    
    输入参数 (parameters):
      origin (str): 起点地址，例如 "中国上海市静安区虬江路931号"
      destination (str): 终点地址，例如 "上海市人民广场"
      mode (str): 出行方式。可选值: 
        - 'transit' (默认): 公共交通
        - 'walking': 纯步行
        - 'driving': 驾车
        - 'bicycling': 骑行

    返回结果 (returns):
      包含出行方式、距离、时间、关键步骤的简洁摘要。
    """
    return plan_route_logic(origin, destination, mode=mode)


@mcp.tool()
def spark_show_image(
    targets: Optional[Union[str, List[str]]] = None,
    all_public_areas: Optional[str] = None
) -> str:
    """
    功能描述 (description):
    获取公寓各个区域或房型的展示图片名称列表。

    输入参数 (parameters):
      targets (Union[str, List[str]]): 支持单个字符串、逗号分隔字符串或JSON列表。
        支持的关键词及对应含义：
        [公共区域]
        - lobby  (公寓大厅/1F)
        - bar    (酒吧/7F)
        - gym    (健身房/7F)
        - ktv    (KTV/7F)
        - music  (音乐室/7F)
        - patio  (连接桥/走廊/7F)
        - pool   (游泳池/7F)
        - kitchen(私享厨房/7F)
        - booth  (单人办公间/7F)
        - yoga   (瑜伽房/7F)

        [房型代码]
        - STD (豪华单间)
        - STE (行政单间)
        - 1BD (一房豪华式公寓)
        - 1BP (一房行政豪华式公寓)
        - STP (行政豪华单间)
        - 2BD (两房豪华式公寓)
        - 3BR (三房式公寓)

      all_public_areas (str): 是否获取所有7楼公共区域的图片。
        - 默认为 None。
        - 如果设置为 "true" 或 "yes"，则返回所有公区（健身房、泳池等）的图片列表。
        - 适用场景：用户询问“你们有哪些公区设施？”或者“给我看看所有公区的照片”。

    返回结果 (returns):
      图片文件名列表。例如: ['gym.jpg', 'lobby.jpg']
    """
    return get_image_list_logic(targets=targets, all_public_areas=all_public_areas)




# ==========================================
# 5. 启动入口
# ==========================================

if __name__ == "__main__":
    # 启动服务 (SSE 模式)
    logger.info(f"🚀 MCP 服务启动中... 模式: SSE | 地址: http://{mcp.settings.host}:{mcp.settings.port}/sse")
    mcp.run(transport="sse")