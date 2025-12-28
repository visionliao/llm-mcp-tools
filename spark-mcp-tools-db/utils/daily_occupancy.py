import datetime
import logging
import sys
import os

try:
    from .db import get_db_cursor
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor

logger = logging.getLogger("DailyOccupancy")

VALID_METHODS = {'period_avg', 'end_point'}

def analyze_occupancy_logic(start: str, end: str, calc_method: str = 'period_avg') -> str:
    """
    全能经营分析逻辑：支持全维度极值（坪效/日租/月租）挖掘。
    """
    logger.info(f"经营分析: {start} 至 {end}, 模式: {calc_method}")

    # 1. 参数验证
    try:
        start_date = datetime.datetime.strptime(start, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end, '%Y-%m-%d').date()
    except ValueError:
        return "输入错误：日期格式不正确，请使用 'YYYY-MM-DD' 格式。"

    if start_date > end_date:
        return "输入错误：开始日期不能晚于结束日期。"

    if calc_method not in VALID_METHODS:
        return "输入错误：计算方式仅支持 'period_avg' 或 'end_point'。"

    sql_start = start_date if calc_method == 'period_avg' else end_date
    sql_end = end_date
    
    days_count = (sql_end - sql_start).days + 1
    range_desc = f"{sql_start} 至 {sql_end} (共 {days_count} 天)"

    try:
        with get_db_cursor() as cur:
            # =======================================================
            # Part A: 聚合统计 (总数、平均数)
            # =======================================================
            sql_agg = """
                SELECT 
                    COALESCE(rd.room_code, 'ALL_TOTAL') as code,
                    MAX(rd.room_code_desc) as name, 
                    COUNT(*) as total_capacity,       -- 总房晚 / 总库存
                    SUM(CASE WHEN d.status = 'I' THEN 1 ELSE 0 END) as occ_units,
                    
                    -- [新增] 统计实际出租面积 (在住状态下的房间面积之和)
                    SUM(CASE WHEN d.status = 'I' THEN rd.area_sqm ELSE 0 END) as total_occ_area,
                    
                    SUM(d.daily_rent) as total_revenue,
                    -- 平均坪效 (仅统计在住天数)
                    AVG(CASE WHEN d.status = 'I' THEN d.rent_per_sqm END) as avg_yield
                FROM room_occupancy_daily d
                LEFT JOIN room_details rd ON d.room_number = rd.room_number
                WHERE d.stat_date BETWEEN %s AND %s
                GROUP BY GROUPING SETS ((rd.room_code), ())
                ORDER BY code
            """
            cur.execute(sql_agg, (sql_start, sql_end))
            agg_rows = cur.fetchall()

            # =======================================================
            # Part B: 全维度极值挖掘
            # =======================================================
            sql_extremes = """
                WITH Ranked AS (
                    SELECT 
                        rd.room_code,
                        d.room_number,
                        rd.area_sqm,
                        d.monthly_rent,
                        d.daily_rent,
                        d.rent_per_sqm,
                        
                        -- 坪效极值
                        ROW_NUMBER() OVER (PARTITION BY rd.room_code ORDER BY d.rent_per_sqm DESC) as rn_max_yield,
                        ROW_NUMBER() OVER (PARTITION BY rd.room_code ORDER BY d.rent_per_sqm ASC) as rn_min_yield,
                        
                        -- 日租金极值
                        ROW_NUMBER() OVER (PARTITION BY rd.room_code ORDER BY d.daily_rent DESC) as rn_max_daily,
                        ROW_NUMBER() OVER (PARTITION BY rd.room_code ORDER BY d.daily_rent ASC) as rn_min_daily,
                        
                        -- 月租金极值
                        ROW_NUMBER() OVER (PARTITION BY rd.room_code ORDER BY d.monthly_rent DESC) as rn_max_monthly,
                        ROW_NUMBER() OVER (PARTITION BY rd.room_code ORDER BY d.monthly_rent ASC) as rn_min_monthly
                        
                    FROM room_occupancy_daily d
                    LEFT JOIN room_details rd ON d.room_number = rd.room_number
                    WHERE d.stat_date BETWEEN %s AND %s 
                      AND d.status = 'I' 
                      AND d.daily_rent > 0
                )
                SELECT * FROM Ranked 
                WHERE rn_max_yield = 1 OR rn_min_yield = 1
                   OR rn_max_daily = 1 OR rn_min_daily = 1
                   OR rn_max_monthly = 1 OR rn_min_monthly = 1
            """
            cur.execute(sql_extremes, (sql_start, sql_end))
            extreme_rows = cur.fetchall()
            
            # 组织极值数据
            extremes_map = {}
            for r in extreme_rows:
                code = r['room_code']
                if code not in extremes_map: extremes_map[code] = {}
                
                if r['rn_max_yield'] == 1: extremes_map[code]['max_yield'] = r
                if r['rn_min_yield'] == 1: extremes_map[code]['min_yield'] = r
                if r['rn_max_daily'] == 1: extremes_map[code]['max_daily'] = r
                if r['rn_min_daily'] == 1: extremes_map[code]['min_daily'] = r
                if r['rn_max_monthly'] == 1: extremes_map[code]['max_monthly'] = r
                if r['rn_min_monthly'] == 1: extremes_map[code]['min_monthly'] = r

            # =======================================================
            # Part C: 总房间数
            # =======================================================
            cur.execute("SELECT room_code, count(*) as cnt FROM room_details GROUP BY room_code")
            room_counts = {r['room_code']: r['cnt'] for r in cur.fetchall()}
            total_rooms = sum(room_counts.values())

            return _format_strict_report(agg_rows, extremes_map, room_counts, total_rooms, range_desc, calc_method)

    except Exception as e:
        logger.error(f"分析失败: {e}")
        return f"数据库查询出错: {str(e)}"

def _format_strict_report(agg_rows, extremes_map, room_counts, total_rooms, range_desc, calc_method):
    """
    严格按照用户要求的格式输出。
    """
    lines = []
    
    # 定义租金统计的文案
    revenue_label = "期间总租金" if calc_method == 'period_avg' else "当日总租金"
    
    # --- 1. 计算全局极值 (Overall Extremes) ---
    overall_ext = {
        'max_yield': None, 'min_yield': None,
        'max_daily': None, 'min_daily': None,
        'max_monthly': None, 'min_monthly': None
    }
    
    for code_data in extremes_map.values():
        for key in overall_ext.keys():
            curr = code_data.get(key)
            if curr:
                current_best = overall_ext[key]
                # Max 逻辑
                if 'max' in key:
                    field = 'rent_per_sqm' if 'yield' in key else ('daily_rent' if 'daily' in key else 'monthly_rent')
                    if not current_best or curr[field] > current_best[field]:
                        overall_ext[key] = curr
                # Min 逻辑
                else:
                    field = 'rent_per_sqm' if 'yield' in key else ('daily_rent' if 'daily' in key else 'monthly_rent')
                    if not current_best or curr[field] < current_best[field]:
                        overall_ext[key] = curr

    # --- 2. 总体概况输出 ---
    overall_stats = next((r for r in agg_rows if r['code'] == 'ALL_TOTAL'), None)
    
    lines.append(f"统计范围: {range_desc}")
    lines.append(f"总房间数: {total_rooms} 间")
    
    if overall_stats:
        occ = overall_stats['occ_units']
        total = overall_stats['total_capacity']
        revenue = float(overall_stats['total_revenue'] or 0)
        
        # [新增] 总体面积和坪效
        total_occ_area = float(overall_stats['total_occ_area'] or 0)
        overall_avg_yield = float(overall_stats['avg_yield'] or 0)
        
        occ_rate = (occ / total * 100) if total else 0
        vac_rate = 100 - occ_rate
        
        lines.append(f"总可用房晚：{total:,}")
        lines.append(f"实际在住房晚: {occ:,}")
        lines.append(f"出租率 (Occ): {occ_rate:.2f}%")
        lines.append(f"空置率 (Vac): {vac_rate:.2f}%")
        
        lines.append(f"{revenue_label}: {revenue:,.2f}")
        # [新增] 总体面积和坪效行
        lines.append(f"总出租面积: {total_occ_area:,.2f} m²  平均坪效: {overall_avg_yield:.2f} 元/m²/日")
        
        # 全局极值输出
        lines.extend(_get_extreme_lines(overall_ext))
    
    lines.append("\n\n--- 各户型详细表现 ---")
    
    # --- 3. 分户型输出 ---
    type_data = [r for r in agg_rows if r['code'] != 'ALL_TOTAL']
    
    for r in type_data:
        code = r['code']
        name = r['name'] or code
        count = room_counts.get(code, 0)
        
        occ = r['occ_units']
        total = r['total_capacity']
        type_revenue = float(r['total_revenue'] or 0)
        
        # [新增] 户型面积和坪效
        type_occ_area = float(r['total_occ_area'] or 0)
        type_avg_yield = float(r['avg_yield'] or 0)
        
        occ_rate = (occ / total * 100) if total else 0
        vac_rate = 100 - occ_rate
        
        lines.append(f"[{name}] (共 {count} 间)")
        lines.append(f"总可用房晚：{total:,}")
        lines.append(f"实际在住房晚: {occ:,}")
        lines.append(f"出租率 (Occ): {occ_rate:.2f}%")
        lines.append(f"空置率 (Vac): {vac_rate:.2f}%")
        
        lines.append(f"{revenue_label}: {type_revenue:,.2f}")
        # [新增] 户型面积和坪效行
        lines.append(f"总出租面积: {type_occ_area:,.2f} m²  平均坪效: {type_avg_yield:.2f} 元/m²/日")
        
        # 该户型的极值
        type_ext = extremes_map.get(code, {})
        lines.extend(_get_extreme_lines(type_ext))
        lines.append("") # 户型间空行

    return "\n".join(lines).strip()

def _get_extreme_lines(ext_data):
    """辅助函数：生成标准的极值文本块"""
    lines = []
    
    # 坪效
    m = ext_data.get('max_yield')
    val = f"{float(m['rent_per_sqm']):.2f}" if m else "N/A"
    room = m['room_number'] if m else "-"
    area = float(m['area_sqm']) if m else 0
    lines.append(f"坪效最高房间：{room}，面积：{area}，坪效：{val}")
    
    m = ext_data.get('min_yield')
    val = f"{float(m['rent_per_sqm']):.2f}" if m else "N/A"
    room = m['room_number'] if m else "-"
    area = float(m['area_sqm']) if m else 0
    lines.append(f"坪效最低房间：{room}，面积：{area}，坪效：{val}")
    
    # 日租金
    m = ext_data.get('max_daily')
    val = f"{float(m['daily_rent']):.2f}" if m else "N/A"
    room = m['room_number'] if m else "-"
    area = float(m['area_sqm']) if m else 0
    lines.append(f"日租金最高房间: {room}，面积：{area}，日租金：{val}")
    
    # 月租金
    m = ext_data.get('max_monthly')
    val = f"{float(m['monthly_rent']):.2f}" if m else "N/A"
    room = m['room_number'] if m else "-"
    area = float(m['area_sqm']) if m else 0
    lines.append(f"月租金最高房间：{room}，面积：{area}，月租金：{val}")
    
    # 日租金最低
    m = ext_data.get('min_daily')
    val = f"{float(m['daily_rent']):.2f}" if m else "N/A"
    room = m['room_number'] if m else "-"
    area = float(m['area_sqm']) if m else 0
    lines.append(f"日租金最低房间: {room}，面积：{area}，日租金：{val}")
    
    # 月租金最低
    m = ext_data.get('min_monthly')
    val = f"{float(m['monthly_rent']):.2f}" if m else "N/A"
    room = m['room_number'] if m else "-"
    area = float(m['area_sqm']) if m else 0
    lines.append(f"月租金最低房间：{room}，面积：{area}，月租金：{val}")
    
    return lines


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(">>> 调试 utils/daily_occupancy.py <<<")
    # 测试输出格式
    print(analyze_occupancy_logic("2025-11-01", "2025-11-30", "period_avg"))

    print("\n>>> 测试 EndPoint <<<")
    #print(analyze_occupancy_logic("2025-08-01", "2025-08-31", "end_point"))