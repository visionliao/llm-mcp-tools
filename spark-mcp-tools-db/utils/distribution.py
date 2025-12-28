import sys
import os
import logging
import datetime
from typing import Optional, List, Dict, Any
from collections import defaultdict

try:
    from .db import get_db_cursor
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor

logger = logging.getLogger("DistributionLogic")

def query_distribution_report_logic(
        start_date_str: Optional[str] = None,
        end_date_str: Optional[str] = None,
) -> str:
    """
    生成工单分布统计报告。
    """
    logger.info(f"生成分布报告: {start_date_str} 至 {end_date_str}")

    params = []
    conditions = ["1=1"]

    # 1. 日期处理
    criteria_time = "不限"
    if start_date_str:
        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            conditions.append("created_at >= %s")
            params.append(start_date)
        except ValueError:
            return "日期格式错误"
    
    if end_date_str:
        try:
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            next_day = end_date + datetime.timedelta(days=1)
            conditions.append("created_at < %s")
            params.append(next_day)
        except ValueError:
            return "日期格式错误"
    
    if start_date_str or end_date_str:
        criteria_time = f"{start_date_str or '不限'} 至 {end_date_str or '不限'}"

    where_clause = " AND ".join(conditions)

    try:
        with get_db_cursor() as cur:
            # -------------------------------------------------------
            # A. 总体计数
            # -------------------------------------------------------
            cur.execute(f"SELECT count(*) as total FROM work_orders WHERE {where_clause}", tuple(params))
            total_count = cur.fetchone()['total']
            
            if total_count == 0:
                return f"在 {criteria_time} 期间未找到任何工单数据。"

            # -------------------------------------------------------
            # B. 各维度 Top 统计
            # -------------------------------------------------------
            # 辅助函数：执行分组查询
            def get_top_stats(field, limit=3):
                sql = f"""
                    SELECT {field} as name, count(*) as count 
                    FROM work_orders 
                    WHERE {where_clause} 
                    AND {field} IS NOT NULL AND {field} != ''
                    GROUP BY {field} 
                    ORDER BY count DESC 
                    LIMIT {limit}
                """
                cur.execute(sql, tuple(params))
                return cur.fetchall()

            # 1. Top 服务项目
            top_services = get_top_stats('service_item')
            
            # 2. Top 位置 (area + location)
            sql_loc = f"""
                SELECT CONCAT(area, ' ', location) as name, count(*) as count 
                FROM work_orders 
                WHERE {where_clause} 
                GROUP BY area, location 
                ORDER BY count DESC 
                LIMIT 3
            """
            cur.execute(sql_loc, tuple(params))
            top_locations = cur.fetchall()

            # 3. 楼栋与楼层提取 (修复正则转义问题 \\d)
            
            # Top 楼栋
            sql_building = f"""
                SELECT 
                    substring(room_number from '^([A-Z])') as name, 
                    count(*) as count
                FROM work_orders
                WHERE {where_clause} AND room_number ~ '^[A-Z]'
                GROUP BY 1
                ORDER BY count DESC
                LIMIT 3
            """
            cur.execute(sql_building, tuple(params))
            top_buildings = cur.fetchall()

            # Top 楼层
            # 修复：使用 \\d 转义，且 Select 中返回文本以便展示
            sql_floor = f"""
                SELECT 
                    (substring(room_number from '^[A-Z](\\d+)')::int / 100)::text || '楼' as name,
                    count(*) as count
                FROM work_orders
                WHERE {where_clause} AND room_number ~ '^[A-Z]\\d{{3,}}'
                GROUP BY 1
                ORDER BY count DESC
                LIMIT 3
            """
            cur.execute(sql_floor, tuple(params))
            top_floors = cur.fetchall()

            # -------------------------------------------------------
            # C. 时间分布统计
            # -------------------------------------------------------
            
            # 按年
            sql_year = f"SELECT to_char(created_at, 'YYYY') as name, count(*) as count FROM work_orders WHERE {where_clause} GROUP BY 1 ORDER BY 1"
            cur.execute(sql_year, tuple(params))
            dist_year = cur.fetchall()

            # 按月
            sql_month = f"SELECT to_char(created_at, 'YYYY-MM') as name, count(*) as count FROM work_orders WHERE {where_clause} GROUP BY 1 ORDER BY 1"
            cur.execute(sql_month, tuple(params))
            dist_month = cur.fetchall()

            # 按周
            sql_week = f"SELECT to_char(created_at, 'IYYY-IW') as name, count(*) as count FROM work_orders WHERE {where_clause} GROUP BY 1 ORDER BY 1"
            cur.execute(sql_week, tuple(params))
            dist_week = cur.fetchall()

            # 按星期
            sql_dow = f"SELECT extract(dow from created_at) as dow, count(*) as count FROM work_orders WHERE {where_clause} GROUP BY 1 ORDER BY 1"
            cur.execute(sql_dow, tuple(params))
            dist_dow = {int(row['dow']): row['count'] for row in cur.fetchall()}

            # 按时段
            sql_hour = f"""
                SELECT 
                    CASE 
                        WHEN extract(hour from created_at) BETWEEN 0 AND 6 THEN '深夜 (00:00-06:59)'
                        WHEN extract(hour from created_at) BETWEEN 7 AND 11 THEN '上午 (07:00-11:59)'
                        WHEN extract(hour from created_at) BETWEEN 12 AND 13 THEN '午间 (12:00-13:59)'
                        WHEN extract(hour from created_at) BETWEEN 14 AND 17 THEN '下午 (14:00-17:59)'
                        ELSE '夜间 (18:00-23:59)'
                    END as name,
                    count(*) as count
                FROM work_orders
                WHERE {where_clause}
                GROUP BY 1
                ORDER BY count DESC
            """
            cur.execute(sql_hour, tuple(params))
            dist_segment = cur.fetchall()

            # -------------------------------------------------------
            # D. 层级详细分布 (修复 ORDER BY 错误)
            # -------------------------------------------------------
            # 修复点：
            # 1. 正则表达式改为 \\d
            # 2. SELECT 中直接计算 integer 类型的 floor，不要转 text
            # 3. ORDER BY 直接使用列位置索引 (1, 2, 3, 4)
            sql_hierarchy = f"""
                SELECT 
                    substring(room_number from '^([A-Z])') as building,
                    (substring(room_number from '^[A-Z](\\d+)')::int / 100) as floor,
                    CONCAT(area, ' ', location) as loc,
                    service_item,
                    count(*) as count
                FROM work_orders
                WHERE {where_clause} 
                AND room_number ~ '^[A-Z]\\d{{3,}}'
                GROUP BY 1, 2, 3, 4
                ORDER BY 1, 2, 3, 4
            """
            cur.execute(sql_hierarchy, tuple(params))
            hierarchy_rows = cur.fetchall()

            # -------------------------------------------------------
            # 格式化输出
            # -------------------------------------------------------
            report = []
            
            # Part 1: 总体总结
            report.append("==================================================")
            report.append("--- 总体数据总结 ---")
            report.append(f"查询范围内总工单数: {total_count} 条\n")
            
            report.append(_format_top_section("Top 3 工单项目", top_services, total_count))
            report.append(_format_top_section("Top 3 工单位置", top_locations, total_count))
            report.append(_format_top_section("Top 3 楼层分布", top_floors, total_count))
            report.append(_format_top_section("Top 3 楼栋分布", top_buildings, total_count))

            # Part 2: 时间分布
            report.append("==================================================")
            report.append("--- 工单创建时间分布报告 ---")
            report.append("==================================================\n")
            
            report.append(_format_time_section("按年份分布", dist_year, total_count))
            report.append(_format_time_section("按月份分布", dist_month, total_count))
            report.append(_format_time_section("按周数分布", dist_week, total_count))
            
            week_days = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
            report.append("[ 按星期内的日分布 (周日至周六) ]")
            for i, day_name in enumerate(week_days):
                count = dist_dow.get(i, 0)
                pct = (count / total_count * 100) if total_count else 0
                report.append(f"  - {day_name}: {count} 次 ({pct:.1f}%)")
            report.append("")

            report.append(_format_time_section("按天内时段分布", dist_segment, total_count))

            # Part 3: 详细层级分布
            report.append("==================================================")
            report.append("--- 服务工单分布情况详细报告 ---")
            report.append(_format_hierarchy_report(hierarchy_rows))
            report.append("==================================================")

            return "\n".join(report)

    except Exception as e:
        logger.error(f"分布报告生成失败: {e}")
        return f"数据库查询出错: {str(e)}"

def _format_top_section(title, data, total):
    lines = [f"--- {title} ---"]
    if not data:
        lines.append("  无数据")
    else:
        for i, row in enumerate(data, 1):
            name = row['name'] or "未知"
            count = row['count']
            pct = (count / total * 100) if total else 0
            lines.append(f"  {i}. {name}: {count} 次 ({pct:.1f}%)")
    lines.append("")
    return "\n".join(lines)

def _format_time_section(title, data, total):
    lines = [f"[ {title} ]"]
    if not data:
        lines.append("  无数据")
    else:
        for row in data:
            count = row['count']
            pct = (count / total * 100) if total else 0
            lines.append(f"  - {row['name']}: {count} 次 ({pct:.1f}%)")
    lines.append("")
    return "\n".join(lines)

def _format_hierarchy_report(rows):
    if not rows:
        return "\n  无详细层级数据"
    
    # 构建树状结构
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        b = r['building'] or "其他"
        # 数据库返回的是整数 floor，这里加 "楼"
        f = f"{r['floor']}楼" if r['floor'] is not None else "未知楼层"
        l = r['loc'] or "未知位置"
        tree[b][f][l].append((r['service_item'], r['count']))
    
    lines = []
    # 楼栋排序
    for b_name in sorted(tree.keys()):
        lines.append(f"\n[ 栋座: {b_name} ]")
        
        # 楼层排序: 提取数字部分进行排序 (10楼 > 2楼)
        def floor_key(f_str):
            num_part = ''.join(filter(str.isdigit, f_str))
            return int(num_part) if num_part else -1
            
        floors = sorted(tree[b_name].keys(), key=floor_key)
        
        for f_name in floors:
            lines.append(f"  [ 楼层: {f_name} ]")
            for l_name, items in tree[b_name][f_name].items():
                lines.append(f"    ● 位置: {l_name}")
                for s_item, count in items:
                    lines.append(f"      - {s_item or '未知服务'}: {count} 次")
    
    return "\n".join(lines)

# ==========================================
# Main 调试
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(">>> 调试 utils/distribution.py <<<")
    
    # 场景 1: 2024 全年数据
    print("\n--- 测试 1: 2024 全年数据 ---")
    print(query_distribution_report_logic(
        start_date_str="2024-01-01",
        end_date_str="2024-12-31"
    ))