import xml.etree.ElementTree as ET
import datetime
import re
from typing import List, Dict, Any, Optional
from services.constants import SERVICE_CODE_MAP, LOCATION_CODE_MAP

# --- 辅助函数 ---
def convert_excel_to_datetime_obj(excel_serial_date_str) -> Optional[datetime.datetime]:
    if not excel_serial_date_str: return None
    try:
        excel_serial_date = float(excel_serial_date_str)
        base_date = datetime.datetime(1899, 12, 30)
        return base_date + datetime.timedelta(days=excel_serial_date)
    except (ValueError, TypeError):
        return None


# 根据一系列条件筛选工单列表
def search_orders_advanced(
    orders: List[Dict[str, Any]], 
    start_date: Optional[datetime.date] = None, 
    end_date: Optional[datetime.date] = None, 
    service_code: Optional[str] = None, 
    location_code: Optional[str] = None
) -> List[Dict[str, Any]]:
    if not orders:
        return []

    results = []
    for order in orders:
        order_date_obj = convert_excel_to_datetime_obj(order.get('create_datetime'))

        if order_date_obj:
            order_date = order_date_obj.date()
            if start_date and order_date < start_date: continue
            if end_date and order_date > end_date: continue
        elif start_date or end_date:
            continue

        if service_code and order.get('product_code') != service_code: continue
        if location_code and order.get('location') != location_code: continue

        results.append(order)
    return results

def sanitize_for_display(text):
    """
    清理字符串，将可能破坏布局的控制字符（如换行、回车、U+2028等）替换为空格。
    这确保了每个字段的内容不会意外地跨越多行。
    """
    if not isinstance(text, str):
        return text

    # 正则表达式，匹配所有C0和C1控制字符，以及Unicode的行/段落分隔符
    control_char_regex = re.compile(r'[\x00-\x1F\x7F-\x9F\u2028\u2029]')

    # 将所有匹配到的控制字符替换为一个空格，防止单词粘连
    sanitized_text = control_char_regex.sub(' ', text)

    return sanitized_text

def format_to_string(results: List[Dict[str, Any]], criteria: str) -> str:
    """将筛选后的工单列表格式化为人类可读的字符串。"""
    if not results:
        return f"查询条件: {criteria}\n>> 未找到符合条件的工单信息。"

    output_parts = [
        f"查询条件: {criteria}",
        f"--- 共找到 {len(results)} 条相关工单 ---\n"
    ]

    for i, order in enumerate(results):
        product_code = order.get('product_code', '')
        service_name = SERVICE_CODE_MAP.get(product_code, f"未知代码 ({product_code})")
        location_code = order.get('location', '')
        location_name = LOCATION_CODE_MAP.get(location_code, "未提供")
        
        create_dt_human = convert_excel_to_datetime_obj(order.get('create_datetime', ''))
        complete_dt_human = convert_excel_to_datetime_obj(order.get('complete_date', ''))
        
        output_parts.append(
            f"\n【记录 {i + 1}】\n"
            f"  房号:       {order.get('rmno', '未提供')}\n"
            f"  服务项目:   {service_name} ({product_code or '无代码'})\n"
            f"  具体位置:   {location_name} ({location_code or '无代码'})\n"
            f"  需求描述:   {sanitize_for_display(order.get('requirement') or '无')}\n"
            f"  创建时间:   {create_dt_human.strftime('%Y-%m-%d %H:%M:%S') if create_dt_human else 'N/A'}\n"
            f"  完成时间:   {complete_dt_human.strftime('%Y-%m-%d %H:%M:%S') if complete_dt_human else 'N/A'}\n"
        )
    return "".join(output_parts)
