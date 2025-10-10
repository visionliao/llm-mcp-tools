import pandas as pd
from datetime import datetime
from lxml import etree
import re

# --- 配置区域 ---
FILE_PATH = 'master_base.xml'
# 各户型代码到具体名称的映射
ROOM_TYPE_NAMES = {
    '1BD': "一房豪华式公寓",
    '1BP': "一房行政豪华式公寓",
    '2BD': "两房行政公寓",
    '3BR': "三房公寓",
    'STD': "豪华单间公寓",
    'STE': "行政单间公寓",
    'STP': "豪华行政单间"
}


# --- 数据解析函数 (与之前相同) ---
def parse_spreadsheetml(file_path: str):
    # ... (此函数代码与之前完全相同，此处省略)
    try:
        tree = etree.parse(file_path)
        root = tree.getroot()
        ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
        rows = root.findall('.//ss:Worksheet/ss:Table/ss:Row', namespaces=ns)
        if not rows: return pd.DataFrame()
        header_row = rows[0]
        header = [cell.find('ss:Data', namespaces=ns).text.strip() if cell.find('ss:Data',
                                                                                namespaces=ns) is not None and cell.find(
            'ss:Data', namespaces=ns).text is not None else "" for cell in header_row.findall('ss:Cell', namespaces=ns)]
        data = []
        for row in rows[1:]:
            row_data = [(cell.find('ss:Data', namespaces=ns).text if cell.find('ss:Data',
                                                                               namespaces=ns) is not None and cell.find(
                'ss:Data', namespaces=ns).text is not None else '') for cell in row.findall('ss:Cell', namespaces=ns)]
            if len(row_data) < len(header): row_data.extend([''] * (len(header) - len(row_data)))
            data.append(row_data)
        return pd.DataFrame(data, columns=header)
    except Exception as e:
        return f"解析XML文件时发生错误: {e}"


# --- 核心查询函数 (与之前相同) ---
def query_checkin_records(file_path: str, start_date_str: str, end_date_str: str, status_filter: str = 'ALL'):
    # ... (此函数代码与之前完全相同，此处省略)
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return "错误: 日期格式不正确，请使用 'YYYY-MM-DD' 格式。"
    if start_date > end_date:
        return "错误: 开始日期不能晚于结束日期。"
    df_or_error = parse_spreadsheetml(file_path)
    if isinstance(df_or_error, str): return df_or_error
    df = df_or_error
    if df.empty: return "未能从文件中加载任何数据。"
    required_cols = ['id', 'sta', 'rmno', 'rmtype', 'arr', 'dep', 'full_rate_long', 'is_long', 'create_datetime',
                     'remark', 'co_msg']
    if not all(col in df.columns for col in required_cols):
        return f"错误: 文件中缺少必要的列。需要: {required_cols}"
    for col in ['id', 'arr', 'dep', 'full_rate_long', 'create_datetime']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(subset=['arr', 'rmno', 'create_datetime'], inplace=True)
    df['arr_date'] = pd.to_datetime(df['arr'], unit='D', origin='1899-12-30').dt.date # type: ignore
    df['dep_date'] = pd.to_datetime(df['dep'], unit='D', origin='1899-12-30').dt.date # type: ignore
    df['create_dt'] = pd.to_datetime(df['create_datetime'], unit='D', origin='1899-12-30')
    checkin_records_df = df[(df['arr_date'] >= start_date) & (df['arr_date'] <= end_date)].copy()
    if status_filter != 'ALL':
        checkin_records_df = checkin_records_df[checkin_records_df['sta'] == status_filter]
    if not checkin_records_df.empty:
        checkin_records_df['rent_priority'] = (checkin_records_df['full_rate_long'] > 0).astype(int)
        sorted_records = checkin_records_df.sort_values(by=['rmno', 'rent_priority', 'create_dt'],
                                                        ascending=[True, False, False])
        unique_checkin_records = sorted_records.drop_duplicates(subset='rmno', keep='first')
        return unique_checkin_records
    else:
        return checkin_records_df


def sanitize_for_display(text):
    """
    清理字符串，将可能破坏表格布局的控制字符替换为空格。
    这确保了每条记录在生成的表格中只占一行。
    """
    if not isinstance(text, str):
        return text

    # 定义一个正则表达式，匹配所有 C0 和 C1 控制字符，但排除我们常见的空白符
    # 比如 \t(tab), \n(换行), \r(回车) 都会被替换
    # 同时包含 Unicode 的行分隔符和段落分隔符
    control_char_regex = re.compile(r'[\x00-\x1F\x7F-\x9F\u2028\u2029]')

    # 将所有匹配到的控制字符替换为一个空格
    sanitized_text = control_char_regex.sub(' ', text)

    return sanitized_text

# --- 格式化输出函数 (已更新) ---
def format_records_to_string(records_df, start_date_str, end_date_str, room_names, status_filter):
    if isinstance(records_df, str): return records_df

    status_text = f"状态: {status_filter}" if status_filter != 'ALL' else "所有状态"

    if records_df.empty:
        return f"在 {start_date_str} 到 {end_date_str} 期间没有找到任何（去重后，{status_text}）的入住记录。"

    # 创建一个副本以避免 SettingWithCopyWarning
    records_df = records_df.copy()

    # 数据准备
    records_df['房型名称'] = records_df['rmtype'].map(room_names).fillna(records_df['rmtype'])
    records_df['入住类型'] = records_df['is_long'].apply(lambda x: '长租' if x == 'T' else '短住')
    records_df['租金/房价'] = records_df['full_rate_long'].apply(lambda x: f"{x:,.2f}" if pd.notna(x) else "N/A")

    # 填充 remark 和 co_msg 的空值
    records_df['remark'] = records_df['remark'].fillna('')
    records_df['co_msg'] = records_df['co_msg'].fillna('')

    # (关键修改点) 清理自由文本字段，防止非法字符破坏表格布局
    records_df['remark'] = records_df['remark'].apply(sanitize_for_display)
    records_df['co_msg'] = records_df['co_msg'].apply(sanitize_for_display)

    records_df_sorted = records_df.sort_values(by='arr_date')

    report_lines = []
    report_lines.append(f"--- 入住记录查询结果 ({start_date_str} 到 {end_date_str}, {status_text}) ---")
    report_lines.append(f"共找到 {len(records_df_sorted)} 条（去重后）记录。\n")

    display_columns = {
        'arr_date': '入住日期',
        'dep_date': '离店日期',
        'rmno': '房号',
        '房型名称': '房型',
        '租金/房价': '租金',
        'sta': '状态',
        'id': '用户ID',
        'remark': '备注',
        'co_msg': '交班信息'
    }

    # 调整pandas的显示选项，防止长文本被截断
    pd.set_option('display.max_colwidth', None)  # 不限制列宽
    pd.set_option('display.width', 1000)  # 设置一个足够宽的显示宽度

    # 生成主表格字符串
    table_string = records_df_sorted[list(display_columns.keys())].rename(columns=display_columns).to_string(
        index=False)
    report_lines.append(table_string)

    report_lines.append("\n" + "-" * 80)
    return "\n".join(report_lines)


# --- 主程序入口 (与之前相同) ---
if __name__ == "__main__":
    print("--- 最近入住记录查询工具 ---")
    start_input = "2025-01-01"
    end_input = "2025-08-28"

    print("\n请选择要查询的记录状态:")
    print(" 1: I (在住)\n 2: O (结帐)\n 3: X (取消)\n 4: R (预订)\n 5: ALL (所有状态，默认)")
    status_choice = "1"

    status_map = {'1': 'I', '2': 'O', '3': 'X', '4': 'R', '5': 'ALL'}
    selected_status = status_map.get(status_choice, 'ALL')

    found_records = query_checkin_records(FILE_PATH, start_input, end_input, status_filter=selected_status)

    final_report_string = format_records_to_string(found_records, start_input, end_input, ROOM_TYPE_NAMES,
                                                   status_filter=selected_status)

    print("\n" + "=" * 80)
    print(final_report_string)
    print("=" * 80)

    '''if isinstance(found_records, pd.DataFrame) and not found_records.empty:
        try:
            with open("checkin_report_table.txt", "w", encoding="utf-8") as f:
                f.write(final_report_string)
            print("\n查询报告已保存至 checkin_report_table.txt")
        except Exception as e:
            print(f"\n写入报告文件时出错: {e}")'''