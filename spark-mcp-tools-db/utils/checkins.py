import datetime
import sys
import os
import logging
from collections import Counter

try:
    from .db import get_db_cursor
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor

logger = logging.getLogger("CheckinsLogic")

# 严格限制仅支持这6种状态
VALID_STATUSES = {'I', 'R', 'O', 'S', 'P', 'A', 'ALL'}

# 轨道分类
WEEKLY_STATUS_MAP = {'A': '将到', 'P': '预离'}  # Track B
TENANT_STATUS_LIST = ['I', 'R', 'O', 'S']      # Track A

def query_checkins_logic(start: str, end: str, status_code: str = 'ALL') -> str:
    """
    双轨制入住记录查询 (基于事件时间)：
    1. Tenant Track (I, R, O, S): 
       - I/R: 查 arrival_date
       - O/S: 查 departure_date
    2. Weekly Track (A, P): 
       - A: 查 arrival_date
       - P: 查 departure_date
    """
    status_code = status_code.upper().strip()
    logger.info(f"查询范围: {start} 至 {end}, 状态: {status_code}")

    try:
        start_date = datetime.datetime.strptime(start, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end, '%Y-%m-%d').date()
    except ValueError:
        return "输入错误：日期格式不正确，请使用 'YYYY-MM-DD' 格式。"

    if status_code not in VALID_STATUSES:
        return f"输入错误：无效的状态代码 '{status_code}'。仅支持: I, R, O, S, P, A"

    all_records = []

    try:
        with get_db_cursor() as cur:
            # 1. 准备基础字典
            cur.execute("SELECT status, status_desc FROM dim_status_map")
            status_desc_map = {row['status']: row['status_desc'] for row in cur.fetchall()}

            # [新增] 获取当前查询状态的中文描述
            current_status_desc = "全部" # 默认值
            if status_code != 'ALL':
                # 从数据库字典中获取，如果没找到则显示未知
                current_status_desc = status_desc_map.get(status_code, "未知状态")
            
            cur.execute("SELECT room_code, room_code_desc FROM dim_room_type")
            room_type_map = {r['room_code']: r['room_code_desc'] for r in cur.fetchall()}

            # =======================================================
            # Track A: 查询 tenant_analysis_report (I, R, O, S)
            # =======================================================
            if status_code == 'ALL' or status_code in TENANT_STATUS_LIST:
                records_a = _query_tenant_track(
                    cur, start_date, end_date, status_code, status_desc_map, room_type_map
                )
                all_records.extend(records_a)

            # =======================================================
            # Track B: 查询 arrival_departure_weekly (A, P)
            # =======================================================
            if status_code == 'ALL' or status_code in WEEKLY_STATUS_MAP:
                records_b = _query_weekly_track(
                    cur, start_date, end_date, status_code, room_type_map
                )
                all_records.extend(records_b)

            # 按事件发生时间倒序排序
            # I/R/A 按 arrival_date, O/S/P 按 departure_date
            # 为了统一排序，这里简单按记录中存在的有效日期排序
            all_records.sort(key=lambda x: x['sort_date'] or datetime.date.min, reverse=True)

            return _format_checkin_report(all_records, start, end, status_code, current_status_desc)

    except Exception as e:
        logger.error(f"查询失败: {e}")
        return f"数据库查询出错: {str(e)}"

def _query_tenant_track(cur, start_date, end_date, status_code, status_map, room_map):
    """
    查询 I, R, O, S
    逻辑：根据状态类型匹配不同的时间字段
    """
    params = []
    conditions = []

    # 1. 构建时间过滤逻辑
    # I, R -> 入住时间
    if status_code in ['I', 'R']:
        conditions.append("(t.status = %s AND t.arrival_date BETWEEN %s AND %s)")
        params.extend([status_code, start_date, end_date])
    
    # O, S -> 离店时间
    elif status_code in ['O', 'S']:
        conditions.append("(t.status = %s AND t.departure_date BETWEEN %s AND %s)")
        params.extend([status_code, start_date, end_date])
    
    # ALL -> 混合逻辑
    elif status_code == 'ALL':
        # I, R 查入住
        conditions.append("(t.status IN ('I', 'R') AND t.arrival_date BETWEEN %s AND %s)")
        params.extend([start_date, end_date])
        # O, S 查离店
        conditions.append("(t.status IN ('O', 'S') AND t.departure_date BETWEEN %s AND %s)")
        params.extend([start_date, end_date])

    if not conditions:
        return []

    where_clause = " OR ".join(conditions)

    sql = f"""
        SELECT 
            t.room_number, t.room_code, t.status, 
            t.resident_name, t.account_no, 
            t.arrival_date, t.departure_date, t.remark,
            (
                SELECT actual_monthly_rent FROM contract_creation_log c 
                WHERE c.room_number = t.room_number AND c.check_in_date <= t.arrival_date 
                ORDER BY c.check_in_date DESC LIMIT 1
            ) as rent
        FROM tenant_analysis_report t
        WHERE {where_clause}
    """
    
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    
    results = []
    for r in rows:
        # 确定用于排序的日期
        sort_date = r['arrival_date'] if r['status'] in ['I', 'R'] else r['departure_date']
        
        results.append({
            'sort_date': sort_date,
            'arr': r['arrival_date'],
            'dep': r['departure_date'],
            'room': r['room_number'],
            'type': room_map.get(r['room_code'], r['room_code']),
            'rent': r['rent'],
            'status_code': r['status'],
            'status_desc': status_map.get(r['status'], r['status']),
            'resident': f"{r['resident_name']}({r['account_no']})",
            'remark': r['remark'] or ""
        })
    return results

def _query_weekly_track(cur, start_date, end_date, status_code, room_map):
    """
    查询 A(将到), P(预离)
    逻辑：A 查 arrival_date, P 查 departure_date
    """
    params = []
    conditions = []
    
    # A -> 将到 -> 查 arrival_date
    if status_code in ['A', 'ALL']:
        conditions.append("(status = '将到' AND arrival_date::date BETWEEN %s AND %s)")
        params.extend([start_date, end_date])
        
    # P -> 预离 -> 查 departure_date
    if status_code in ['P', 'ALL']:
        conditions.append("(status = '预离' AND departure_date::date BETWEEN %s AND %s)")
        params.extend([start_date, end_date])
        
    if not conditions:
        return []

    where_clause = " OR ".join(conditions)
    
    sql = f"""
        SELECT 
            room_number, room_code, status,
            resident_name, account_no,
            arrival_date, departure_date, remark, room_rate
        FROM arrival_departure_weekly
        WHERE {where_clause}
    """
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()
    
    results = []
    for r in rows:
        code = 'A' if r['status'] == '将到' else 'P'
        
        # 确定排序日期
        sort_date = r['arrival_date'] if code == 'A' else r['departure_date']
        if isinstance(sort_date, datetime.datetime):
            sort_date = sort_date.date()

        # 租金兜底
        rent_val = float(r['room_rate'] or 0)
        if rent_val == 0:
             # A 用入住日查合同，P 用入住日(不是离店日)查合同
             # 注意：即使是预离(P)，我们查合同也是用它的 arrival_date 去匹配 check_in_date
             c_anchor_date = r['arrival_date'] 
             cur.execute("""
                SELECT actual_monthly_rent FROM contract_creation_log 
                WHERE room_number = %s AND check_in_date <= %s 
                ORDER BY check_in_date DESC LIMIT 1
             """, (r['room_number'], c_anchor_date))
             c_row = cur.fetchone()
             if c_row: rent_val = float(c_row['actual_monthly_rent'])

        results.append({
            'sort_date': sort_date,
            'arr': r['arrival_date'].date() if isinstance(r['arrival_date'], datetime.datetime) else r['arrival_date'],
            'dep': r['departure_date'].date() if isinstance(r['departure_date'], datetime.datetime) else r['departure_date'],
            'room': r['room_number'],
            'type': room_map.get(r['room_code'], r['room_code']),
            'rent': rent_val,
            'status_code': code,
            'status_desc': r['status'], 
            'resident': f"{r['resident_name']}({r['account_no']})",
            'remark': r['remark'] or ""
        })
    return results

def _format_checkin_report(records, start, end, status_code, status_desc_text):
    lines = []
    if status_code == 'ALL':
        title_part = f"{status_code}({status_desc_text})" # ALL(全部)
    else:
        title_part = f"{status_code}({status_desc_text})"

    lines.append(f"--- 查询 ({start} 至 {end}) 状态为 {title_part} 的结果---")

    # =========================================================
    # [修改点] 针对 ALL 状态生成的统计摘要
    # =========================================================
    summary_text = f"共找到 {len(records)} 条记录"

    if status_code == 'ALL':
        # 1. 统计各状态数量
        # 使用 Counter 统计 records 中 status_code 的出现次数
        counts = Counter(r['status_code'] for r in records)
        
        # 2. 定义显示的顺序和默认描述 (用于 count=0 时的兜底显示)
        # 注意：这里 status_desc 优先从 record 中取，取不到则用默认值
        target_stats = [
            ('I', '在住'), 
            ('R', '预定'), 
            ('O', '结账'), 
            ('S', '挂账'), 
            ('P', '预离'), 
            ('A', '将到')
        ]
        
        breakdown_parts = []
        for code, default_desc in target_stats:
            count = counts.get(code, 0)
            
            # 尝试从记录中获取真实的 desc (如果存在记录的话)，否则用默认值
            real_desc = default_desc
            if count > 0:
                # 找到第一个该状态的记录，提取其 desc
                for r in records:
                    if r['status_code'] == code:
                        real_desc = r['status_desc']
                        break
            
            # 格式化: I(在住) 5条
            breakdown_parts.append(f"{code}({real_desc}) {count}条")
        
        # 3. 拼接到摘要中
        breakdown_str = "、".join(breakdown_parts)
        summary_text += f"，包含 {breakdown_str}"

    lines.append(f"{summary_text}。\n")

    header = "{:<12} {:<12} {:<8} {:<12} {:<10} {:<10} {:<20} {:<20}".format(
        "入住日期", "离店日期", "房号", "房型", "租金", "状态", "住客(ID)", "备注"
    )
    lines.append(header)
    lines.append("-" * 115)

    for r in records:
        arr = str(r['arr'])
        dep = str(r['dep'])
        rent = f"{float(r['rent']):,.0f}" if r['rent'] else "-"
        status_display = f"{r['status_code']} {r['status_desc']}"
        remark = str(r['remark']).replace('\n',' ')
        if len(remark) > 15: remark = remark[:12] + "..."
        res = r['resident']
        if len(res) > 18: res = res[:15] + "..."
        rtype = str(r['type'])
        if len(rtype) > 10: rtype = rtype[:10]

        line = "{:<12} {:<12} {:<8} {:<12} {:<10} {:<10} {:<20} {:<20}".format(
            arr, dep, r['room'], rtype, rent, status_display, res, remark
        )
        lines.append(line)
        
    lines.append("-" * 115)
    return "\n".join(lines)



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print("\n[测试 在住 I]")
    print(query_checkins_logic("2025-09-01", "2025-09-14", "I"))

    print("\n[测试 预定 R]")
    print(query_checkins_logic("2025-08-01", "2025-12-31", "R"))

    print("\n[测试 结账 O]")
    print(query_checkins_logic("2025-08-01", "2025-08-31", "O"))

    print("\n[测试 挂账 S]")
    print(query_checkins_logic("2025-08-01", "2025-08-31", "S"))
    
    print("\n[测试 预离 P]")
    print(query_checkins_logic("2025-08-01", "2025-12-31", "P"))

    print("\n[测试 将到 A]")
    print(query_checkins_logic("2025-08-01", "2025-12-31", "A"))

    print(">>> 调试ALL checkins.py <<<")
    # 测试 ALL，只应包含 I/R/O/S/P/A
    print(query_checkins_logic("2025-09-01", "2025-09-14", "ALL"))

    