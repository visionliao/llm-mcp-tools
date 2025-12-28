import sys
import os
import logging
import re
from typing import Optional, Union, List, Dict, Any
from datetime import datetime
import json

try:
    from .db import get_db_cursor
    from .param_parser import normalize_list_param, smart_parse_date, fix_gender_misplaced_in_nation
except ImportError:
    # 假设本地调试时的路径处理
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor
    from utils.param_parser import normalize_list_param, smart_parse_date, fix_gender_misplaced_in_nation

logger = logging.getLogger("StatsLogic")

def get_guest_statistics_logic(
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
        room_type: Optional[Union[str, List[str]]] = None
) -> Dict[str, Any]:
    """
    住客统计核心逻辑 (多维度交叉分析版 + 宠物分析)。
    """
    logger.info("执行住客深度统计分析...")

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

    # params_base 用于 CTE 第一部分 (base_data)
    params_base = []
    conditions = ["1=1"]

    # --- 基础字段筛选 ---
    if name:
        conditions.append("t.resident_name ILIKE %s")
        params_base.append(f"%{name}%")
    if room_number:
        conditions.append("t.room_number = %s")
        params_base.append(room_number)
    if gender:
        conditions.append("t.gender = %s")
        params_base.append(gender)
    if nation:
        conditions.append("t.nationality ILIKE %s")
        params_base.append(f"%{nation}%")

    # --- 数值与日期 ---
    if min_age is not None:
        conditions.append("t.age >= %s")
        params_base.append(min_age)
    if max_age is not None:
        conditions.append("t.age <= %s")
        params_base.append(max_age)
    if start_arr_date:
        conditions.append("t.arrival_date >= %s")
        params_base.append(start_arr_date)
    if end_arr_date:
        conditions.append("t.arrival_date <= %s")
        params_base.append(end_arr_date)

    # --- 房型筛选 ---
    if room_type:
        if isinstance(room_type, list):
            conditions.append("dt.room_code_desc = ANY(%s)")
            params_base.append(room_type)
        else:
            conditions.append("dt.room_code_desc = %s")
            params_base.append(room_type)

    # --- 状态筛选 ---
    if status:
        if isinstance(status, list):
            conditions.append("t.status = ANY(%s)")
            params_base.append(status)
        else:
            conditions.append("t.status = %s")
            params_base.append(status)

    # --- 租金筛选 (params_outer 用于 CTE 第二部分 enriched_data) ---
    rent_conditions = []
    params_outer = []
    
    # 修复：使用参数化查询代替 f-string
    if min_rent is not None:
        rent_conditions.append("raw_rent >= %s")
        params_outer.append(float(min_rent))
    if max_rent is not None:
        rent_conditions.append("raw_rent <= %s")
        params_outer.append(float(max_rent))
    
    base_where = " AND ".join(conditions)
    # 修复：如果没有租金条件，保持 1=1
    outer_where = " AND ".join(rent_conditions) if rent_conditions else "1=1"

    # 合并所有参数：先 Base 的参数，再 Outer 的参数
    # 因为 CTE 执行顺序是先 base_data (params_base) -> enriched_data (params_outer)
    full_params = tuple(params_base + params_outer)

    # ==========================================
    # CTE 构建：数据预处理中心
    # ==========================================
    
    cte_sql = f"""
    WITH base_data AS (
        SELECT 
            t.age, 
            COALESCE(t.gender, '未知') as gender, 
            COALESCE(t.nationality, '未知') as nationality,
            t.room_number,
            t.status,
            t.has_pet,
            COALESCE(dt.room_code_desc, '未知房型') as room_type_desc,
            -- 1. 获取房间总租金 (增加 COALESCE 防止 NULL)
            COALESCE((
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
            ), 0) as raw_rent,
            -- 2. 计算房间同住人数 (分母)
            (
                SELECT count(*) 
                FROM tenant_analysis_report t2 
                WHERE t2.room_number = t.room_number 
                AND t2.status = t.status
            ) as room_pax
        FROM tenant_analysis_report t
        LEFT JOIN dim_room_type dt ON t.room_code = dt.room_code
        WHERE {base_where}
    ),
    enriched_data AS (
        SELECT 
            *,
            -- 计算个人分摊租金 (防止除以零)
            CASE 
                WHEN room_pax > 0 THEN (raw_rent / room_pax) 
                ELSE 0 
            END as allocated_rent,
            -- 宠物标识
            CASE 
                WHEN has_pet IS NOT NULL AND has_pet != '' THEN 1 
                ELSE 0 
            END as is_pet_owner,
            -- 年龄分箱
            CASE 
                WHEN age < 18 THEN '18岁以下'
                WHEN age BETWEEN 18 AND 25 THEN '18-25岁'
                WHEN age BETWEEN 26 AND 35 THEN '26-35岁'
                WHEN age BETWEEN 36 AND 45 THEN '36-45岁'
                WHEN age BETWEEN 46 AND 60 THEN '46-60岁'
                ELSE '60岁以上'
            END as age_group
        FROM base_data
        WHERE {outer_where}
    )
    """

    try:
        with get_db_cursor() as cur:
            # ----------------------------------
            # 1. 基础概况
            # ----------------------------------
            cur.execute(f"""
                {cte_sql} 
                SELECT count(*) as cnt, sum(allocated_rent) as total_rev 
                FROM enriched_data
            """, full_params)
            
            row = cur.fetchone()
            total_count = row['cnt']
            total_revenue = float(row['total_rev'] or 0)
            
            if total_count == 0:
                return {"count": 0, "analysis": None}

            result = {
                "count": total_count,
                "total_revenue_contribution": total_revenue,
                "analysis": {
                    "based_on": f"基于 {total_count} 位住客数据"
                }
            }

            # ----------------------------------
            # 2. 房型分布
            # ----------------------------------
            sql_room_type = f"""
                {cte_sql}
                SELECT room_type_desc, count(*) as cnt
                FROM enriched_data
                GROUP BY 1 ORDER BY cnt DESC
            """
            cur.execute(sql_room_type, full_params)
            result['analysis']['room_type_distribution'] = [
                {"room_type": r['room_type_desc'], "count": r['cnt'], "percentage": f"{(r['cnt']/total_count*100):.1f}%"}
                for r in cur.fetchall()
            ]

            # ----------------------------------
            # 3. 年龄 x 性别 交叉分布
            # ----------------------------------
            sql_age_gender = f"""
                {cte_sql}
                SELECT age_group, gender, count(*) as cnt
                FROM enriched_data
                GROUP BY 1, 2
                ORDER BY age_group, gender
            """
            cur.execute(sql_age_gender, full_params)
            
            age_gender_map = {}
            for r in cur.fetchall():
                grp = r['age_group']
                if grp not in age_gender_map:
                    age_gender_map[grp] = {'group': grp, 'total': 0, 'details': {}}
                
                age_gender_map[grp]['details'][r['gender']] = r['cnt']
                age_gender_map[grp]['total'] += r['cnt']
            
            age_dist_list = []
            sort_order = ['18岁以下', '18-25岁', '26-35岁', '36-45岁', '46-60岁', '60岁以上']
            for grp in sort_order:
                if grp in age_gender_map:
                    data = age_gender_map[grp]
                    pct = (data['total'] / total_count) * 100
                    age_dist_list.append({
                        "group": grp,
                        "count": data['total'],
                        "percentage": f"{pct:.1f}%",
                        "gender_breakdown": data['details']
                    })
            result['analysis']['age_gender_distribution'] = age_dist_list

            # ----------------------------------
            # 4. 租金贡献分析
            # ----------------------------------
            
            # A. 性别租金
            sql_rent_gender = f"""
                {cte_sql}
                SELECT gender, count(*) as cnt, sum(allocated_rent) as rent_sum
                FROM enriched_data
                GROUP BY 1 ORDER BY rent_sum DESC
            """
            cur.execute(sql_rent_gender, full_params)
            gender_rent_list = []
            for r in cur.fetchall():
                r_sum = float(r['rent_sum'] or 0)
                pct = (r_sum / total_revenue * 100) if total_revenue else 0
                gender_rent_list.append({
                    "gender": r['gender'],
                    "headcount": r['cnt'],
                    "total_rent_contribution": r_sum,
                    "contribution_share": f"{pct:.1f}%"
                })
            result['analysis']['gender_rent_contribution'] = gender_rent_list

            # B. 年龄租金
            sql_rent_age = f"""
                {cte_sql}
                SELECT age_group, sum(allocated_rent) as rent_sum, avg(allocated_rent) as avg_rent
                FROM enriched_data
                GROUP BY 1 ORDER BY rent_sum DESC
            """
            cur.execute(sql_rent_age, full_params)
            age_rent_list = []
            for r in cur.fetchall():
                r_sum = float(r['rent_sum'] or 0)
                avg = float(r['avg_rent'] or 0)
                pct = (r_sum / total_revenue * 100) if total_revenue else 0
                age_rent_list.append({
                    "age_group": r['age_group'],
                    "total_rent": r_sum,
                    "avg_person_rent": avg,
                    "contribution_share": f"{pct:.1f}%"
                })
            result['analysis']['age_rent_contribution'] = age_rent_list

            # ----------------------------------
            # 5. 宠物数据分析
            # ----------------------------------
            sql_pet = f"""
                {cte_sql}
                SELECT 
                    sum(is_pet_owner) as total_pet_owners,
                    sum(CASE WHEN is_pet_owner = 1 AND gender = '男' THEN 1 ELSE 0 END) as male_pet_owners,
                    sum(CASE WHEN is_pet_owner = 1 AND gender = '女' THEN 1 ELSE 0 END) as female_pet_owners
                FROM enriched_data
            """
            cur.execute(sql_pet, full_params)
            pet_row = cur.fetchone()
            
            pet_total = int(pet_row['total_pet_owners'] or 0)
            pet_male = int(pet_row['male_pet_owners'] or 0)
            pet_female = int(pet_row['female_pet_owners'] or 0)
            
            result['analysis']['pet_analysis'] = {
                "total_pet_owners": pet_total,
                "pet_ownership_rate": f"{(pet_total / total_count * 100):.1f}%" if total_count else "0.0%",
                "gender_breakdown": {
                    "男": {"count": pet_male, "ratio": f"{(pet_male / pet_total * 100):.1f}%" if pet_total else "0.0%"},
                    "女": {"count": pet_female, "ratio": f"{(pet_female / pet_total * 100):.1f}%" if pet_total else "0.0%"}
                }
            }

            # ----------------------------------
            # 6. 国籍 (Top 10)
            # ----------------------------------
            sql_nation = f"""
                {cte_sql} 
                SELECT 
                    nationality, 
                    count(*) as cnt,
                    SUM(CASE WHEN gender = '男' THEN 1 ELSE 0 END) as male_cnt,
                    SUM(CASE WHEN gender = '女' THEN 1 ELSE 0 END) as female_cnt
                FROM enriched_data 
                GROUP BY 1 
                ORDER BY cnt DESC
                LIMIT 10
            """
            cur.execute(sql_nation, full_params)
            
            nation_list = []
            for r in cur.fetchall():
                n_total = r['cnt']
                male = int(r['male_cnt'] or 0)
                female = int(r['female_cnt'] or 0)
                
                nation_list.append({
                    "nation": r['nationality'] or "未知",
                    "count": n_total,
                    "percentage": f"{(n_total / total_count * 100):.1f}%" if total_count else "0.0%",
                    "gender_breakdown": {
                        "男": {"count": male, "ratio": f"{(male / n_total * 100):.1f}%" if n_total else "0.0%"},
                        "女": {"count": female, "ratio": f"{(female / n_total * 100):.1f}%" if n_total else "0.0%"}
                    }
                })
            result['analysis']['nationality_distribution'] = nation_list

            # 7. 租金区间
            sql_rent_range = f"""
                {cte_sql}
                SELECT 
                    CASE 
                        WHEN raw_rent < 5000 THEN '5000以下'
                        WHEN raw_rent BETWEEN 5000 AND 8000 THEN '5000-8000'
                        WHEN raw_rent BETWEEN 8001 AND 12000 THEN '8000-12000'
                        WHEN raw_rent BETWEEN 12001 AND 15000 THEN '12000-15000'
                        WHEN raw_rent BETWEEN 15001 AND 20000 THEN '15000-20000'
                        ELSE '20000以上'
                    END as range_name,
                    count(*) as cnt
                FROM enriched_data
                GROUP BY 1 ORDER BY cnt DESC
            """
            cur.execute(sql_rent_range, full_params)
            result['analysis']['rent_range_distribution'] = [
                {"range": r['range_name'], "count": r['cnt'], "percentage": f"{(r['cnt']/total_count*100):.1f}%"}
                for r in cur.fetchall()
            ]

            return result

    except Exception as e:
        logger.error(f"统计查询出错: {e}", exc_info=True)
        return {"count": 0, "analysis": None, "error": str(e)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    import json
    
    # 测试 1: 在住用户统计
    print("\n--- 测试: 在住(I) 深度分析 ---")
    res = get_guest_statistics_logic(start_arr_date="2025-08-01", end_arr_date="2025-08-31")
    print(json.dumps(res, ensure_ascii=False, indent=2))

    # 测试 2: 在住 + 男性 (修正了之前把“男”传给nation的错误)
    print("\n--- 测试: 在住(I) 男性 深度分析 ---")
    res = get_guest_statistics_logic(status="I", gender="男") 
    print(json.dumps(res, ensure_ascii=False, indent=2))

    # 测试 3: 租金筛选 (验证参数化查询是否生效)
    print("\n--- 测试: 租金>10000 的住客 ---")
    res = get_guest_statistics_logic(status='I', min_rent=10000)
    print(json.dumps(res, ensure_ascii=False, indent=2))

    # 测试 3: 租金筛选 (验证参数化查询是否生效)
    print("\n--- 测试: 住在行政单间的住客 ---")
    res = get_guest_statistics_logic(status='I', room_type="\"行政单间\"")
    print(json.dumps(res, ensure_ascii=False, indent=2))

    def run_test(description: str, **kwargs):
        """
        辅助测试函数：打印测试描述，执行查询，并打印关键结果摘要
        """
        print(f"\n{'='*60}")
        print(f"测试场景: {description}")
        print(f"传入参数: {json.dumps(kwargs, ensure_ascii=False)}")
        print(f"{'-'*60}")
        
        try:
            res = get_guest_statistics_logic(**kwargs)
            
            # 打印摘要而不是全部JSON，防止控制台刷屏
            count = res.get("count", 0)
            print(f"✅ 查询成功 | 匹配人数: {count}")
            
            if count > 0 and res.get("analysis"):
                analysis = res["analysis"]
                # 打印几个关键指标验证数据准确性
                print(f"   - 总营收贡献: {res.get('total_revenue_contribution'):,.2f}")
                print(f"   - 宠物饲养率: {analysis.get('pet_analysis', {}).get('pet_ownership_rate')}")
                
                # 取出排名第一的房型（如果有）
                if analysis.get('room_type_distribution'):
                    top_room = analysis['room_type_distribution'][0]
                    print(f"   - Top1 房型: {top_room['room_type']} ({top_room['percentage']})")
                
                # 取出排名第一的国籍（如果有）
                if analysis.get('nationality_distribution'):
                    top_nation = analysis['nationality_distribution'][0]
                    print(f"   - Top1 国籍: {top_nation['nation']} ({top_nation['percentage']})")
            else:
                print("⚠️ 无匹配数据 (符合预期或需检查数据库)")
                
        except Exception as e:
            print(f"❌ 测试失败: {str(e)}")

    # ==========================================
    # 1. 基础单维度筛选
    # ==========================================
    # run_test("查询所有【在住】客人", status="I")
    # run_test("查询所有【男性】客人", gender="男")
    # run_test("精确查询【特定房号】 (假设存在 1001)", room_number="1001")
    # run_test("模糊查询【姓名】 (包含 '王')", name="王")

    # # ==========================================
    # # 2. 列表传参 (List Logic)
    # # ==========================================
    # run_test("多状态筛选：【在住】+【挂账】+【预定】", 
    #          status=["I", "S", "R"])
    
    # run_test("多房型筛选：【行政单间】+【豪华单间】", 
    #          room_type=["行政单间", "豪华单间"])

    # # ==========================================
    # # 3. 数值区间 (Range Filters)
    # # ==========================================
    # run_test("年龄段筛选：【25岁 - 35岁】的青年租客", 
    #          min_age=25, max_age=35)
    
    # run_test("高租金人群：月租金 > 15,000 的土豪", 
    #          min_rent=15000)
    
    # run_test("特定租金区间：8,000 - 12,000", 
    #          min_rent=8000, max_rent=12000)

    # # ==========================================
    # # 4. 日期筛选 (Date Filters)
    # # ==========================================
    # run_test("近期入住：2025年1月1日之后入住的新客", 
    #          start_arr_date="2025-01-01")
             
    # run_test("特定时间窗口入住：2024年全年的住客", 
    #          start_arr_date="2024-01-01", end_arr_date="2024-12-31")

    # # ==========================================
    # # 5. 高级组合场景 (Complex Persona)
    # # ==========================================
    # run_test("【高净值单身男性】：在住 + 男性 + 租金>12000 + 年龄<40", 
    #          status="I", 
    #          gender="男", 
    #          min_rent=12000, 
    #          max_age=40)

    # run_test("【家庭/多人房型分析】：筛选两房或三房 + 在住", 
    #          room_type=["两房豪华式公寓", "三房式公寓"], 
    #          status="I")

    # run_test("【特定国籍画像】：日本籍 (JP) + 在住 + 女性", 
    #          nation="JP", 
    #          status="I", 
    #          gender="女")

    # # ==========================================
    # # 6. 极端/冲突/空数据测试 (Edge Cases)
    # # ==========================================
    # run_test("【逻辑冲突】：年龄 < 5 岁 (通常无数据)", 
    #          max_age=5)
             
    # run_test("【不可能的租金】：租金 > 1,000,000", 
    #          min_rent=1000000)
             
    # run_test("【全组合压力测试】：所有参数都填 (除了冲突的)", 
    #          status="I",
    #          gender="男",
    #          min_age=20,
    #          max_age=50,
    #          min_rent=5000,
    #          start_arr_date="2023-01-01")