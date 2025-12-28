import sys
import os
import logging
from decimal import Decimal
from typing import Optional, List

try:
    from .db import get_db_cursor
    from .param_parser import normalize_list_param
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor
    from utils.param_parser import normalize_list_param

logger = logging.getLogger("ApartmentSearch")

def find_apartments_logic(
    room_number: Optional[str] = None,
    building_no: Optional[List[str]] = None,
    room_code_desc: Optional[List[str]] = None,
    orientation: Optional[List[str]] = None,
    floor_range: Optional[List[int]] = None,
    area_sqm_range: Optional[List[float]] = None,
    price_range: Optional[List[float]] = None,
    sort_by: str = 'monthly_rent', 
    sort_order: str = 'asc',
    aggregation: Optional[str] = None,
    limit: int = 10,
    return_fields: Optional[List[str]] = None
) -> dict:
    """
    房源搜索逻辑。固定使用 rent_12_months 作为价格参考。
    包含状态联查和多样性排序修复。
    """

    # 1. 参数清洗
    building_no = normalize_list_param(building_no)
    room_code_desc = normalize_list_param(room_code_desc)
    orientation = normalize_list_param(orientation)
    floor_range = normalize_list_param(floor_range)
    area_sqm_range = normalize_list_param(area_sqm_range)
    price_range = normalize_list_param(price_range)
    return_fields = normalize_list_param(return_fields)

    target_rent_col = 'rent_12_months'

    params = []
    conditions = ["1=1"]
    desc_parts = []

    if room_number:
        conditions.append("rd.room_number = %s")
        params.append(room_number.strip().upper())
        desc_parts.append(f"房号:{room_number}")

    if building_no:
        conditions.append("rd.building_no = ANY(%s)")
        params.append([b.strip().upper() for b in building_no])
        desc_parts.append(f"楼栋:{','.join(building_no)}")

    if room_code_desc:
        type_conds = []
        for t in room_code_desc:
            type_conds.append("rd.room_code_desc ILIKE %s")
            params.append(f"%{t.strip()}%")
        conditions.append(f"({' OR '.join(type_conds)})")
        desc_parts.append(f"{','.join(room_code_desc)}")

    if orientation:
        conditions.append("rd.orientation = ANY(%s)")
        params.append([o.strip() for o in orientation])
        desc_parts.append(f"朝向:{','.join(orientation)}")

    if floor_range and len(floor_range) == 2:
        conditions.append("rd.floor BETWEEN %s AND %s")
        params.extend([floor_range[0], floor_range[1]])
        desc_parts.append(f"楼层{floor_range[0]}-{floor_range[1]}")

    if area_sqm_range and len(area_sqm_range) == 2:
        conditions.append("rd.area_sqm BETWEEN %s AND %s")
        params.extend([area_sqm_range[0], area_sqm_range[1]])
        desc_parts.append(f"面积{area_sqm_range[0]}-{area_sqm_range[1]}")

    if price_range and len(price_range) == 2:
        conditions.append(f"rd.{target_rent_col} BETWEEN %s AND %s")
        params.extend([price_range[0], price_range[1]])
        desc_parts.append(f"月租金{price_range[0]}-{price_range[1]}")

    where_clause = " AND ".join(conditions)
    criteria_str = ", ".join(desc_parts) if desc_parts else "全量"

    # --- 聚合查询 (Count) ---
    if aggregation == 'count':
        try:
            with get_db_cursor() as cur:
                sql = f"""
                    SELECT rd.room_code_desc, COUNT(*) as cnt 
                    FROM room_details rd
                    WHERE {where_clause} 
                    GROUP BY rd.room_code_desc
                    ORDER BY cnt DESC
                """
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
                total_count = sum(r['cnt'] for r in rows)
                
                breakdown_str = ", ".join([f"{r['room_code_desc']}:{r['cnt']}" for r in rows])
                final_desc = f"{breakdown_str} (筛选: {criteria_str})" if criteria_str != "全量" else breakdown_str

                return {"count": total_count, "description": final_desc or "无匹配房源"}
        except Exception as e:
            return {"error": str(e)}

    # --- 列表查询 ---
    full_criteria_str = f"{criteria_str}"

    sort_map = {
        'price': f'rd.{target_rent_col}',
        'rent': f'rd.{target_rent_col}',
        'monthly_rent': target_rent_col,
        'area': 'rd.area_sqm',
        'floor': 'rd.floor'
    }
    # 内部排序字段 (带 rd. 前缀)
    order_col_inner = sort_map.get(sort_by, f'rd.{target_rent_col}')
    allowed_inner_cols = [f'rd.{target_rent_col}', 'rd.area_sqm', 'rd.floor', 'rd.room_number']
    if order_col_inner not in allowed_inner_cols:
        order_col_inner = f'rd.{target_rent_col}'

    order_dir = "ASC" if sort_order.lower() == 'asc' else "DESC"

    # [判断是否启用多样性排序]
    use_diversity_sort = False
    if room_code_desc and len(room_code_desc) > 1:
        use_diversity_sort = True
    
    # 字段选择
    if return_fields and len(return_fields) > 0:
        clean_fields = [f.replace('"', '').replace("'", "") for f in return_fields]
        field_mapping = {
            '房号': 'room_number', '楼栋': 'building_no', '楼层': 'floor',
            '房型': 'room_code_desc', '面积': 'area_sqm', '面积(平方米)': 'area_sqm',
            '朝向': 'orientation', '参考月租金': target_rent_col
        }
        final_fields = [f'rd."{field_mapping.get(f, f)}"' for f in clean_fields]
        if 'rd."room_number"' not in final_fields:
            final_fields.append('rd."room_number"')
        select_cols = ", ".join(final_fields)
    else:
        select_cols = f"rd.room_number, rd.building_no, rd.floor, rd.room_code_desc, rd.area_sqm, rd.orientation, rd.{target_rent_col} as monthly_rent"

    try:
        with get_db_cursor() as cur:
            # 查总数
            cur.execute(f"SELECT COUNT(*) as total FROM room_details rd WHERE {where_clause}", tuple(params))
            total_found = cur.fetchone()['total']

            status_join = """
                LEFT JOIN LATERAL (
                    SELECT 1 as is_occupied
                    FROM tenant_analysis_report t
                    WHERE t.room_number = rd.room_number
                    AND t.status = 'I'
                    LIMIT 1
                ) st ON true
            """

            if use_diversity_sort:
                # 准备外部排序字段名
                # 去除 'rd.' 前缀
                order_col_outer = order_col_inner.replace('rd.', '')
                
                # 如果是租金字段，且使用了 monthly_rent 别名，则外部必须用别名
                # 简单判断：如果 inner 是租金，且 select_cols 里有 monthly_rent
                if target_rent_col in order_col_inner and "as monthly_rent" in select_cols:
                    order_col_outer = "monthly_rent"

                sql = f"""
                    WITH Ranked AS (
                        SELECT 
                            {select_cols},
                            COALESCE(st.is_occupied, 0) as is_occupied,
                            ROW_NUMBER() OVER (
                                PARTITION BY rd.room_code_desc 
                                ORDER BY COALESCE(st.is_occupied, 0) ASC, {order_col_inner} {order_dir}
                            ) as rn
                        FROM room_details rd
                        {status_join}
                        WHERE {where_clause}
                    )
                    SELECT * FROM Ranked
                    ORDER BY rn ASC, is_occupied ASC, {order_col_outer} {order_dir}
                    LIMIT %s
                """
            else:
                sql = f"""
                    SELECT 
                        {select_cols},
                        COALESCE(st.is_occupied, 0) as is_occupied
                    FROM room_details rd
                    {status_join}
                    WHERE {where_clause}
                    ORDER BY is_occupied ASC, {order_col_inner} {order_dir}
                    LIMIT %s
                """
            
            cur.execute(sql, tuple(params + [limit]))
            raw_rows = cur.fetchall()

            # 定义字段映射表
            key_map = {
                'room_number': '房间号',
                'building_no': '楼栋',
                'floor': '楼层',
                'room_code_desc': '房型',
                'area_sqm': '面积',
                'orientation': '朝向',
                'monthly_rent': '月租金',
                'room_status': '房间状态'
            }

            clean_rows = []
            for row in raw_rows:
                new_row = {}
                for key, value in row.items():
                    if key in ['rn', 'is_occupied']: continue

                    # 1. 统一租金字段名 (数据库可能是 rent_12_months)
                    std_key = key
                    if key == target_rent_col:
                        std_key = 'monthly_rent'
                    # 2. 转换为中文 Key (如果不在映射表中，保留原英文名)
                    final_key = key_map.get(std_key, std_key)
                    
                    if isinstance(value, Decimal):
                        new_row[final_key] = float(value)
                    else:
                        new_row[final_key] = value
                
                is_occ = row.get('is_occupied', 0)
                new_row['room_status'] = '在住' if is_occ == 1 else '空置'
                
                clean_rows.append(new_row)

            return {
                "description": full_criteria_str,
                "查询结果总数": total_found,
                "返回总数": len(clean_rows),
                "apartments": clean_rows
            }
    except Exception as e:
        logger.error(f"DB Error: {e}")
        return {"error": f"数据库查询失败: {str(e)}"}



# ==========================================
# Main 调试
# ==========================================
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(">>> 调试 utils/apartment_search.py <<<")

    # ---------------------------------------------------------
    # 测试 1: 基础查询
    # ---------------------------------------------------------
    print("\n--- 测试 1: 基础查询 (A栋) ---")
    res1 = find_apartments_logic(room_code_desc=['行政单间'],orientation=['南', '东南', '西南'],sort_by='rent_12_months',sort_order='asc',limit=5)
    # print(json.dumps(res1, ensure_ascii=False, indent=2))
    print(res1)

    # ---------------------------------------------------------
    # 测试 2: 复杂组合
    # ---------------------------------------------------------
    print("\n--- 测试 2: 复杂组合 (视野好 + 1.5万左右 + 朝南) ---")
    complex_params = {
        "orientation": ["南", "东南", "西南"],
        "price_range": [14000.0, 16000.0],
        "floor_range": [15, 100], 
        "sort_by": "floor",
        "sort_order": "desc",
        "limit": 5
    }
    res2 = find_apartments_logic(**complex_params)
    # print(json.dumps(res2, ensure_ascii=False, indent=2))
    print(res2)

    # ---------------------------------------------------------
    # 测试 3: 计数统计 (带楼层限制)
    # ---------------------------------------------------------
    print("\n--- 测试 3: 计数统计 (10楼以上 + 行政单间) ---")
    # 注意：这里有楼层限制，所以结果是 211 而不是 360
    res3 = find_apartments_logic(
        floor_range=[10, 100], 
        room_code_desc=["行政单间"], 
        aggregation="count"
    )
    print(f"统计结果: {res3}")

    # ---------------------------------------------------------
    # 测试 4: 列表参数逻辑 (多房型)
    # ---------------------------------------------------------
    print("\n--- 测试 4: 查询所有房型总数 (不限楼层) ---")
    res_all_types = find_apartments_logic(
        room_code_desc=['行政单间', '行政豪华单间', '豪华单间', '一房豪华式公寓', '一房行政豪华式公寓', '两房豪华式公寓', '三房式公寓']
    )
    # 这里打印 res_all_types
    # print(json.dumps(res_all_types, ensure_ascii=False, indent=2))
    print(res_all_types)


    print("\n--- 测试 1: 基础查询 (A栋) ---")
    res4 = find_apartments_logic(orientation=['南'], floor_range=[6, 6])
    print(res4)

    print("\n--- 测试 1: 基础查询 (B栋) ---")
    res4 = find_apartments_logic(building_no="B", floor_range=[8, 8], return_fields=['房号', '朝向'])
    print(res4)