import sys
import os
import logging
import re
from typing import Optional, Union, List, Any
from datetime import datetime

# ==========================================
# 导入处理
# ==========================================
try:
    from .db import get_db_cursor
    from .param_parser import normalize_list_param, smart_parse_date, fix_gender_misplaced_in_nation
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor
    from utils.param_parser import normalize_list_param, smart_parse_date, fix_gender_misplaced_in_nation

logger = logging.getLogger("GuestDetailsLogic")

def get_filtered_details_logic(
        name: Optional[str] = None,
        room_number: Optional[str] = None,
        gender: Optional[str] = None,
        status: Union[str, List[str]] = None,
        nation: Optional[str] = None,
        min_age: Optional[int] = None,
        max_age: Optional[int] = None,
        min_rent: Optional[float] = None,
        max_rent: Optional[float] = None,
        start_arr_date: Optional[Any] = None,
        end_arr_date: Optional[Any] = None,
        pet: Optional[str] = None,
        room_type: Optional[Union[str, List[str]]] = None
) -> str:
    logger.info(f"执行住客详情查询: Status={status}")

    # ==========================================
    # 0. 性别、国籍 参数清洗与纠错
    # ==========================================
    # 这会把 nation="女" 变成 nation=None, gender="女"
    nation, gender = fix_gender_misplaced_in_nation(nation, gender)

    # ==========================================
    # 1. 参数清洗
    # ==========================================
    status = normalize_list_param(status)
    room_type = normalize_list_param(room_type)

    # ==========================================
    # 2. 智能日期纠错
    # ==========================================
    
    # 场景 A: start 和 end 内容完全一样 (例如大模型都填了 '2025')
    if start_arr_date and end_arr_date and str(start_arr_date).strip() == str(end_arr_date).strip():
        s_val = str(start_arr_date).strip()
        if re.match(r'^\d{4}-\d{2}-\d{2}$', s_val):
            pass # 保持原样
        else:
            # 调用辅助函数解析
            s_res, e_res = smart_parse_date(start_arr_date)
            if s_res and e_res:
                logger.info(f"日期纠错(相同输入): {start_arr_date} -> {s_res} 至 {e_res}")
                start_arr_date = s_res
                end_arr_date = e_res

    # 场景 B: 只有 start 没有 end (例如 '2025.05')
    elif start_arr_date and not end_arr_date:
        # 如果是标准格式，说明用户意图非常明确（查询从这一天开始的所有数据），无需任何处理！
        s_val = str(start_arr_date).strip()
        if re.match(r'^\d{4}-\d{2}-\d{2}$', s_val):
            pass  # 直接跳过，保持 start_arr_date 原值，end_arr_date 为 None
        else:
            s_res, e_res = smart_parse_date(s_val)
            # 只有当解析出的是一个范围(例如整月/整年)时，才自动补全 end
            if s_res and e_res:
                logger.info(f"日期纠错(单一范围): {start_arr_date} -> {s_res} 至 {e_res}")
                start_arr_date = s_res
                end_arr_date = e_res
            elif s_res:
                start_arr_date = s_res # 仅格式化 start

    # 场景 C: start 和 end 都不为空且不相同 (分别清洗)
    else:
        # 1. 处理 Start Date
        if start_arr_date:
            s_val = str(start_arr_date).strip()
            # 只有不符合 YYYY-MM-DD 时才解析
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', s_val):
                s_min, _ = smart_parse_date(s_val)
                # 对于 Start，取解析结果的“起始值” (s_min)
                # 例如输入 '2025' -> 取 '2025-01-01'
                if s_min: start_arr_date = s_min
        
        # 2. 处理 End Date
        if end_arr_date:
            e_val = str(end_arr_date).strip()
            # 只有不符合 YYYY-MM-DD 时才解析
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', e_val):
                _, e_max = smart_parse_date(e_val)
                # 对于 End，取解析结果的“结束值” (e_max)
                # 例如输入 '2025' -> 取 '2025-12-31' (这一点非常重要！)
                if e_max: end_arr_date = e_max

    # ==========================================
    # 2. 最终合法性校验 (防止脏数据穿透)
    # ==========================================
    try:
        s_date_obj = None
        e_date_obj = None

        if start_arr_date:
            s_date_obj = datetime.strptime(str(start_arr_date), '%Y-%m-%d').date()
        
        if end_arr_date:
            e_date_obj = datetime.strptime(str(end_arr_date), '%Y-%m-%d').date()

        if s_date_obj and e_date_obj and s_date_obj > e_date_obj:
            return {
                "count": 0, "analysis": None, 
                "error": f"日期逻辑错误: 起始日期 ({start_arr_date}) 不能晚于 结束日期 ({end_arr_date})"
            }
            
    except ValueError:
        return {
            "count": 0, "analysis": None, 
            "error": f"日期格式无效，无法自动修复。请严格使用 YYYY-MM-DD 格式。"
        }

    params_inner = []
    conditions = ["1=1"]

    # --- 1. CTE 内部筛选 ---
    if name:
        conditions.append("t.resident_name ILIKE %s")
        params_inner.append(f"%{name}%")
    if room_number:
        conditions.append("t.room_number = %s")
        params_inner.append(room_number)
    if gender:
        conditions.append("t.gender = %s")
        params_inner.append(gender)
    if nation:
        conditions.append("t.nationality ILIKE %s")
        params_inner.append(f"%{nation}%")
    
    if pet:
        pet_val = str(pet).lower().strip()
        if pet_val in ['yes', 'true', '1', '有']:
            conditions.append("(t.has_pet IS NOT NULL AND t.has_pet != '')")
        elif pet_val in ['no', 'false', '0', '无']:
            conditions.append("(t.has_pet IS NULL OR t.has_pet = '')")

    if min_age is not None:
        conditions.append("t.age >= %s")
        params_inner.append(min_age)
    if max_age is not None:
        conditions.append("t.age <= %s")
        params_inner.append(max_age)

    if start_arr_date:
        conditions.append("t.arrival_date >= %s")
        params_inner.append(start_arr_date)
    if end_arr_date:
        conditions.append("t.arrival_date <= %s")
        params_inner.append(end_arr_date)

    if room_type:
        if isinstance(room_type, list):
            conditions.append("dt.room_code_desc = ANY(%s)")
            params_inner.append(room_type)
        else:
            conditions.append("dt.room_code_desc = %s")
            params_inner.append(room_type)

    if status:
        if isinstance(status, list):
            conditions.append("t.status = ANY(%s)")
            params_inner.append(status)
        else:
            conditions.append("t.status = %s")
            params_inner.append(status)

    # --- 2. CTE 外部筛选 ---
    params_outer = []
    rent_conditions = []
    
    if min_rent is not None:
        rent_conditions.append("rent >= %s")
        params_outer.append(float(min_rent))
    if max_rent is not None:
        rent_conditions.append("rent <= %s")
        params_outer.append(float(max_rent))

    base_where = " AND ".join(conditions)
    outer_where = " AND ".join(rent_conditions) if rent_conditions else "1=1"
    full_params = tuple(params_inner + params_outer)

    # --- 3. 构造查询 SQL (关键修改点) ---
    # 使用 COUNT(*) OVER() 计算总数，而不受 LIMIT 影响
    sql = f"""
    WITH base_data AS (
        SELECT 
            t.account_no,
            t.resident_name,
            t.gender,
            t.age,
            t.nationality,
            t.room_number,
            t.status,
            COALESCE(ds.status_desc, t.status) as status_desc, 
            t.arrival_date,
            t.departure_date,
            t.remark,
            t.has_pet,
            COALESCE(dt.room_code_desc, '未知房型') as room_code_desc,
            (
                SELECT actual_monthly_rent 
                FROM contract_creation_log c 
                WHERE c.room_number = t.room_number 
                AND c.check_in_date <= (
                    CASE 
                        WHEN t.status IN ('I', 'W', 'P') THEN CURRENT_DATE 
                        ELSE t.arrival_date 
                    END
                )
                ORDER BY c.check_in_date DESC 
                LIMIT 1
            ) as rent
        FROM tenant_analysis_report t
        LEFT JOIN dim_room_type dt ON t.room_code = dt.room_code
        LEFT JOIN dim_status_map ds ON t.status = ds.status
        WHERE {base_where}
    )
    SELECT 
        *,
        COUNT(*) OVER() as total_match_count  -- [关键] 计算符合条件的总行数
    FROM base_data 
    WHERE {outer_where}
    ORDER BY room_number ASC, arrival_date DESC
    LIMIT 100
    """

    try:
        with get_db_cursor() as cur:
            cur.execute(sql, full_params)
            rows = cur.fetchall()
            return _format_details_report(rows)

    except Exception as e:
        logger.error(f"住客详情查询失败: {e}", exc_info=True)
        return f"数据库查询出错: {str(e)}"

def _format_details_report(rows):
    if not rows:
        return "--- 未找到符合条件的住客记录 ---"

    # 获取真实总数 (从第一行数据中获取)
    total_count = rows[0]['total_match_count']
    current_count = len(rows)
    
    lines = []
    
    # [关键] 动态生成头部提示信息
    if total_count > 100:
        lines.append(f"查询到 {total_count} 条数据，由于数据量过大，仅返回前 {current_count} 条数据")
    else:
        lines.append(f"--- 共找到 {total_count} 条记录 ---")
        
    lines.append("==================================================")

    for row in rows:
        acc_no = row['account_no']
        name = row['resident_name']
        gender = row['gender'] or "未知"
        age = row['age'] if row['age'] else "未知"
        nation = row['nationality'] or "未知"
        room = row['room_number']
        rtype = row['room_code_desc']
        status_code = row['status']
        status_desc = row['status_desc']
        status_display = f"{status_desc} ({status_code})" if status_desc and status_code != status_desc else status_code
        arr = row['arrival_date']
        dep = row['departure_date']
        rent_val = row['rent']
        rent_str = f"{float(rent_val):,.2f}" if rent_val is not None else "N/A"
        remark = str(row['remark']).strip() if row['remark'] else "无"
        pet_info = str(row['has_pet']).strip() if row['has_pet'] else "无"
        
        lines.append(f"客户ID:       {acc_no}")
        lines.append(f"姓名:         {name} ({gender}, {age}岁, {nation})")
        lines.append(f"房间信息:     {room} - {rtype}")
        lines.append(f"当前状态:     {status_display}")
        lines.append(f"宠物信息:     {pet_info}")
        lines.append(f"租期:         {arr} 至 {dep}")
        lines.append(f"月租金:       {rent_str} 元")
        lines.append(f"备注:         {remark}")
        lines.append("==================================================")
        
    # 如果被截断，在底部再次提醒
    # if total_count > 100:
    #     lines.append(f"... (还有 {total_count - 100} 条记录未显示) ...")

    return "\n".join(lines)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(">>> 调试 utils/guest_details.py <<<")
    
    # 场景 1: 在住 + 宠物
    print("\n--- 测试: 在住 + 有宠物 ---")
    print(get_filtered_details_logic(
        status='I',
        pet='yes'
    ))

    # 场景 2: 在住 + 男性 (修正了原来的 nation='男' 错误)
    print("\n--- 测试: 在住 + 男性 ---")
    print(get_filtered_details_logic(status='I', gender='男'))

    # 场景 3: 租金筛选 (验证参数顺序是否正确)
    print("\n--- 测试: 租金 > 15000 ---")
    print(get_filtered_details_logic(status='I', min_rent=15000))

    # 场景 4: 组合列表筛选
    print("\n--- 测试: 状态(在住/挂账) + 房型(行政单间) ---")
    print(get_filtered_details_logic(status=['I'], room_type=['行政单间']))