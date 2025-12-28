import sys
import os
import logging
import datetime
import re
from collections import defaultdict
from typing import Optional

try:
    from .db import get_db_cursor
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor

logger = logging.getLogger("WorkOrderLogic")

DETAIL_THRESHOLD = 10

def search_work_orders_logic(
        start_date_str: Optional[str] = None,
        end_date_str: Optional[str] = None,
        room_number: Optional[str] = None,
        service_code: Optional[str] = None,
        location_code: Optional[str] = None
) -> str:
    """
    通用工单查询与分析逻辑。
    <= 10 条: 返回详情。
    > 10 条: 返回深度统计报告 (Top榜 + 时间趋势 + 层级分布)。
    """
    logger.info(f"全能工单查询: Time=[{start_date_str}-{end_date_str}], Room={room_number}, Srv={service_code}")

    try:
        with get_db_cursor() as cur:
            # 1. 转换服务代码
            target_service_name = service_code
            if service_code:
                cur.execute("SELECT item_desc FROM dim_work_order_items WHERE item_code = %s", (service_code,))
                res = cur.fetchone()
                if res: target_service_name = res['item_desc']

            # 2. 转换位置代码
            target_loc_name = location_code
            if location_code:
                lookup_code = location_code
                if location_code.isdigit(): lookup_code = str(int(location_code))
                cur.execute("SELECT location_desc FROM dim_work_locations WHERE location_code::text = %s", (lookup_code,))
                res = cur.fetchone()
                if res: target_loc_name = res['location_desc']

            # 3. 构建查询条件
            params = []
            conditions = ["1=1"]
            criteria_desc_parts = []

            # 日期
            if start_date_str:
                try:
                    start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    conditions.append("created_at >= %s")
                    params.append(start_date)
                    criteria_desc_parts.append(f"开始于 {start_date_str}")
                except ValueError: return "日期格式错误"
            
            if end_date_str:
                try:
                    end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
                    next_day = end_date + datetime.timedelta(days=1)
                    conditions.append("created_at < %s")
                    params.append(next_day)
                    criteria_desc_parts.append(f"结束于 {end_date_str}")
                except ValueError: return "日期格式错误"

            # 房间号筛选
            if room_number:
                rooms = [r.strip() for r in re.split(r'[\s,]+', room_number) if r.strip()]
                if rooms:
                    conditions.append("room_number = ANY(%s)")
                    params.append(rooms)
                    criteria_desc_parts.append(f"房号[{','.join(rooms)}]")

            # 服务项目
            if target_service_name:
                conditions.append("service_item = %s")
                params.append(target_service_name)
                criteria_desc_parts.append(f"项目[{target_service_name}]")
            
            # 具体位置
            if target_loc_name:
                conditions.append("(area = %s OR location = %s)")
                params.append(target_loc_name)
                params.append(target_loc_name)
                criteria_desc_parts.append(f"位置[{target_loc_name}]")

            where_clause = " AND ".join(conditions)
            criteria_str = ", ".join(criteria_desc_parts) if criteria_desc_parts else "全量查询"

            # 4. 计数 & 分支
            count_sql = f"SELECT count(*) as total FROM work_orders WHERE {where_clause}"
            cur.execute(count_sql, tuple(params))
            total_count = cur.fetchone()['total']

            if total_count == 0:
                return f"查询条件: {criteria_str}\n结果: 未找到任何工单记录。"

            if total_count <= DETAIL_THRESHOLD:
                return _fetch_details(cur, where_clause, params, total_count, criteria_str)
            else:
                return _fetch_statistics(cur, where_clause, params, total_count, criteria_str)

    except Exception as e:
        logger.error(f"查询出错: {e}")
        return f"数据库查询出错: {str(e)}"

def _fetch_details(cur, where_clause, params, total_count, criteria_str):
    """【模式A】获取详细记录列表"""
    sql = f"""
        SELECT 
            work_order_no, room_number, service_item, order_type,
            area, location, applicant, contact_info, status, 
            expected_visit_date, expected_visit_time,
            created_by, created_at, updated_at
        FROM work_orders
        WHERE {where_clause}
        ORDER BY created_at DESC
    """
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()

    lines = []
    lines.append(f"--- 工单查询详情 ({criteria_str}) ---")
    lines.append(f"共找到 {total_count} 条记录。")
    lines.append("-" * 60)
    
    for i, row in enumerate(rows, 1):
        if row['room_number']:
            pos_info = f"房号: {row['room_number']}"
        else:
            pos_info = f"公区: {row['location'] or row['area'] or '未知区域'}"

        c_time = row['created_at'].strftime('%Y-%m-%d %H:%M') if row['created_at'] else "N/A"
        
        # 期望上门
        exp_date = str(row['expected_visit_date']) if row['expected_visit_date'] else ""
        exp_time = str(row['expected_visit_time']) if row['expected_visit_time'] else ""
        exp_full = f"{exp_date} {exp_time}".strip()
        
        lines.append(f"【{i}】 工单号: {row['work_order_no']}")
        lines.append(f"  位置: {pos_info}")
        lines.append(f"  项目: {row['service_item'] or '未知'} ({row['order_type'] or '-'})")
        lines.append(f"  状态: {row['status']} | 申请人: {row['applicant']}")
        if exp_full:
            lines.append(f"  期望上门: {exp_full}")
        lines.append(f"  时间: {c_time}")
        lines.append("-" * 60)

    return "\n".join(lines)

def _fetch_statistics(cur, where_clause, params, total_count, criteria_str):
    """【模式B】获取深度聚合统计信息 (整合了原 distribution 逻辑)"""
    lines = []
    lines.append(f"--- 工单深度统计报告 ({criteria_str}) ---")
    lines.append(f"总数据量: {total_count} 条 (已切换至统计视图)")
    lines.append("=" * 60)

    # ------------------------------------------
    # 1. 概览 Top 榜
    # ------------------------------------------
    srv_expr = "COALESCE(NULLIF(service_item, ''), '未知服务')"
    loc_expr = "COALESCE(NULLIF(room_number, ''), NULLIF(location, ''), NULLIF(area, ''), '其他区域')"

    # 1.1 维修内容 Top 5
    sql_srv = f"""
        SELECT {srv_expr} as name, count(*) as cnt 
        FROM work_orders WHERE {where_clause} 
        GROUP BY 1 ORDER BY cnt DESC LIMIT 5
    """
    cur.execute(sql_srv, tuple(params))
    srv_rows = cur.fetchall()
    
    lines.append("\n[维修项目 Top 5]")
    for r in srv_rows:
        pct = (r['cnt'] / total_count) * 100
        lines.append(f"  - {r['name']}: {r['cnt']} 次 ({pct:.1f}%)")

    # 1.2 报修位置 Top 5 (带详情)
    sql_room_top = f"""
        SELECT {loc_expr} as name, count(*) as cnt 
        FROM work_orders WHERE {where_clause} 
        GROUP BY 1 ORDER BY cnt DESC LIMIT 5
    """
    cur.execute(sql_room_top, tuple(params))
    room_rows = cur.fetchall()
    
    if room_rows:
        top_loc_names = [r['name'] for r in room_rows]
        sql_room_details = f"""
            SELECT 
                {loc_expr} as loc_name, {srv_expr} as srv_name, count(*) as cnt
            FROM work_orders
            WHERE {where_clause} AND {loc_expr} = ANY(%s)
            GROUP BY 1, 2
            ORDER BY loc_name, cnt DESC
        """
        cur.execute(sql_room_details, tuple(params + [top_loc_names]))
        detail_rows = cur.fetchall()
        
        loc_details_map = defaultdict(list)
        for d in detail_rows:
            loc_details_map[d['loc_name']].append(f"{d['srv_name']} {d['cnt']}次")
        
        lines.append("\n[报修频次最高位置]")
        for r in room_rows:
            details = loc_details_map.get(r['name'], [])
            detail_str = f" ({', '.join(details)})" if details else ""
            lines.append(f"  - {r['name']}: {r['cnt']} 次{detail_str}")

    # ------------------------------------------
    # 2. 时间分布 (年/月/周/时段)
    # ------------------------------------------
    lines.append("\n[时间分布]")
    
    # 按月
    sql_month = f"SELECT to_char(created_at, 'YYYY-MM') as name, count(*) as cnt FROM work_orders WHERE {where_clause} GROUP BY 1 ORDER BY 1"
    cur.execute(sql_month, tuple(params))
    month_rows = cur.fetchall()
    if len(month_rows) > 1: # 只有跨月才有意义显示
        lines.append("  按月: " + ", ".join([f"{r['name']}({r['cnt']})" for r in month_rows]))

    # 按时段
    sql_hour = f"""
        SELECT 
            CASE 
                WHEN extract(hour from created_at) BETWEEN 0 AND 6 THEN '深夜'
                WHEN extract(hour from created_at) BETWEEN 7 AND 11 THEN '上午'
                WHEN extract(hour from created_at) BETWEEN 12 AND 13 THEN '午间'
                WHEN extract(hour from created_at) BETWEEN 14 AND 17 THEN '下午'
                ELSE '夜间'
            END as name,
            count(*) as cnt
        FROM work_orders WHERE {where_clause} GROUP BY 1 ORDER BY cnt DESC
    """
    cur.execute(sql_hour, tuple(params))
    hour_rows = cur.fetchall()
    lines.append("  时段: " + ", ".join([f"{r['name']}({r['cnt']})" for r in hour_rows]))

    # ------------------------------------------
    # 3. 层级分布 (楼栋 -> 楼层)
    # ------------------------------------------
    # 仅当没有指定具体房间号时，显示楼栋分布才有意义
    sql_hierarchy = f"""
        SELECT 
            substring(room_number from '^([A-Z])') as building,
            (substring(room_number from '^[A-Z](\\d+)')::int / 100) as floor,
            count(*) as cnt
        FROM work_orders
        WHERE {where_clause} AND room_number ~ '^[A-Z]\\d{{3,}}'
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    cur.execute(sql_hierarchy, tuple(params))
    hier_rows = cur.fetchall()
    
    if hier_rows:
        lines.append("\n[楼栋楼层分布]")
        tree = defaultdict(list)
        for r in hier_rows:
            b = r['building']
            f = r['floor']
            tree[b].append(f"{f}楼({r['cnt']})")
        
        for b, floors in sorted(tree.items()):
            # 合并显示，避免太长
            lines.append(f"  - {b}栋: {', '.join(floors)}")

    return "\n".join(lines)


# ==========================================
# Main 调试
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(">>> 调试 utils/advanced_service.py <<<")
    print(search_work_orders_logic(room_number="A213,A212,A215,A1918"))

    # 场景1: 用代码查 (B102 -> 微波炉)
    print("--- 测试: 用代码 B102 (微波炉) ---")
    print(search_work_orders_logic(start_date_str="2025-01-01", end_date_str="2025-08-31"))

    # 场景2: 用代码查位置 (4 -> 厨房)
    print("\n--- 测试: 用代码 004 (厨房) ---")
    print(search_work_orders_logic(start_date_str="2025-08-01", end_date_str="2025-08-31", location_code="004"))

    print(search_work_orders_logic())
