import pandas as pd
from datetime import datetime
import re
from typing import Union

# --- 核心查询函数 ---
def query_checkin_records(
    df: pd.DataFrame, 
    start_date_str: str, 
    end_date_str: str, 
    status_filter: str = 'ALL'
) -> Union[pd.DataFrame, str]:
    """
    在一个给定的DataFrame中，根据日期范围和状态筛选入住记录。
    这是一个纯函数，不执行任何I/O操作。
    """
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return "错误: 日期格式不正确，请使用 'YYYY-MM-DD' 格式。"
    if start_date > end_date:
        return "错误: 开始日期不能晚于结束日期。"

    if df.empty: 
        return "未能加载任何数据。"

    required_cols = ['id', 'sta', 'rmno', 'rmtype', 'arr', 'dep', 'full_rate_long', 'is_long', 'create_datetime',
                     'remark', 'co_msg']
    if not all(col in df.columns for col in required_cols):
        return f"错误: 文件中缺少必要的列。需要: {required_cols}"

    # 为避免SettingWithCopyWarning，对数据进行一次性的预处理和拷贝
    df_processed = df.copy()
    for col in ['id', 'arr', 'dep', 'full_rate_long', 'create_datetime']:
        df_processed[col] = pd.to_numeric(df_processed[col], errors='coerce')
    
    df_processed.dropna(subset=['arr', 'rmno', 'create_datetime'], inplace=True)
    
    df_processed['arr_date'] = pd.to_datetime(df_processed['arr'], unit='D', origin='1899-12-30').dt.date
    df_processed['dep_date'] = pd.to_datetime(df_processed['dep'], unit='D', origin='1899-12-30').dt.date
    df_processed['create_dt'] = pd.to_datetime(df_processed['create_datetime'], unit='D', origin='1899-12-30')

    checkin_records_df = df_processed[(df_processed['arr_date'] >= start_date) & (df_processed['arr_date'] <= end_date)].copy()
    if status_filter != 'ALL':
        checkin_records_df = checkin_records_df[checkin_records_df['sta'] == status_filter]
        
    if not checkin_records_df.empty:
        checkin_records_df['rent_priority'] = (checkin_records_df['full_rate_long'] > 0).astype(int)
        sorted_records = checkin_records_df.sort_values(by=['rmno', 'rent_priority', 'create_dt'], ascending=[True, False, False])
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

# --- 格式化输出函数---
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

    # 清理自由文本字段，防止非法字符破坏表格布局
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
