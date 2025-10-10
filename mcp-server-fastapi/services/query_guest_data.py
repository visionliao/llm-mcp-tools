import pandas as pd
import os
from lxml import etree
from datetime import datetime, timedelta
from typing import Optional

# --- 配置 ---
XML_FILE_PATH = 'master_guest.xml'

# 定义重要字段列表
IMPORTANT_FIELDS = [
    'id', 'profile_id', 'name', 'sex_like', 'birth', 'language',
    'mobile', 'email', 'nation', 'country', 'state', 'street',
    'id_code', 'id_no', 'hotel_id', 'profile_type', 'times_in',
    'create_user', 'create_datetime', 'modify_user', 'modify_datetime',
]

# 字段名到中文描述的映射
FIELD_NAME_MAPPING = {
    'id': '主键ID', 'profile_id': '客户档案ID', 'name': '姓名',
    'sex_like': '推断性别', 'birth': '出生日期', 'language': '语言代码',
    'mobile': '手机', 'email': '电子邮件', 'nation': '国籍代码',
    'country': '国家代码', 'state': '省份/州代码', 'street': '街道地址',
    'id_code': '证件类型代码', 'id_no': '证件号码', 'hotel_id': '酒店ID',
    'profile_type': '客户档案类型', 'times_in': '入住次数',
    'create_user': '创建用户', 'create_datetime': '创建时间',
    'modify_user': '修改用户', 'modify_datetime': '修改时间',
}


def get_display_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if '\u4e00' <= char <= '\u9fff' else 1
    return width


def convert_excel_date(excel_date):
    try:
        num_date = float(excel_date)
        base_date = datetime(1899, 12, 30)
        dt = base_date + timedelta(days=num_date)
        return dt.strftime('%Y-%m-%d %H:%M:%S') if num_date != int(num_date) else dt.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return excel_date


def load_data_from_xml(file_path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(file_path):
        print(f"错误：文件 '{file_path}' 不存在。")
        return None
    try:
        tree = etree.parse(file_path)
        ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
        rows = tree.xpath('.//ss:Row', namespaces=ns)
        if not rows: return None
        header = [cell.text for cell in rows[0].xpath('.//ss:Data', namespaces=ns)]
        all_rows_data = [[cell.text if cell.text is not None else '' for cell in row.xpath('.//ss:Data', namespaces=ns)]
                         for row in rows[1:]]
        df = pd.DataFrame([row for row in all_rows_data if len(row) == len(header)], columns=header)

        if 'id' not in df.columns: return None
        df['id'] = pd.to_numeric(df['id'], errors='coerce')
        df.dropna(subset=['id'], inplace=True)
        df['id'] = df['id'].astype(int)

        date_columns = ['birth', 'create_datetime', 'modify_datetime']
        for col in date_columns:
            if col in df.columns:
                df[col] = df[col].apply(convert_excel_date)

        print(f"成功加载并处理了 {len(df)} 条记录。")
        return df
    except Exception as e:
        print(f"加载或处理XML文件时发生错误: {e}")
        return None


# --- 【核心新函数】 ---
def get_query_result_as_string(df: pd.DataFrame, query_id: int) -> str:
    """
    查询指定ID的数据，并将格式化后的结果作为单个字符串返回。

    Args:
        df (pd.DataFrame): 包含所有客户数据的DataFrame。
        query_id (int): 要查询的客户ID。

    Returns:
        str: 格式化后的查询结果字符串，或一条“未找到”的消息。
    """
    result = df[df['id'] == query_id]

    if result.empty:
        return f"--- 未找到 ID 为 {query_id} 的记录 ---"

    record = result.iloc[0]
    output_lines = []

    # 添加标题行
    output_lines.append(f"--- ID: {query_id} 的核心数据 ---")

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
            line = f"{display_name}{padding_spaces}: {display_value}"
            output_lines.append(line)
        else:
            line = f"{FIELD_NAME_MAPPING.get(field, field)}: [字段未找到]"
            output_lines.append(line)

    # 添加结尾行
    output_lines.append("----------------------------")

    # 将所有行用换行符连接成一个字符串并返回
    return "\n".join(output_lines)


def query_and_display_interactive(df: pd.DataFrame):
    """
    启动一个交互式循环，调用新函数来获取结果字符串并打印它。
    """
    while True:
        user_input = input("\n请输入要查询的客户 ID (输入 'q' 或 'quit' 退出): ").strip()
        if user_input.lower() in ['q', 'quit']:
            print("脚本退出。")
            break
        try:
            query_id = int(user_input)
            # 调用新函数获取结果字符串
            result_string = get_query_result_as_string(df, query_id)
            # 打印结果
            print(result_string)
        except ValueError:
            print("无效输入。请输入一个数字ID。")


if __name__ == "__main__":
    guest_df = load_data_from_xml(XML_FILE_PATH)

    if guest_df is not None:
        # --- 示例：如何将查询结果存入变量 ---
        print("\n--- 将ID 3494 的查询结果存入变量 ---")
        query_id_example = 3664

        # 调用函数，将返回的字符串存入 `result_variable`
        result_variable = get_query_result_as_string(guest_df, query_id_example)

        print("查询结果已成功存入变量 'result_variable'。")
        print("现在可以对这个变量进行操作，例如打印它：\n")

        # 打印变量的内容
        print(result_variable)

        # 也可以将它写入文件
        # with open("query_result.txt", "w", encoding="utf-8") as f:
        #     f.write(result_variable)
        # print("\n结果也已写入到 query_result.txt 文件。")

        # --- 启动交互式查询 ---
        print("\n\n--- 现在启动交互式查询 ---")
        query_and_display_interactive(guest_df)
    else:
        print("数据未能成功加载，程序即将退出。")