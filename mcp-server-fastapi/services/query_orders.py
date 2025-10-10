import xml.etree.ElementTree as ET
import os
import datetime
import re

# --- 配置 ---
XML_FILE_PATH = 'lease_service_order.xml'

# --- 步骤 1: 数据化服务代码表 (内置知识库) ---
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
    '002': '卧室',
    '004': '厨房',
    '008': '卫生间',
    '009': '客厅',
    '001': '公寓外围',
    '003': '工区走道',
    '005': '后场区域',
    '006': '前场区域',
    '011': '电梯厅-后',
    '010': '电梯厅-前',
    '007': '停车场',
    '012': '消防楼梯',
}

# --- 步骤 2: 创建查询函数 ---
def get_service_name(code):
    """
    根据服务代码查询服务项目名称。
    如果代码不存在，则返回一个提示信息。
    """
    if not code:
        return "未提供"
    return SERVICE_CODE_MAP.get(code, f"未知代码 ({code})")


# --- 辅助函数 ---
def convert_excel_date(excel_serial_date_str):
    if not excel_serial_date_str: return "N/A"
    try:
        excel_serial_date = float(excel_serial_date_str)
        base_date = datetime.datetime(1899, 12, 30)
        delta = datetime.timedelta(days=excel_serial_date)
        return (base_date + delta).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return excel_serial_date_str


# --- 数据加载与搜索函数 (无变化) ---
def parse_service_orders(xml_file):
    print(f"正在从 '{xml_file}' 加载数据...")
    if not os.path.exists(xml_file):
        print(f"错误: 文件 '{xml_file}' 未找到。")
        return None
    try:
        namespaces = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
        tree = ET.parse(xml_file)
        root = tree.getroot()
        table = root.find('.//ss:Table', namespaces)
        if table is None: return []
        rows = table.findall('ss:Row', namespaces)
        header_row = rows[0]
        data_elements = [cell.find('ss:Data', namespaces) for cell in header_row.findall('ss:Cell', namespaces)]
        headers = [elem.text if elem is not None else "" for elem in data_elements]
        orders = []
        for row in rows[1:]:
            order_data = {}
            cells = row.findall('ss:Cell', namespaces)
            for i, cell in enumerate(cells):
                if i < len(headers):
                    data_element = cell.find('ss:Data', namespaces)
                    value = data_element.text if data_element is not None and data_element.text is not None else ""
                    order_data[headers[i]] = value.strip()
            orders.append(order_data)
        print(f"成功加载 {len(orders)} 条工单数据。\n")
        return orders
    except ET.ParseError as e:
        print(f"错误: 解析XML文件失败。错误信息: {e}")
        return None


def search_by_rmno(orders, room_number):
    if not room_number: return []
    search_term = room_number.lower().strip()
    return [order for order in orders if order.get('rmno', '').lower().strip() == search_term]

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

# --- 步骤 3: 修改输出格式 ---
def format_results_string(results):
    if not results:
        return ">> 未找到相关工单信息。"

    output_parts = []
    output_parts.append(f"--- 找到 {len(results)} 条相关工单 ---\n\n")

    for i, order in enumerate(results):
        # 获取服务代码并查找其名称
        product_code = order.get('product_code', '')
        service_name = get_service_name(product_code)

        location_code = order.get('location', '')
        location_name = LOCATION_CODE_MAP.get(location_code)

        # 转换时间
        create_dt_human = convert_excel_date(order.get('create_datetime', ''))
        complete_dt_human = convert_excel_date(order.get('complete_date', ''))

        sanitized_requirement = sanitize_for_display(order.get('requirement') or '无')
        sanitized_entry_guidelines = sanitize_for_display(order.get('entry_guidelines') or '无')

        output_parts.append(f"【记录 {i + 1}】\n")
        output_parts.append(f"  工单ID:     {order.get('id', 'N/A')}\n")
        output_parts.append(f"  房号:       {order.get('rmno', 'N/A')}\n")
        output_parts.append(f"  服务项目:   {service_name} ({product_code or '无代码'})\n")
        output_parts.append(f"  具体位置:   {location_name} ({location_code or '无代码'})\n")
        output_parts.append(f"  需求描述:   {sanitized_requirement}\n")
        output_parts.append(f"  优先级:   {order.get('priority', '无描述')}\n")
        output_parts.append(f"  进入房间指引/注意事项:   {sanitized_entry_guidelines}\n")
        output_parts.append(f"  服务状态:   {order.get('service_state', 'N/A')}\n")
        output_parts.append(f"  服务人员:   {order.get('service_man', '未分配')}\n")
        output_parts.append(f"  处理结果:   {order.get('remark', '无')}\n")
        output_parts.append(f"  创建时间:   {create_dt_human}\n")
        output_parts.append(f"  完成时间:   {complete_dt_human}\n")
        output_parts.append("-" * 25 + "\n\n")

    return "".join(output_parts)


def main():
    all_orders = parse_service_orders(XML_FILE_PATH)
    if all_orders is None: return

    print("欢迎使用服务工单查询系统！")
    while True:
        room_number_input = input("请输入要查询的房号 (输入 'q' 退出): ")
        if room_number_input.lower().strip() == 'q':
            print("感谢使用，再见！")
            break
        found_orders = search_by_rmno(all_orders, room_number_input)
        result_string = format_results_string(found_orders)
        print(result_string)


if __name__ == "__main__":
    main()