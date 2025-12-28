import sys
import os
import re
import logging
from typing import Union, List

# ==========================================
# 导入处理
# ==========================================
try:
    from .db import get_db_cursor
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor

logger = logging.getLogger("OrdersLogic")

def query_orders_logic(room_number: str) -> str:
    """
    根据房间号查询历史工单信息。
    基于 work_orders 表。
    """
    # 1. 参数解析 (支持 "A513" 或 "A513, A514")
    room_list = [r.strip() for r in re.split(r'[\s,]+', room_number) if r.strip()]

    if not room_list:
        return "输入错误：未能解析出有效的房间号。"

    logger.info(f"正在查询房间工单: {room_list}")

    try:
        with get_db_cursor() as cur:
            # 2. SQL 查询
            # work_orders 表包含: work_order_no, order_type, area, location, service_item, status, created_at 等
            sql = """
                SELECT 
                    work_order_no,
                    room_number,
                    service_item,
                    order_type,
                    area,
                    location,
                    applicant,
                    contact_info,
                    expected_visit_date,
                    expected_visit_time,
                    status,
                    created_at,
                    updated_at,
                    created_by
                FROM work_orders
                WHERE room_number = ANY(%s)
                ORDER BY created_at DESC
            """
            
            cur.execute(sql, (room_list,))
            rows = cur.fetchall()

            if not rows:
                return f"未找到房间 {', '.join(room_list)} 的工单记录。"

            # 3. 格式化输出
            return _format_order_results(rows)

    except Exception as e:
        logger.error(f"查询工单失败: {e}")
        return f"数据库查询出错: {str(e)}"

def _format_order_results(rows):
    """格式化工单记录列表"""
    lines = []
    lines.append(f"--- 共找到 {len(rows)} 条相关工单 ---")

    for i, row in enumerate(rows, 1):
        # 数据清洗与空值处理
        wo_no = row['work_order_no']
        room = row['room_number']
        
        # 拼接位置信息
        area = row['area'] or ""
        loc = row['location'] or ""
        full_location = f"{area} {loc}".strip() or "未指定"
        
        item = row['service_item'] or "未知项目"
        o_type = row['order_type'] or ""
        
        status = row['status'] or "未知"
        
        # 时间格式化
        create_time = row['created_at'].strftime('%Y-%m-%d %H:%M:%S') if row['created_at'] else "N/A"
        # 数据库中没有专门的 completed_at，暂时用 updated_at 代替，或显示 N/A
        update_time = row['updated_at'].strftime('%Y-%m-%d %H:%M:%S') if row['updated_at'] else "N/A"

        # 期望上门时间
        expect_date = str(row['expected_visit_date']) if row['expected_visit_date'] else ""
        expect_time = str(row['expected_visit_time']) if row['expected_visit_time'] else ""
        expect_full = f"{expect_date} {expect_time}".strip()

        lines.append(f"\n【记录 {i}】")
        lines.append(f"  工单ID:     {wo_no}")
        lines.append(f"  房号:       {room}")
        lines.append(f"  服务项目:   {item} ({o_type})")
        lines.append(f"  具体位置:   {full_location}")
        lines.append(f"  申请人:     {row['applicant']} (联系方式: {row['contact_info'] or 'N/A'})")
        lines.append(f"  期望上门:   {expect_full or '尽快'}")
        lines.append(f"  服务状态:   {status}")
        lines.append(f"  创建人:     {row['created_by']}")
        lines.append(f"  创建时间:   {create_time}")
        lines.append(f"  更新时间:   {update_time}")
        
    return "\n".join(lines)

# ==========================================
# Main 方法：用于直接调试
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    print(">>> 开始调试 utils/orders.py <<<")
    
    # 假设数据库里有这个房间的工单 (根据你提供的 SELECT * 结果)
    test_room = "A213,A212,A215,A1918" 
    
    print(f"查询房间: {test_room}")
    result = query_orders_logic(test_room)
    print(result)