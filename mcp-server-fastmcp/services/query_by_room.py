import pandas as pd
import re
from typing import List, Union

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
def query_records_by_room(
    df: pd.DataFrame, 
    room_numbers: List[str]
) -> Union[pd.DataFrame, str]:
    """
    根据一个或多个房间号查询所有相关记录。
    """
    if not room_numbers:
        return "错误: 未输入任何房间号。"

    if df.empty:
        return "未能加载任何数据。"

    # --- 数据预处理 ---
    required_cols = ['id', 'sta', 'rmno', 'rmtype', 'arr', 'dep', 'full_rate_long', 'is_long', 'remark', 'co_msg']
    if not all(col in df.columns for col in required_cols):
        return f"错误: 数据文件中缺少必要的列。需要: {required_cols}"

    # 创建副本以安全地进行后续操作
    df_processed = df.copy()
    for col in ['id', 'arr', 'dep', 'full_rate_long']:
        df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce')

    df_processed.dropna(subset=['rmno'], inplace=True)
    df_processed['arr_date'] = pd.to_datetime(df_processed['arr'], unit='D', origin='1899-12-30').dt.date
    df_processed['dep_date'] = pd.to_datetime(df_processed['dep'], unit='D', origin='1899-12-30').dt.date

    # --- 核心筛选逻辑 ---
    room_numbers_upper = [r.upper() for r in room_numbers]
    room_records_df = df_processed[df_processed['rmno'].str.upper().isin(room_numbers_upper)].copy()

    return room_records_df


# --- 格式化输出函数 ---
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
