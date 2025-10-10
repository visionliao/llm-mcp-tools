import pandas as pd
from datetime import datetime
from lxml import etree
import re  # 引入正则表达式库，用于处理用户输入

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
    """
    使用 lxml 解析 SpreadsheetML 2003 XML 文件并返回一个 pandas DataFrame 或错误信息。
    """
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

# --- 核心查询函数 (按房号筛选) ---
def query_records_by_room(file_path: str, room_numbers: list):
    """
    根据一个或多个房间号查询所有相关记录。
    """
    if not room_numbers:
        return "错误: 未输入任何房间号。"

    df_or_error = parse_spreadsheetml(file_path)
    if isinstance(df_or_error, str):
        return df_or_error
    df = df_or_error

    if df.empty:
        return "未能从文件中加载任何数据。"

    # --- 数据预处理 ---
    required_cols = ['id', 'sta', 'rmno', 'rmtype', 'arr', 'dep', 'full_rate_long', 'is_long', 'remark', 'co_msg']
    if not all(col in df.columns for col in required_cols):
        return f"错误: 文件中缺少必要的列。需要: {required_cols}"

    for col in ['id', 'arr', 'dep', 'full_rate_long']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df.dropna(subset=['rmno'], inplace=True)

    df['arr_date'] = pd.to_datetime(df['arr'], unit='D', origin='1899-12-30').dt.date # type: ignore
    df['dep_date'] = pd.to_datetime(df['dep'], unit='D', origin='1899-12-30').dt.date # type: ignore

    # --- 核心筛选逻辑 ---
    # 使用 .isin() 方法来匹配列表中的多个房间号
    # .str.upper() 将数据和输入的房号都转为大写，实现不区分大小写的匹配
    room_numbers_upper = [r.upper() for r in room_numbers]
    room_records_df = df[df['rmno'].str.upper().isin(room_numbers_upper)].copy()

    return room_records_df


# --- 格式化输出函数 (与之前类似) ---
def format_string(records_df, room_numbers, room_names) -> str:
    if isinstance(records_df, str):
        return records_df

    query_rooms_str = ", ".join(room_numbers)

    if records_df.empty:
        return f"没有找到与房间号 '{query_rooms_str}' 相关的任何记录。"

    # 清理自由文本字段，防止非法字符破坏表格布局
    records_df['remark'] = records_df['remark'].apply(sanitize_for_display)
    records_df['co_msg'] = records_df['co_msg'].apply(sanitize_for_display)

    records_df['房型名称'] = records_df['rmtype'].map(room_names).fillna(records_df['rmtype'])
    records_df['入住类型'] = records_df['is_long'].apply(lambda x: '长租' if x == 'T' else '短住')
    records_df['租金/房价'] = records_df['full_rate_long'].apply(lambda x: f"{x:,.2f}" if pd.notna(x) else "N/A")
    records_df['remark'] = records_df['remark'].fillna('')
    records_df['co_msg'] = records_df['co_msg'].fillna('')

    # 按入住日期降序排列，最新记录在前
    records_df_sorted = records_df.sort_values(by='arr_date', ascending=False)

    report_lines = []
    report_lines.append(f"--- 房间号查询结果 ({query_rooms_str}) ---")
    report_lines.append(f"共找到 {len(records_df_sorted)} 条相关记录。\n")

    display_columns = {
        'arr_date': '入住日期', 'dep_date': '离店日期', 'rmno': '房号', '房型名称': '房型',
        '租金/房价': '租金', 'sta': '状态', 'id': '用户ID', 'remark': '备注', 'co_msg': '交班信息'
    }

    pd.set_option('display.max_colwidth', None)
    pd.set_option('display.width', 1000)

    table_string = records_df_sorted[list(display_columns.keys())].rename(columns=display_columns).to_string(
        index=False)
    report_lines.append(table_string)

    report_lines.append("\n" + "-" * 80)
    return "\n".join(report_lines)


# --- 主程序入口 ---
if __name__ == "__main__":
    print("--- 房间历史记录查询工具 ---")
    #room_input = input("请输入一个或多个房间号 (用空格或逗号分隔): ")
    room_input = 'A212, B202 C303'

    # 使用正则表达式分割输入，并清除空字符串
    # 例如，'A101, B202 C303' -> ['A101', 'B202', 'C303']
    room_list = [r.strip() for r in re.split(r'[\s,]+', room_input) if r.strip()]

    # 1. 调用查询函数
    found_records = query_records_by_room(FILE_PATH, room_list)

    # 2. 调用格式化函数
    final_string = format_string(
        found_records,
        room_list,
        ROOM_TYPE_NAMES
    )

    # 3. 打印结果
    print("\n" + "=" * 80)
    print(final_string)
    print("=" * 80)

    '''# 4. (可选) 写入文件
    if isinstance(found_records, pd.DataFrame) and not found_records.empty:
        try:
            with open("room_query_report.txt", "w", encoding="utf-8") as f:
                f.write(final_report_string)
            print("\n查询报告已保存至 room_query_report.txt")
        except Exception as e:
            print(f"\n写入报告文件时出错: {e}")'''