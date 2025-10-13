# services/data_loader.py

import pandas as pd
from lxml import etree
import xml.etree.ElementTree as ET
from functools import lru_cache
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

# 这是一个内部辅助函数，我们不直接在外部调用它
def _parse_spreadsheetml(file_path: str) -> Optional[pd.DataFrame]:
    """
    一个通用的、底层的 SpreadsheetML XML 解析器。
    注意：这个函数本身不应该被缓存，因为我们希望缓存的是加载特定文件的结果。
    """
    try:
        tree = etree.parse(file_path)
        root = tree.getroot()
        ns = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
        rows = root.findall('.//ss:Worksheet/ss:Table/ss:Row', namespaces=ns)

        if not rows:
            return pd.DataFrame()

        header_row = rows[0]
        data_elements = [cell.find('ss:Data', namespaces=ns) for cell in header_row.findall('ss:Cell', namespaces=ns)]
        header = [elem.text.strip() if elem is not None and elem.text is not None else "" for elem in data_elements]

        data = []
        for row in rows[1:]:
            row_data = []
            cells = row.findall('ss:Cell', namespaces=ns)
            for cell in cells:
                cell_text_element = cell.find('ss:Data', namespaces=ns)
                cell_value = cell_text_element.text if cell_text_element is not None and cell_text_element.text is not None else ''
                row_data.append(cell_value)
            if len(row_data) < len(header):
                row_data.extend([''] * (len(header) - len(row_data)))
            data.append(row_data)

        return pd.DataFrame(data, columns=header)
    except FileNotFoundError:
        print(f"致命错误: 数据文件未找到 '{file_path}'。请确保文件存在。")
        return None
    except Exception as e:
        print(f"致命错误: 解析XML文件 '{file_path}' 时失败: {e}")
        return None

# --- 解析器 2: 用于 lease_service_order.xml 格式 ---
def _parse_service_order_xml(file_path: str) -> Optional[List[Dict[str, Any]]]:
    """
    专门用于解析工单XML的函数，返回一个字典列表。
    """
    try:
        namespaces = {'ss': 'urn:schemas-microsoft-com:office:spreadsheet'}
        tree = ET.parse(file_path)
        root = tree.getroot()
        table = root.find('.//ss:Table', namespaces)
        if table is None: return []
        rows = table.findall('ss:Row', namespaces)
        header_row = rows[0]
        headers = [
            elem.text 
            if (elem := cell.find('ss:Data', namespaces)) is not None and elem.text is not None 
            else "" 
            for cell in header_row.findall('ss:Cell', namespaces)
        ]
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
        return orders
    except FileNotFoundError:
        print(f"致命错误: 数据文件未找到 '{file_path}'。")
        return None
    except Exception as e:
        print(f"致命错误: 解析XML文件 '{file_path}' 时失败: {e}")
        return None

# --- 内部辅助函数，用于日期转换 ---
def _convert_excel_date(excel_date: Any) -> Any:
    """将Excel序列号日期转换为标准日期时间字符串。"""
    try:
        num_date = float(excel_date)
        base_date = datetime(1899, 12, 30)
        dt = base_date + timedelta(days=num_date)
        # 如果有时间部分则保留，否则只保留日期
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return excel_date

# --- 以下是带缓存的、供外部调用的函数 ---
@lru_cache(maxsize=None)
def get_master_base_df() -> Optional[pd.DataFrame]:
    """
    加载并缓存 master_base.xml 数据。
    lru_cache 装饰器确保这个函数只在第一次被调用时真正执行。
    之后的所有调用将立即返回内存中的缓存结果。
    """
    print("--- [Cache] 首次加载并解析 master_base.xml ---")
    return _parse_spreadsheetml('services/master_base.xml')

@lru_cache(maxsize=None)
def get_master_guest_df() -> Optional[pd.DataFrame]:
    """
    加载并缓存 master_guest.xml 数据。
    所有的数据清洗和类型转换都在这里一次性完成。
    """
    print("--- [Cache] 首次加载并解析 master_guest.xml ---")
    df = _parse_spreadsheetml('services/master_guest.xml')
    try:
        if df is None or df.empty:
            return None

        # --- 在这里进行所有一次性的数据预处理 ---
        if 'id' not in df.columns:
            print("错误: 'master_guest.xml' 中缺少 'id' 列。")
            return None
            
        df['id'] = pd.to_numeric(df['id'], errors='coerce')
        df.dropna(subset=['id'], inplace=True)
        df['id'] = df['id'].astype(int)

        date_columns = ['birth', 'create_datetime', 'modify_datetime']
        for col in date_columns:
            if col in df.columns:
                df[col] = df[col].apply(_convert_excel_date)
        
        print(f"--- [Cache] 成功加载并预处理了 {len(df)} 条客户记录。 ---")
        return df
    except Exception as e:
        print(f"错误: 在预处理 'master_guest.xml' 数据时失败: {e}")
        return None

@lru_cache(maxsize=None)
def get_lease_service_orders() -> Optional[List[Dict[str, Any]]]:
    """加载并缓存 lease_service_order.xml 数据，返回字典列表。"""
    print("--- [Cache] 首次加载并解析 lease_service_order.xml ---")
    return _parse_service_order_xml('services/lease_service_order.xml')

# 如果还有其他XML文件，请在这里为它们添加类似的 get_..._df() 函数