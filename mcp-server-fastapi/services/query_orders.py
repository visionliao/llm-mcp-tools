import datetime
import re
from typing import List, Dict, Any
from services.constants import SERVICE_CODE_MAP, LOCATION_CODE_MAP

# --- 辅助函数 ---
def _convert_excel_date(excel_serial_date_str: str) -> str:
    if not excel_serial_date_str: return "N/A"
    try:
        excel_serial_date = float(excel_serial_date_str)
        base_date = datetime.datetime(1899, 12, 30)
        delta = datetime.timedelta(days=excel_serial_date)
        return (base_date + delta).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return excel_serial_date_str

def _sanitize_for_display(text: Any) -> Any:
    if not isinstance(text, str): return text
    control_char_regex = re.compile(r'[\x00-\x1F\x7F-\x9F\u2028\u2029]')
    return control_char_regex.sub(' ', text)

def search_by_rmno(
    orders: List[Dict[str, Any]], 
    room_number: str
) -> List[Dict[str, Any]]:
    """
    在一个给定的工单列表（字典列表）中，根据房号筛选工单。
    这是一个纯函数，不执行任何I/O操作。
    """
    # 接收一个工单列表作为输入
    if not room_number or not orders: 
        return []
        
    search_term = room_number.lower().strip()
    return [order for order in orders if order.get('rmno', '').lower().strip() == search_term]


def format_results_string(results: List[Dict[str, Any]]) -> str:
    """将工单结果列表格式化为人类可读的字符串。"""
    if not results:
        return ">> 未找到相关工单信息。"

    output_parts = [f"--- 找到 {len(results)} 条相关工单 ---\n"]

    for i, order in enumerate(results):
        product_code = order.get('product_code', '')
        service_name = SERVICE_CODE_MAP.get(product_code, f"未知代码 ({product_code})")
        location_code = order.get('location', '')
        location_name = LOCATION_CODE_MAP.get(location_code, "未提供")

        output_parts.append(
            f"\n【记录 {i + 1}】\n"
            f"  工单ID:     {order.get('id', 'N/A')}\n"
            f"  房号:       {order.get('rmno', 'N/A')}\n"
            f"  服务项目:   {service_name} ({product_code or '无代码'})\n"
            f"  具体位置:   {location_name} ({location_code or '无代码'})\n"
            f"  需求描述:   {_sanitize_for_display(order.get('requirement') or '无')}\n"
            f"  优先级:     {order.get('priority', '无')}\n"
            f"  进入指引:   {_sanitize_for_display(order.get('entry_guidelines') or '无')}\n"
            f"  服务状态:   {order.get('service_state', 'N/A')}\n"
            f"  服务人员:   {order.get('service_man', '未分配')}\n"
            f"  处理结果:   {order.get('remark', '无')}\n"
            f"  创建时间:   {_convert_excel_date(order.get('create_datetime', ''))}\n"
            f"  完成时间:   {_convert_excel_date(order.get('complete_date', ''))}\n"
        )
    return "".join(output_parts)
