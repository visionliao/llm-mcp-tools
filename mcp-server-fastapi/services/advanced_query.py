import xml.etree.ElementTree as ET
import os
import datetime
import re

# --- 配置与数据字典 (无变化) ---
XML_FILE_PATH = 'lease_service_order.xml'
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
    '002': '卧室', '004': '厨房', '008': '卫生间', '009': '客厅',
    '001': '公寓外围', '003': '工区走道', '005': '后场区域', '006': '前场区域',
    '011': '电梯厅-后', '010': '电梯厅-前', '007': '停车场', '012': '消防楼梯',
}


# --- 辅助、数据加载、高级筛选、结果格式化函数 (无变化) ---
def get_service_name(code):
    return SERVICE_CODE_MAP.get(code, f"未知代码 ({code})")


def convert_excel_to_datetime_obj(excel_serial_date_str):
    if not excel_serial_date_str: return None
    try:
        excel_serial_date = float(excel_serial_date_str)
        base_date = datetime.datetime(1899, 12, 30)
        return base_date + datetime.timedelta(days=excel_serial_date)
    except (ValueError, TypeError):
        return None


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
        headers = [cell.find('ss:Data', namespaces).text for cell in header_row.findall('ss:Cell', namespaces)]
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


def search_orders_advanced(orders, start_date=None, end_date=None, service_code=None, location_code=None):
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

def format_to_string(results, criteria):
    if not results:
        return f"查询条件: {criteria}\n>> 未找到符合条件的工单信息。"
    output_parts = []
    output_parts.append(f"查询条件: {criteria}")
    output_parts.append(f"--- 共找到 {len(results)} 条相关工单 ---\n\n")
    for i, order in enumerate(results):
        product_code = order.get('product_code', '')
        service_name = get_service_name(product_code)
        location_code = order.get('location', '')
        location_name = LOCATION_CODE_MAP.get(location_code) if location_code else "未提供"
        create_dt_human = convert_excel_to_datetime_obj(order.get('create_datetime', ''))
        complete_dt_human = convert_excel_to_datetime_obj(order.get('complete_date', ''))
        sanitized_requirement = sanitize_for_display(order.get('requirement') or '无')
        default_text = "未提供"
        output_parts.append(f"【记录 {i + 1}】\n")
        output_parts.append(f"  房号:       {order.get('rmno', default_text)}\n")
        output_parts.append(f"  服务项目:   {service_name} ({product_code or '无代码'})\n")
        output_parts.append(f"  具体位置:   {location_name} ({location_code or '无代码'})\n")
        output_parts.append(f"  需求描述:   {sanitized_requirement}\n")
        output_parts.append(
            f"  创建时间:   {create_dt_human.strftime('%Y-%m-%d %H:%M:%S') if create_dt_human else 'N/A'}\n")
        output_parts.append(
            f"  完成时间:   {complete_dt_human.strftime('%Y-%m-%d %H:%M:%S') if complete_dt_human else 'N/A'}\n")
        output_parts.append("-" * 25 + "\n\n")
    return "".join(output_parts)


# --- 主程序 ---
def main():
    all_orders = parse_service_orders(XML_FILE_PATH)
    if not all_orders:
        return

    service_list = list(SERVICE_CODE_MAP.items())
    location_list = list(LOCATION_CODE_MAP.items())

    print("欢迎使用高级工单查询系统！\n")

    while True:
        print("--- 请输入筛选条件 ---")
        start_date_str = input("请输入开始日期 (格式 YYYY-MM-DD, 直接回车表示不限): ")
        end_date_str = input("请输入结束日期 (格式 YYYY-MM-DD, 直接回车表示不限): ")

        print("\n可选服务项目:")
        for i, (code, name) in enumerate(service_list):
            print(f"  {i + 1}: {name} ({code})")
        # 【修改】更新提示信息
        service_choice_str = input("请选择服务项目编号 (输入 0 或直接回车表示不限): ")

        print("\n可选具体位置:")
        for i, (code, name) in enumerate(location_list):
            print(f"  {i + 1}: {name} ({code})")
        # 【修改】更新提示信息
        location_choice_str = input("请选择具体位置编号 (输入 0 或直接回车表示不限): ")

        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None

            # 【修改】更新输入处理逻辑，将 '0' 也视作 '不限'
            service_code = None
            if service_choice_str and service_choice_str != '0':
                service_code = service_list[int(service_choice_str) - 1][0]

            # 【修改】更新输入处理逻辑，将 '0' 也视作 '不限'
            location_code = None
            if location_choice_str and location_choice_str != '0':
                location_code = location_list[int(location_choice_str) - 1][0]

        except (ValueError, IndexError):
            print("\n!!! 输入错误: 日期格式或编号无效，请重新输入。 !!!\n")
            continue

        criteria_desc = (
            f"时间范围: [{start_date_str or '不限'} 至 {end_date_str or '不限'}], "
            f"服务项目: [{SERVICE_CODE_MAP.get(service_code, '不限')}], "
            f"具体位置: [{LOCATION_CODE_MAP.get(location_code, '不限')}]"
        )

        found_orders = search_orders_advanced(all_orders, start_date, end_date, service_code, location_code)
        result_string = format_to_string(found_orders, criteria_desc)
        print("\n" + "=" * 50)
        print(result_string)
        print("=" * 50 + "\n")

        continue_choice = input("是否进行新的查询? (y/n, 默认y): ").lower()
        if continue_choice == 'n':
            print("感谢使用，再见！")
            break


if __name__ == "__main__":
    main()