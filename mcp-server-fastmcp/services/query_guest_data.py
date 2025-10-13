import pandas as pd
from services.constants import IMPORTANT_FIELDS, FIELD_NAME_MAPPING

def get_display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if '\u4e00' <= char <= '\u9fff' else 1
    return width


def get_query_result_as_string(df: pd.DataFrame, query_id: int) -> str:
    """
    查询指定ID的数据，并将格式化后的结果作为单个字符串返回。

    Args:
        df (pd.DataFrame): 包含所有客户数据的DataFrame。
        query_id (int): 要查询的客户ID。

    Returns:
        str: 格式化后的查询结果字符串，或一条“未找到”的消息。
    """
    if df is None:
        return "错误：客户数据未能加载。"

    result = df[df['id'] == query_id]
    if result.empty:
        return f"--- 未找到 ID 为 {query_id} 的记录 ---"

    record = result.iloc[0]
    output_lines = [f"--- ID: {query_id} 的核心数据 ---"]
    max_label_width = 15

    for field in IMPORTANT_FIELDS:
        if field in record:
            display_name = FIELD_NAME_MAPPING.get(field, field)
            value = record[field]
            display_value = value if pd.notna(value) and str(value).strip() != '' else "[空]"

            if field == 'sex_like':
                if display_value == '>':
                    display_value = "男"
                elif display_value == '?':
                    display_value = "女"

            padding_spaces = " " * (max_label_width - get_display_width(display_name))
            output_lines.append(f"{display_name}{padding_spaces}: {display_value}")
        else:
            output_lines.append(f"{FIELD_NAME_MAPPING.get(field, field)}: [字段未找到]")

    # 添加结尾行
    output_lines.append("----------------------------")

    # 将所有行用换行符连接成一个字符串并返回
    return "\n".join(output_lines)

