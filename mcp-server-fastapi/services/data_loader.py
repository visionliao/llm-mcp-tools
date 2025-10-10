# services/data_loader.py

import pandas as pd
from lxml import etree
from functools import lru_cache
from typing import Optional

# 这是一个内部辅助函数，我们不直接在外部调用它
def _parse_spreadsheetml(file_path: str) -> Optional[pd.DataFrame]:
    """
    一个通用的、底层的 SpreadsheetML XML 解析器。
    注意：这个函数本身不应该被缓存，因为我们希望缓存的是加载特定文件的结果。
    """
    try:
        # (这里可以粘贴您最完善的那个 parse_spreadsheetml 函数的内部逻辑)
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
    except Exception as e:
        print(f"致命错误: 解析XML文件 '{file_path}' 时失败: {e}")
        # 在生产环境中，这里应该使用日志记录
        return None

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
    """加载并缓存 master_guest.xml 数据。"""
    print("--- [Cache] 首次加载并解析 master_guest.xml ---")
    return _parse_spreadsheetml('services/master_guest.xml')

@lru_cache(maxsize=None)
def get_lease_service_order_df() -> Optional[pd.DataFrame]:
    """加载并缓存 lease_service_order.xml 数据。"""
    print("--- [Cache] 首次加载并解析 lease_service_order.xml ---")
    return _parse_spreadsheetml('services/lease_service_order.xml')

# 如果还有其他XML文件，请在这里为它们添加类似的 get_..._df() 函数