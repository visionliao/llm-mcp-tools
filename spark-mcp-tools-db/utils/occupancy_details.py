import datetime
import logging
import sys
import os
from collections import defaultdict

# 导入处理
try:
    from .db import get_db_cursor
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor

logger = logging.getLogger("RoomStats")

# 定义合法的计算方式
VALID_METHODS = {'period_avg', 'end_point'}

def get_occupancy_details_logic(start_time: str, end_time: str, calc_method: str = 'period_avg') -> str:
    """
    获取指定时间段内各房型的经营表现。
    基于物理房间（Room Number）进行时间并集去重，防止多份合同导致房晚数虚高，比如一个房间多人入住会存在多条记录。
    """
    logger.info(f"执行户型分析: {start_time} 至 {end_time}")

    try:
        start_date = datetime.datetime.strptime(start_time, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end_time, '%Y-%m-%d').date()
    except ValueError:
        return "输入错误：日期格式不正确，请使用 'YYYY-MM-DD' 格式。"

    if start_date > end_date:
        return "输入错误：开始日期不能晚于结束日期。"

    # 查询期间的总天数
    period_days = (end_date - start_date).days + 1

    try:
        with get_db_cursor() as cur:
            # 1. 获取所有房型元数据
            cur.execute("SELECT room_code, room_code_desc, area_sqm, room_count FROM dim_room_type")
            room_meta = {
                rt['room_code']: {
                    'desc': rt['room_code_desc'],
                    'area': float(rt['area_sqm']) if rt['area_sqm'] else 0,
                    'count': int(rt['room_count']) if rt['room_count'] else 0
                } for rt in cur.fetchall()
            }

            # 2. 获取合同数据 (包含已计算好的 rent_per_sqm)
            # 查询与时间段有交集的所有合同
            query_sql = """
                SELECT contract_no, room_number, room_code, actual_monthly_rent, rent_per_sqm, check_in_date, check_out_date
                FROM contract_creation_log
                WHERE check_in_date < %s 
                AND check_out_date > %s
            """
            cur.execute(query_sql, (end_date, start_date))
            all_contracts = cur.fetchall()

    except Exception as e:
        logger.error(f"Database Query Error: {e}")
        return f"数据库查询出错: {e}"

    # -------------------------------------------------------
    # 核心计算逻辑：按房间去重
    # -------------------------------------------------------

    # 1. 将合同按房型 -> 房号 分组
    # 结构: contracts_by_room[room_code][room_number] = [contract1, contract2...]
    contracts_by_room = defaultdict(lambda: defaultdict(list))

    for c in all_contracts:
        r_code = c['room_code']
        r_no = c['room_number']
        contracts_by_room[r_code][r_no].append(c)

    analysis_results = []
    sorted_codes = sorted(room_meta.keys())

    for code in sorted_codes:
        meta = room_meta[code]
        rooms_data = contracts_by_room.get(code, {})

        # 初始化房型统计累加器
        type_stats = {
            # Period Metrics
            'total_occ_nights': 0,      # 物理入住总房晚 (去重后)
            'total_revenue': 0.0,       # 总营收 (租金可叠加)
            'weighted_yield_sum': 0.0,  # [期间] 坪效加权和 (坪效 * 天数)

            # EndPoint Metrics
            'end_occ_count': 0,         # 期末在租房间数 (去重后)
            'end_paid_count': 0,        # 期末付费房间数
            'end_point_revenue': 0.0,   # 期末时点的月租金总和 (Run Rate)
            'end_point_yield_sum': 0.0, # [期末] 坪效和 (直接累加)

            # Extremes
            'max_rent': None,
            'min_rent': None
        }

        valid_contracts_for_extremes = [] # 用于找最大最小租金

        # 遍历该房型下的每一个物理房间 (进行房间级聚合)
        for r_no, r_contracts in rooms_data.items():

            # --- 房间级变量 ---
            room_occupied_dates = set() # 使用集合存储该房间被占用的具体日期，实现去重
            is_occupied_at_end = False
            is_paid_at_end = False
            room_end_revenue = 0.0
            room_end_yield = 0.0

            for c in r_contracts:
                c_in = c['check_in_date'] if isinstance(c['check_in_date'], datetime.date) else c['check_in_date'].date()
                c_out = c['check_out_date'] if isinstance(c['check_out_date'], datetime.date) else c['check_out_date'].date()
                monthly_rent = float(c['actual_monthly_rent'] or 0)
                per_sqm = float(c['rent_per_sqm'] or 0)

                # A. 计算并集日期 & 累加营收
                # 计算合同与查询区间的交集
                overlap_start = max(start_date, c_in)
                # end_date + 1 是因为 range 是左闭右开，且离店日通常不算住
                # 但为了精确计算 date set，我们取 min(end_date + 1, c_out)
                overlap_end = min(end_date + datetime.timedelta(days=1), c_out)

                # 将每一天加入集合
                curr = overlap_start
                while curr < overlap_end:
                    room_occupied_dates.add(curr)
                    curr += datetime.timedelta(days=1)

                # 营收计算：(月租/30) * 重叠天数
                # 注意：营收是不用去重的，两个人住就要付两份钱
                overlap_days = (overlap_end - overlap_start).days
                if overlap_days > 0:
                    contract_revenue = (monthly_rent / 30.0) * overlap_days
                    type_stats['total_revenue'] += contract_revenue

                    # 坪效累加 (按合同贡献)：坪效 * 天数
                    type_stats['weighted_yield_sum'] += per_sqm * overlap_days

                    if monthly_rent > 0:
                        valid_contracts_for_extremes.append(c)

                # B. 判断期末状态 (end_date 当天是否在住)
                if c_in <= end_date < c_out:
                    is_occupied_at_end = True
                    if monthly_rent > 0:
                        is_paid_at_end = True
                        room_end_revenue += monthly_rent
                        room_end_yield += per_sqm

            # --- 房间级汇总结束 ---
            # 将该房间的去重房晚数加入房型总数
            type_stats['total_occ_nights'] += len(room_occupied_dates)

            if is_occupied_at_end:
                type_stats['end_occ_count'] += 1
                type_stats['end_point_revenue'] += room_end_revenue
                type_stats['end_point_yield_sum'] += room_end_yield
            if is_paid_at_end:
                type_stats['end_paid_count'] += 1

        # --- 房型级指标计算 ---

        # 找极值
        if valid_contracts_for_extremes:
            max_c = max(valid_contracts_for_extremes, key=lambda x: float(x['actual_monthly_rent'] or 0))
            min_c = min(valid_contracts_for_extremes, key=lambda x: float(x['actual_monthly_rent'] or 0))
            type_stats['max_rent'] = _format_rent_record(max_c)
            type_stats['min_rent'] = _format_rent_record(min_c)

        total_supply = meta['count']

        # 1. 期间指标
        avg_adr = (type_stats['total_revenue'] / type_stats['total_occ_nights']) if type_stats['total_occ_nights'] > 0 else 0.0
        # [修复] 期间平均坪效 = 加权总和 / 总实际房晚
        period_avg_yield = (type_stats['weighted_yield_sum'] / type_stats['total_occ_nights']) if type_stats['total_occ_nights'] > 0 else 0.0
        
        total_avail_nights = total_supply * period_days
        safe_occ_nights = min(type_stats['total_occ_nights'], total_avail_nights)
        period_vac_rate = ((total_avail_nights - safe_occ_nights) / total_avail_nights * 100) if total_avail_nights > 0 else 100.0
        
        # 2. 期末指标
        end_vac_rate = ((total_supply - type_stats['end_occ_count']) / total_supply * 100) if total_supply > 0 else 100.0
        end_avg_monthly_rent = (type_stats['end_point_revenue'] / type_stats['end_paid_count']) if type_stats['end_paid_count'] > 0 else 0.0
        # [修复] 期末平均坪效 = 坪效总和 / 期末在租房间数
        # 注意：坪效是基于在租房间计算的，空房不分母
        end_point_avg_yield = (type_stats['end_point_yield_sum'] / type_stats['end_occ_count']) if type_stats['end_occ_count'] > 0 else 0.0

        analysis_results.append({
            'name': meta['desc'],
            'total_supply': total_supply,
            'area': meta['area'],

            # Period Data
            'period_nights': safe_occ_nights,
            'period_vac_rate': period_vac_rate,
            'period_revenue': type_stats['total_revenue'],
            'period_adr': avg_adr,
            'period_yield': period_avg_yield, # 数据库字段加权

            # EndPoint Data
            'end_occ': type_stats['end_occ_count'],
            'end_paid': type_stats['end_paid_count'],
            'end_vac_rate': end_vac_rate,
            'end_revenue': type_stats['end_point_revenue'],
            'end_avg_rent': end_avg_monthly_rent,
            'end_yield': end_point_avg_yield, # 数据库字段平均

            'max_rent': type_stats['max_rent'],
            'min_rent': type_stats['min_rent']
        })

    return _format_occupancy_report(analysis_results, start_time, end_time, calc_method)

def _format_rent_record(record):
    return {
        'rent': float(record['actual_monthly_rent']),
        'id': str(record['contract_no']),
        'room': str(record['room_number']),
        'arr': record['check_in_date'],
        'dep': record['check_out_date']
    }

def _format_occupancy_report(results: list, start: str, end: str, calc_method: str) -> str:
    if not results:
        return f"在 {start} 至 {end} 期间未找到相关数据。"

    lines = []
    lines.append(f"--- 各户型经营表现分析 (数据范围: {start} 至 {end}) ---")

    total_revenue_accum = 0.0
    total_nights_accum = 0
    total_end_revenue_accum = 0.0
    total_end_paid_accum = 0

    for r in results:
        lines.append(f"\n==================== 户型: {r['name']} ====================")
        lines.append(f"总数: {r['total_supply']} 间 | 面积: {r['area']} m²")

        if calc_method == 'period_avg':
            lines.append(f"期间入住房晚: {r['period_nights']:,} 晚")
            lines.append(f"期间空置率  : {r['period_vac_rate']:.2f}%")
            lines.append(f"期间总营收  : {r['period_revenue']:,.2f} 元")
            lines.append(f"平均日租金(ADR): {r['period_adr']:,.2f} 元")
            lines.append(f"平均坪效    : {r['period_yield']:.2f} 元/m²/日") # 显示

            total_revenue_accum += r['period_revenue']
            total_nights_accum += r['period_nights']

        else:
            lines.append(f"期末在租数  : {r['end_occ']} 间 (空置 {r['end_vac_rate']:.2f}%)")
            lines.append(f"期末付费数  : {r['end_paid']} 间")
            lines.append(f"当前月租流水: {r['end_revenue']:,.2f} 元 (Run Rate)")
            lines.append(f"平均签约月租: {r['end_avg_rent']:,.2f} 元")
            lines.append(f"平均坪效    : {r['end_yield']:.2f} 元/m²/日") # 显示
            
            total_end_revenue_accum += r['end_revenue']
            total_end_paid_accum += r['end_paid']

        lines.append("---")

        for label, val in [("最高", r['max_rent']), ("最低", r['min_rent'])]:
            if val:
                lines.append(f"{label}月租金    : {val['rent']:,.2f} 元 (房间: {val['room']}, 合同: {val['id']})")
            else:
                lines.append(f"{label}月租金    : N/A")

    lines.append("\n==================== 总体概要 ====================")
    if calc_method == 'period_avg':
        avg_total_adr = (total_revenue_accum / total_nights_accum) if total_nights_accum > 0 else 0.0
        lines.append(f"全公寓期间总营收: {total_revenue_accum:,.2f} 元")
        lines.append(f"全公寓平均日租金: {avg_total_adr:,.2f} 元")
    else:
        avg_total_rent = (total_end_revenue_accum / total_end_paid_accum) if total_end_paid_accum > 0 else 0.0
        lines.append(f"全公寓当前月租流水: {total_end_revenue_accum:,.2f} 元")
        lines.append(f"全公寓平均签约月租: {avg_total_rent:,.2f} 元")

    lines.append("========================================================")

    return "\n".join(lines)

# ==========================================
# Main 调试
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(">>> 调试 utils/room_stats.py <<<")

    test_start = "2025-11-01"
    test_end = "2025-11-30"

    print("\n[模式: Period Avg]")
    print(get_occupancy_details_logic(test_start, test_end, "period_avg"))

    print("\n[模式: End Point]")
    print(get_occupancy_details_logic(test_start, test_end, "end_point"))