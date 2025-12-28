import json
import re
import ast
import calendar
from datetime import date
from typing import Optional, Union, List, Any, Tuple

def clean_string_val(val: Any) -> Optional[str]:
    """
    清洗单个字符串值。
    处理如 "I'", '"I"', "'I'" 这种带有奇怪引号的脏数据。
    """
    if val is None:
        return None
    s = str(val).strip()
    # 去除首尾可能误带的单引号或双引号 (针对 "I'" 或 "'A'" 这种情况)
    s = s.strip("'").strip('"')
    return s

def smart_parse_list(val: Any, element_type=None) -> Optional[List[Any]]:
    """
    智能列表解析器。
    
    能够处理:
    - List 对象: ['A'] -> ['A']
    - JSON 字符串: '["A", "B"]' -> ['A', 'B']
    - Python 字符串: "['A', 'B']" -> ['A', 'B']
    - 单个值(非列表格式): "B" -> ['B']
    - 脏数据: "['A']" (带有多余引号的字符串)
    
    Args:
        val: 输入值
        element_type: (可选) 转换列表元素的类型，如 int, float, str
    """
    if val is None:
        return None
    
    # 1. 如果已经是列表，直接处理元素类型
    if isinstance(val, list):
        result = val
    else:
        # 2. 尝试解析字符串
        s_val = str(val).strip()
        
        # 2.1 看起来像列表 [...]
        if s_val.startswith('[') and s_val.endswith(']'):
            try:
                # 优先尝试标准 JSON
                result = json.loads(s_val)
            except Exception:
                try:
                    # 其次尝试 Python 字面量 (处理单引号)
                    result = ast.literal_eval(s_val)
                except Exception:
                    # 最后的倔强：手动拆分 (针对极其糟糕的格式)
                    content = s_val[1:-1]
                    if not content:
                        result = []
                    else:
                        # 简单按逗号拆分，并清洗引号
                        result = [x.strip().strip("'").strip('"') for x in content.split(',')]
        else:
            # 2.2 不像列表，视为单个值，包裹成列表
            # 先清洗一下脏引号
            clean_val = clean_string_val(s_val)
            result = [clean_val] if clean_val else []

    # 3. 统一转换元素类型 (如果指定)
    if element_type and result:
        try:
            return [element_type(x) for x in result]
        except Exception:
            # 如果转换失败（比如 'A' 转 int），返回原样或空，这里选择原样以便报错在逻辑层处理
            return result
            
    return result


def normalize_list_param(val: Union[str, List[str], None]) -> Union[str, List[str], None]:
    """
    清洗参数，将 JSON 格式的字符串列表转换为 Python 列表。
    
    场景: 大模型有时会传 '["行政单间"]' (字符串) 而不是 ['行政单间'] (列表)。
    
    示例: 
    - 输入: '["行政单间"]' -> 输出: ['行政单间']
    - 输入: '行政单间'     -> 输出: '行政单间'
    """
    if not val:
        return val
    
    # 如果已经是列表，直接返回
    if isinstance(val, list):
        return val
    
    s_val = str(val).strip()
    
    # 检测是否为列表格式的字符串 (以 [ 开头，以 ] 结尾)
    if s_val.startswith('[') and s_val.endswith(']'):
        try:
            # 尝试标准 JSON 解析
            return json.loads(s_val)
        except Exception:
            # 容错解析 (处理单引号等非标准JSON，如 "['A', 'B']")
            # 去除首尾括号 -> 按逗号分割 -> 去除每一项的首尾引号和空格
            return [x.strip().strip("'").strip('"') for x in s_val[1:-1].split(',') if x.strip()]
            
    # 普通字符串，原样返回
    return val

def smart_parse_date(date_val: Any) -> Tuple[Optional[str], Optional[str]]:
    """
    辅助函数：解析模糊的日期字符串，返回标准化的 (起始日期, 结束日期)。
    
    输入示例:
    - '2025'       -> ('2025-01-01', '2025-12-31')
    - '2025.08'    -> ('2025-08-01', '2025-08-31')
    - '20250801'   -> ('2025-08-01', '2025-08-01')
    """
    if not date_val:
        return None, None
    
    s_val = str(date_val).strip()
    
    # 模式1: 纯年份 (YYYY) -> 整年
    match_year = re.match(r'^(\d{4})$', s_val)
    if match_year:
        year = int(match_year.group(1))
        return f"{year}-01-01", f"{year}-12-31"

    # 模式2: 年月 (YYYY-MM, YYYY.MM, YYYYMM) -> 整月
    # 处理 6位数字(202508) 或 分隔符
    match_month = re.match(r'^(\d{4})[-./]?(\d{1,2})$', s_val)
    if match_month:
        year, month = int(match_month.group(1)), int(match_month.group(2))
        if 1 <= month <= 12:
            last_day = calendar.monthrange(year, month)[1]
            return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day}"

    # 模式3: 年月日 (YYYY-MM-DD, YYYY.MM.DD, YYYYMMDD) -> 单日
    match_day = re.match(r'^(\d{4})[-./]?(\d{1,2})[-./]?(\d{1,2})$', s_val)
    if match_day:
        year, month, day = int(match_day.group(1)), int(match_day.group(2)), int(match_day.group(3))
        try:
            d_obj = date(year, month, day)
            fmt_d = d_obj.strftime('%Y-%m-%d')
            return fmt_d, fmt_d # 起止相同
        except ValueError:
            pass 

    # 无法解析，原样返回 None 让后续逻辑报错
    return None, None


def fix_gender_misplaced_in_nation(nation: Any, gender: Any) -> Tuple[Any, Any]:
    """
    纠错函数：检测大模型是否错误地将 '男'/'女' 填入了 nation 字段。
    处理原始输入，兼容 str, list 或 JSON string。
    
    场景: 
    - 输入 nation="女" -> 返回 (None, "女")
    - 输入 nation='["女"]' -> 返回 (None, "女")
    - 输入 nation="中国" -> 返回 ("中国", 原gender)
    """
    if not nation:
        return nation, gender
        
    # 1. 暴力清洗：移除所有列表相关的符号，只保留核心文本
    # 这样无论是 "女", "['女']", '["女"]' 都会变成 "女"
    s_val = str(nation).strip()
    clean_val = s_val.replace('[', '').replace(']', '').replace('"', '').replace("'", "").strip()
    
    # 2. 定义精确匹配的性别关键词 (防止误伤 "越南" 这种含男字的国家)
    male_keywords = {'男', '男性', 'Male', 'man'}
    female_keywords = {'女', '女性', 'Female', 'woman'}
    
    # 3. 判定与替换
    if clean_val in male_keywords:
        # 发现填错了，nation 置空，gender 修正为 '男'
        return None, '男'
    
    if clean_val in female_keywords:
        # 发现填错了，nation 置空，gender 修正为 '女'
        return None, '女'
            
    # 如果不是性别，原样返回
    return nation, gender