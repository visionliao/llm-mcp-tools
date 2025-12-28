import datetime
import sys
import os
import logging

try:
    from .db import get_db_cursor
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor

logger = logging.getLogger("OccupancyLogic")

# 定义合法的计算方式
VALID_METHODS = {'period_avg', 'end_point'}

def calculate_occupancy_logic(start: str, end: str, calc_method: str = 'period_avg') -> str:
    """
    出租率计算核心逻辑。

    参数:
        calc_method: 
            - 'period_avg': 期间加权平均 (总入住房晚 / 总可用房晚) -> 财务/管理视角
            - 'end_point': 期末时点数据 (结束日当天的出租率) -> 运营/销售库存视角
    """
    logger.info(f"计算出租率: {start} 至 {end}, 模式: {calc_method}")

    # 1. 参数验证
    try:
        start_date = datetime.datetime.strptime(start, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end, '%Y-%m-%d').date()
    except ValueError:
        return "输入错误：日期格式不正确，请使用 'YYYY-MM-DD' 格式。"

    if start_date > end_date:
        return "输入错误：开始日期不能晚于结束日期。"

    if calc_method not in VALID_METHODS:
        return f"输入错误：不支持的计算方式 '{calc_method}'。可选值: period_avg, end_point"

    try:
        with get_db_cursor() as cur:
            # 步骤 1: 获取总房间数
            cur.execute('SELECT COUNT(DISTINCT room_number) as total FROM room_details')
            res = cur.fetchone()
            total_rooms = res['total'] if res else 579

            # 步骤 2: 获取合同记录
            # 逻辑：查询 check_in_date <= 查询结束时间 AND check_out_date >= 查询开始时间
            query_sql = """
                SELECT room_number, check_in_date, check_out_date
                FROM contract_creation_log
                WHERE check_in_date <= %s 
                AND check_out_date >= %s
            """
            cur.execute(query_sql, (end_date, start_date))
            raw_records = cur.fetchall()

    except Exception as e:
        logger.error(f"数据库查询失败: {e}")
        return f"数据库查询失败: {str(e)}"

    # 步骤 3: 数据预处理
    contracts = []
    for r in raw_records:
        c_in = r['check_in_date']
        c_out = r['check_out_date']
        if isinstance(c_in, datetime.datetime): c_in = c_in.date()
        if isinstance(c_out, datetime.datetime): c_out = c_out.date()
        
        contracts.append({
            'room': r['room_number'],
            'start': c_in,
            'end': c_out
        })

    # -------------------------------------------------------
    # 核心计算
    # -------------------------------------------------------

    result_data = {}

    if calc_method == 'period_avg':
        # --- 模式 A: 期间加权平均 (Period Weighted Average) ---
        # 公式: ∑(每天的占用数) / (总房间数 * 天数)
        # 适用于财务报表、经营分析

        total_days = (end_date - start_date).days + 1
        total_avail_nights = total_rooms * total_days

        total_occ_nights = 0
        total_app_nights = 0 # 广义占用(含预定)

        current_date = start_date
        while current_date <= end_date:
            daily_occ = set()
            daily_res = set()

            for c in contracts:
                if c['start'] <= current_date < c['end']:
                    daily_occ.add(c['room'])
                elif current_date < c['start']:
                    daily_res.add(c['room'])

            # 使用set并集防止重复统计，比如家庭入住一个房间号对应多条记录的情况
            total_occ_nights += len(daily_occ)
            total_app_nights += len(daily_occ | daily_res)

            current_date += datetime.timedelta(days=1)

        result_data = {
            'type': '期间加权平均 (Period Average)',
            'range': f"{start} 至 {end} ({total_days} 天)",
            'total_avail': total_avail_nights,
            'val_occ': total_occ_nights,
            'val_app': total_app_nights,
            'rate_occ': (total_occ_nights / total_avail_nights * 100) if total_avail_nights else 0,
            'rate_app': (total_app_nights / total_avail_nights * 100) if total_avail_nights else 0
        }

    else:
        # --- 模式 B: 期末时点 (End Point Snapshot) ---
        # 公式: 结束日当天的占用数 / 总房间数
        # 适用于运营查房、销售看库存

        # 只需要计算 end_date 这一天
        target_date = end_date

        snapshot_occ = set()
        snapshot_res = set()

        for c in contracts:
            if c['start'] <= target_date < c['end']:
                snapshot_occ.add(c['room'])
            elif target_date < c['start']:
                snapshot_res.add(c['room'])

        occ_count = len(snapshot_occ)
        app_count = len(snapshot_occ | snapshot_res)

        result_data = {
            'type': '期末时点 (End Point Snapshot)',
            'range': f"时点: {end}",
            'total_avail': total_rooms, # 分母是房间数，不是房晚数
            'val_occ': occ_count,
            'val_app': app_count,
            'rate_occ': (occ_count / total_rooms * 100) if total_rooms else 0,
            'rate_app': (app_count / total_rooms * 100) if total_rooms else 0
        }

    # 步骤 4: 格式化输出
    return _format_result(result_data, total_rooms)

def _format_result(data, total_rooms):
    lines = []
    lines.append(f"--- 出租率计算报告 [{data['type']}] ---")
    lines.append(f"统计范围: {data['range']}")
    lines.append(f"总房间数: {total_rooms}")

    if '加权' in data['type']:
        lines.append(f"总可用房晚: {data['total_avail']:,}")
        lines.append(f"实际占有用房晚: {data['val_occ']:,}")
        lines.append("-" * 30)
        lines.append(f"实际入住率 (Occupancy): {data['rate_occ']:.2f}%")
        lines.append(f"广义出租率 (Application): {data['rate_app']:.2f}%")
        lines.append("(注: 广义出租率包含已签约但未入住的预定)")
    else:
        lines.append("-" * 30)
        lines.append(f"当前在住房间数: {data['val_occ']}")
        lines.append(f"广义占用房间数: {data['val_app']} (含预定)")
        lines.append("-" * 30)
        lines.append(f"即时入住率: {data['rate_occ']:.2f}%")
        lines.append(f"即时出租率: {data['rate_app']:.2f}%")

    return "\n".join(lines)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    print(">>> 调试 utils/occupancy.py <<<")

    # 测试1: 期间平均
    print("\n[测试1: 8月期间平均]")
    print(calculate_occupancy_logic("2025-08-01", "2025-08-31", "period_avg"))

    # 测试2: 期末时点
    print("\n[测试2: 8月31日时点]")
    print(calculate_occupancy_logic("2025-08-01", "2025-08-31", "end_point"))

    # 测试1: 期间平均
    print("\n[测试1: 9月期间平均]")
    print(calculate_occupancy_logic("2025-09-01", "2025-09-30", "period_avg"))

    # 测试2: 期末时点
    print("\n[测试2: 9月30日时点]")
    print(calculate_occupancy_logic("2025-09-01", "2025-09-30", "end_point"))