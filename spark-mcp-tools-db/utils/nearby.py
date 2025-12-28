import sys
import os
import re
import logging
import datetime
from typing import Optional, Union, List

try:
    from .db import get_db_cursor
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor

logger = logging.getLogger("NearbyLogic")

def has_four(num: int) -> bool:
    """检查数字是否包含 4"""
    return '4' in str(num)

def get_valid_neighbor_val(current_val: int, step: int) -> int:
    """计算下一个有效的楼层或序号 (跳过含4的数字)"""
    next_val = current_val + step
    while has_four(next_val):
        next_val += step
    return next_val

def nearby_report_logic(room_input: Union[str, List[str]]) -> str:
    """
    查询指定房间及其周边的当前入住状态。
    逻辑更新：
    1. 严格遵循“逢4必跳”规则计算邻居。
    2. SQL查询逻辑变更：优先信任 'status' 字段。只要最新记录是 I/W/P，即视为在住，不再强制校验日期。
    """
    # 1. 参数清洗
    target_room = ""
    if isinstance(room_input, list):
        for r in room_input:
            if r and str(r).strip():
                target_room = str(r).strip()
                break
    elif isinstance(room_input, str):
        parts = re.split(r'[\s,]+', room_input)
        if parts:
            target_room = parts[0].strip()

    if not target_room:
        return "输入错误：未能解析出有效的房间号。"

    logger.info(f"查询周边 (以状态为准): 目标={target_room}")

    # 2. 解析房号结构 & 计算周边
    match = re.match(r'^([A-Z]+)(\d+)$', target_room)
    if not match:
        return f"房间号格式无法解析: {target_room}"

    prefix = match.group(1)   
    num_str = match.group(2)  
    
    if len(num_str) < 3:
        return f"房间号数字过短: {target_room}"

    seq_str = num_str[-2:]       
    floor_str = num_str[:-2]     
    
    try:
        curr_floor = int(floor_str)
        curr_seq = int(seq_str)
    except ValueError:
        return f"房间号解析失败: {target_room}"

    # 计算周边 (跳过含4)
    relations = {} 
    
    # 左邻
    if curr_seq > 1:
        left_seq = get_valid_neighbor_val(curr_seq, -1)
        if left_seq > 0:
            left_room = f"{prefix}{curr_floor}{str(left_seq).zfill(2)}"
            relations[left_room] = "左邻"
    
    # 右舍
    right_seq = get_valid_neighbor_val(curr_seq, 1)
    right_room = f"{prefix}{curr_floor}{str(right_seq).zfill(2)}"
    relations[right_room] = "右舍"
    
    # 楼上
    up_floor = get_valid_neighbor_val(curr_floor, 1)
    up_room = f"{prefix}{up_floor}{seq_str}"
    relations[up_room] = "楼上"
    
    # 楼下
    if curr_floor > 1:
        down_floor = get_valid_neighbor_val(curr_floor, -1)
        if down_floor > 0:
            down_room = f"{prefix}{down_floor}{seq_str}"
            relations[down_room] = "楼下"

    target_list = list(relations.keys())
    
    if not target_list:
        return "无法计算出周边房间 (可能目标房间号本身异常)。"

    try:
        with get_db_cursor() as cur:
            # -------------------------------------------------------
            # 步骤 3: 数据库查询 (使用 Lateral Join 获取最新状态)
            # -------------------------------------------------------
            # 逻辑：对于列表中的每个房间，查找 tenant 表中最新的一条记录。
            # 如果那条记录的状态是 I/W/P/R/A，则显示出来；否则显示空置。
            
            sql_nearby = """
                SELECT 
                    rd.room_number,
                    rd.room_code_desc,
                    rd.rent_12_months,
                    t_latest.resident_name,
                    t_latest.account_no,
                    t_latest.status,
                    ds.status_desc,
                    t_latest.arrival_date,
                    t_latest.departure_date,
                    t_latest.remark,
                    (
                        SELECT actual_monthly_rent 
                        FROM contract_creation_log c 
                        WHERE c.room_number = rd.room_number 
                        ORDER BY c.check_in_date DESC 
                        LIMIT 1
                    ) as contract_rent
                FROM room_details rd
                -- 使用 LATERAL JOIN 查找该房间最新的有效租住记录
                LEFT JOIN LATERAL (
                    SELECT * 
                    FROM tenant_analysis_report t
                    WHERE t.room_number = rd.room_number
                    -- 只关注活跃状态，忽略已结账(O)或取消(X)的历史
                    -- 如果某房间最后一条记录是 O，这里查不到，就会显示空置，符合逻辑
                    AND t.status IN ('I', 'W', 'P', 'R', 'A')
                    ORDER BY t.arrival_date DESC 
                    LIMIT 1
                ) t_latest ON true
                LEFT JOIN dim_status_map ds ON t_latest.status = ds.status
                WHERE rd.room_number = ANY(%s)
                ORDER BY rd.building_no, rd.floor DESC, rd.room_number ASC
            """
            
            cur.execute(sql_nearby, (target_list,))
            rows = cur.fetchall()

            if not rows:
                return f"未在数据库中找到房间 {target_room} 的周边房间信息。"

            return _format_nearby_plain_text(rows, relations, target_room)

    except Exception as e:
        logger.error(f"周边查询失败: {e}")
        return f"数据库查询出错: {str(e)}"

def _format_nearby_plain_text(rows, relations, target_room):
    lines = []
    lines.append(f"--- 目标房间 {target_room} 的周边邻居状态 ---")
    lines.append(f"共找到 {len(rows)} 个相邻房间。")
    
    # 排序权重: 楼上(1) -> 左(2) -> 右(3) -> 楼下(4)
    def sort_key(row):
        rel = relations.get(row['room_number'], "")
        if "楼上" in rel: return 1
        if "左邻" in rel: return 2
        if "右舍" in rel: return 3
        if "楼下" in rel: return 4
        return 99

    sorted_rows = sorted(rows, key=sort_key)

    for r in sorted_rows:
        r_no = r['room_number']
        relation = relations.get(r_no, "周边")
        rtype = r['room_code_desc'] or "未知房型"
        
        # 状态处理
        if r['status']:
            # 有活跃记录 (I, W, P, R, A)
            status_desc = r['status_desc'] or r['status']
            status_str = f"{status_desc} ({r['status']})"
            is_occupied = True
        else:
            # 查不到活跃记录 -> 视为空置
            status_str = "空置"
            is_occupied = False
        
        # 租金逻辑
        if is_occupied and r['contract_rent']:
            rent_val = float(r['contract_rent'])
            rent_source = "实际签约"
        elif r['rent_12_months']:
            rent_val = float(r['rent_12_months'])
            rent_source = "挂牌参考"
        else:
            rent_val = 0.0
            rent_source = "未知"
            
        rent_str = f"{rent_val:,.0f} ({rent_source})"

        lines.append("-" * 40)
        lines.append(f"房间: {r_no} [{relation}]")
        lines.append(f"房型: {rtype}")
        lines.append(f"状态: {status_str}")
        lines.append(f"租金: {rent_str}")
        
        if is_occupied and r['resident_name']:
            arr = str(r['arrival_date'])
            dep = str(r['departure_date'])
            lines.append(f"住客: {r['resident_name']}")
            lines.append(f"ID:   {r['account_no']}")
            lines.append(f"租期: {arr} 至 {dep}")
            
            if r['remark']:
                clean_remark = str(r['remark']).replace('\n', ' ').strip()
                if clean_remark:
                    lines.append(f"备注: {clean_remark}")

    lines.append("-" * 40)
    return "\n".join(lines)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(">>> 调试 utils/nearby.py <<<")
    # 测试 A213 的周边
    print(nearby_report_logic("A213"))