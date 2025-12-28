import sys
import os
import re
import logging
import datetime
from collections import defaultdict
from typing import Union, List

try:
    from .db import get_db_cursor
except ImportError:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.db import get_db_cursor

logger = logging.getLogger("UnifiedQuery")

def search_occupancy_logic(query_input: Union[str, List[str]]) -> str:
    """
    通用查询逻辑：
    核心策略：以合同(Contract)为时间轴骨架，将住客(Resident)匹配填入合同中。
    解决续租问题（同一人多份合同）和家庭入住问题（一份合同多人）。
    """
    # 1. 参数清洗
    targets = []
    if isinstance(query_input, list):
        targets = [str(item).strip() for item in query_input if str(item).strip()]
    elif isinstance(query_input, str):
        targets = [item.strip() for item in re.split(r'[\s,]+', query_input) if item.strip()]

    if not targets:
        return "输入错误：请输入有效的 房号 或 客户ID。"

    logger.info(f"执行通用查询 (合同优先): {targets}")

    try:
        with get_db_cursor() as cur:
            # =======================================================
            # Step 1: 定位涉及的房间
            # =======================================================
            sql_locate = """
                SELECT DISTINCT room_number
                FROM resident_id_document_list
                WHERE room_number = ANY(%s) OR account_no::text = ANY(%s)
            """
            cur.execute(sql_locate, (targets, targets))
            room_rows = cur.fetchall()
            
            if not room_rows:
                return f"未找到与 '{', '.join(targets)}' 相关的记录。"
            
            target_room_numbers = [r['room_number'] for r in room_rows]

            # =======================================================
            # Step 2: 获取全量数据 (Contract, Resident, Tenant, RoomType, Status)
            # =======================================================
            
            # A. 核心骨架：合同表 (决定了有多少条历史记录)
            sql_contracts = """
                SELECT 
                    contract_no, room_number, resident_name, 
                    check_in_date, check_out_date, actual_monthly_rent,
                    room_code
                FROM contract_creation_log
                WHERE room_number = ANY(%s)
                ORDER BY check_in_date DESC
            """
            cur.execute(sql_contracts, (target_room_numbers,))
            contracts = cur.fetchall()

            # B. 住客数据 (用于填充 ID 和 状态)
            sql_residents = """
                SELECT 
                    r.room_number, r.account_no, r.resident_name, r.status,
                    COALESCE(ds.status_desc, r.status) as status_desc
                FROM resident_id_document_list r
                LEFT JOIN dim_status_map ds ON r.status = ds.status
                WHERE r.room_number = ANY(%s)
            """
            cur.execute(sql_residents, (target_room_numbers,))
            residents = cur.fetchall()

            # C. 画像数据 (用于填充性别、年龄、备注)
            account_nos = [str(r['account_no']) for r in residents]
            sql_tenant = """
                SELECT account_no, arrival_date, departure_date, remark, gender, age, nationality
                FROM tenant_analysis_report
                WHERE account_no::text = ANY(%s)
            """
            cur.execute(sql_tenant, (account_nos,))
            # 转为字典映射: account_no -> info
            tenant_map = {str(t['account_no']): t for t in cur.fetchall()}

            # D. 房型翻译
            cur.execute("SELECT room_code, room_code_desc FROM dim_room_type")
            room_type_map = {r['room_code']: r['room_code_desc'] for r in cur.fetchall()}

            # =======================================================
            # Step 3: 内存匹配逻辑 (Contract-First)
            # =======================================================
            timeline = _build_timeline(contracts, residents, tenant_map, room_type_map)
            
            return _format_timeline_report(timeline, targets)

    except Exception as e:
        logger.error(f"通用查询失败: {e}")
        return f"数据库查询出错: {str(e)}"

def _build_timeline(contracts, residents, tenant_map, room_type_map):
    """
    构建时间轴。
    逻辑：
    1. 遍历每一份合同，创建一个 TimeBlock。
    2. 遍历该房间的所有住客，如果住客属于这份合同（名字匹配 或 时间重叠），加入该 Block。
    3. 处理无合同的“孤儿”住客（极少数情况）。
    """
    timeline = []
    
    # 将住客按房间分组，方便查找
    residents_by_room = defaultdict(list)
    for r in residents:
        residents_by_room[r['room_number']].append(r)

    # 标记已分配的住客，防止重复显示（可选，视需求而定，这里暂不强行剔除，允许一个人出现在多个合同里）
    # processed_residents = set()

    # --- 遍历合同 (主时间轴) ---
    for c in contracts:
        room_no = c['room_number']
        c_name = c['resident_name']
        c_start = c['check_in_date']
        c_end = c['check_out_date']
        
        block = {
            'type': 'contract',
            'room_number': room_no,
            'room_type': room_type_map.get(c['room_code'], c['room_code']),
            'rent': c['actual_monthly_rent'],
            'arr': c_start,
            'dep': c_end,
            'status_str': "历史合同", # 默认值，后面根据住客状态更新
            'residents': [],
            'remarks': set()
        }

        # 在该房间的住客中寻找匹配者
        room_residents = residents_by_room.get(room_no, [])
        
        # 临时列表：签约人 和 同住人
        signers = []
        family = []
        
        # 确定该合同块的最终状态 (取住客中最新的状态，如 I 或 O)
        current_status_priority = 0 # I > O
        
        for res in room_residents:
            r_name = res['resident_name']
            r_acc = str(res['account_no'])
            t_info = tenant_map.get(r_acc, {})
            
            # --- 匹配逻辑 ---
            is_match = False
            
            # 1. 名字完全匹配 (签约人)
            if r_name == c_name:
                is_match = True
                
            # 2. 时间重叠匹配 (同住人)
            # 如果 tenant 表有时间，且时间与合同时间高度重叠
            if not is_match and t_info.get('arrival_date'):
                t_arr = t_info['arrival_date']
                # 宽松匹配：入住时间在合同期间内，或误差7天内
                if c_start and abs((t_arr - c_start).days) <= 7:
                    is_match = True
            
            # 3. 兜底匹配 (如果住客是 'I' 在住，且合同覆盖今天)
            if not is_match and res['status'] == 'I':
                today = datetime.date.today()
                if c_start <= today <= c_end:
                    is_match = True

            if is_match:
                # 组装展示信息
                res_str = f"{r_name}({r_acc})"
                profile = []
                if t_info.get('gender'): profile.append(t_info['gender'])
                if t_info.get('age'): profile.append(f"{t_info['age']}岁")
                if t_info.get('nationality'): profile.append(t_info['nationality'])
                if profile:
                    res_str += f" [{', '.join(profile)}]"
                
                # 收集备注
                if t_info.get('remark'):
                    block['remarks'].add(t_info['remark'].strip())
                
                # 更新 Block 状态 (取优先级最高的状态)
                # I(在住) > O(离店)
                s_code = res['status']
                s_desc = res.get('status_desc') or s_code
                
                if s_code == 'I':
                    block['status_str'] = f"{s_desc} ({s_code})"
                    current_status_priority = 10
                elif s_code == 'O' and current_status_priority < 10:
                    block['status_str'] = f"{s_desc} ({s_code})"
                
                # 分类
                if r_name == c_name:
                    signers.append(res_str)
                else:
                    family.append(res_str)

        # 合并名单：签约人放在最前
        # 去重：防止同名同ID被加两次
        final_list = []
        seen = set()
        for p in signers + family:
            if p not in seen:
                final_list.append(p)
                seen.add(p)
                
        # 如果没匹配到任何人 (可能是纯历史合同，住客表已被清洗)，显示合同上的名字
        if not final_list:
            final_list.append(f"{c_name} (仅合同记录)")
            block['status_str'] = "已归档"

        block['residents'] = final_list
        timeline.append(block)

    # --- 寻找孤儿住客 (有 Resident 记录但没匹配到任何 Contract) ---
    # 暂略，假设系统数据完整性较高。如果需要，可再次遍历 residents 检查是否被 match 过。
    
    return timeline

def _format_timeline_report(timeline, targets):
    lines = []
    lines.append(f"--- 综合查询结果 (查询项: {', '.join(targets)}) ---")
    lines.append(f"共找到 {len(timeline)} 条记录 (含续租)。")
    lines.append("-" * 80)
    
    for item in timeline:
        rent_str = f"￥{float(item['rent']):,.0f}" if item['rent'] else "N/A"
        
        # 1. 标题
        lines.append(f"房号: {item['room_number']} | {item['status_str']} | 租金: {rent_str}/月")
        lines.append(f"房型: {item['room_type']}")
        
        # 2. 时间
        arr = str(item['arr']) if item['arr'] else "未知"
        dep = str(item['dep']) if item['dep'] else "未知"
        lines.append(f"租期: {arr} 至 {dep}")
        
        # 3. 住客
        res_list = item['residents']
        label = "家庭入住" if len(res_list) > 1 else "住客"
        lines.append(f"{label}: {', '.join(res_list)}")
        
        # 4. 备注
        if item['remarks']:
            rem_line = " | ".join(item['remarks']).replace('\n', ' ')
            lines.append(f"备注: {rem_line}")
            
        lines.append("-" * 80)

    return "\n".join(lines)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(">>> 调试 utils/unified_query.py <<<")
    
    # 测试1: A1001 (蒋续租应该出2条，李王同住应该出1条)
    print("\n[测试1: A1001]")
    print(search_occupancy_logic("A212,A215,A1606"))
    
    # 测试2: ID 3808
    print("\n[测试2: 3808]")
    print(search_occupancy_logic("3808,3556"))