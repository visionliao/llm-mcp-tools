import pandas as pd
from datetime import datetime
from services.data_loader import get_master_base_df

def calculate_occupancy_rate(start_date_str: str, end_date_str: str, total_rooms: int,
                             show_details: bool = False):
    """
    计算指定时间范围内的酒店入住率和出租率，并可选择返回每日详情字符串。
    """
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        return None, "错误: 日期格式不正确，请使用 'YYYY-MM-DD' 格式。"

    if start_date > end_date:
        return None, "错误: 开始日期不能晚于结束日期。"

    df = get_master_base_df()
    if df is None or df.empty:
        return None, "错误: 无法从XML文件中解析出数据。"

    required_cols = ['sta', 'rmno', 'arr', 'dep']
    if not all(col in df.columns for col in required_cols):
        return None, f"错误: 文件中缺少必要的列。需要: {required_cols}"

    # M# <--- 修改: 筛选状态为 'I' (在住) 或 'R' (预定) 的记录
    df_filtered = df[df['sta'].isin(['I', 'R'])].copy()
    df_filtered.dropna(subset=['arr', 'dep', 'rmno'], inplace=True)
    df_filtered = df_filtered[df_filtered['rmno'] != '']

    df_filtered['arr'] = pd.to_numeric(df_filtered['arr'], errors='coerce')
    df_filtered['dep'] = pd.to_numeric(df_filtered['dep'], errors='coerce')
    df_filtered.dropna(subset=['arr', 'dep'], inplace=True)

    df_filtered['arr_date'] = pd.to_datetime(df_filtered['arr'], unit='D', origin='1899-12-30').dt.date
    df_filtered['dep_date'] = pd.to_datetime(df_filtered['dep'], unit='D', origin='1899-12-30').dt.date

    # --- 详细计算过程 ---
    details_log = ""
    if show_details:
        details_log += "\n--- 每日入住与预定详情 ---\n"  # M# <--- 修改: 更新标题

    total_occupied_room_nights = 0
    total_reserved_room_nights = 0  # M# <--- 新增: 用于累计预定房晚数
    date_range = pd.date_range(start=start_date, end=end_date, freq='D').date

    for day in date_range:
        # 筛选出当天所有相关记录 (包括在住和预定)
        daily_records_df = df_filtered[
            (df_filtered['arr_date'] <= day) & (df_filtered['dep_date'] > day)
            ]

        # M# <--- 修改: 分别计算在住和预定的房间数
        inhouse_rooms_on_day = daily_records_df[daily_records_df['sta'] == 'I']['rmno'].unique()
        reserved_rooms_on_day = daily_records_df[daily_records_df['sta'] == 'R']['rmno'].unique()

        inhouse_rooms_count = len(inhouse_rooms_on_day)
        reserved_rooms_count = len(reserved_rooms_on_day)

        total_occupied_room_nights += inhouse_rooms_count
        total_reserved_room_nights += reserved_rooms_count

        if show_details:
            # M# <--- 修改: 每日详情现在同时显示在住和预定数量
            details_log += f"日期: {day} | 在住房间数: {inhouse_rooms_count:<3} | 预定房间数: {reserved_rooms_count:<3} | 出租情况 Roomnights occ: {(inhouse_rooms_count / total_rooms) * 100 if total_rooms > 0 else 0:.2f}% Application occ: {((inhouse_rooms_count + reserved_rooms_count) / total_rooms) * 100 if total_rooms > 0 else 0:.2f}%\n"

    num_days = (end_date - start_date).days + 1
    total_available_room_nights = total_rooms * num_days

    # 入住率 (仅基于在住)
    occupancy_rate = (
                             total_occupied_room_nights / total_available_room_nights) * 100 if total_available_room_nights > 0 else 0

    # 计算出租率 (在住 + 预定)
    rental_rate = ((
                               total_occupied_room_nights + total_reserved_room_nights) / total_available_room_nights) * 100 if total_available_room_nights > 0 else 0

    result_data = {
        "start_date": start_date_str,
        "end_date": end_date_str,
        "days_in_range": num_days,
        "total_available_room_nights": total_available_room_nights,
        "total_occupied_room_nights": total_occupied_room_nights,
        "total_reserved_room_nights": total_reserved_room_nights,  # M# <--- 新增
        "occupancy_rate_percentage": occupancy_rate,
        "rental_rate_percentage": rental_rate  # M# <--- 新增
    }

    return result_data, details_log


def format_result_to_string(result_data: dict, details_log: str = "") -> str:
    """
    将计算结果和详细日志格式化为单个字符串。
    """
    if not result_data:
        return ""

    report_string = details_log

    report_string += "\n--- 计算结果 ---\n"
    report_string += f"查询范围: {result_data['start_date']} 到 {result_data['end_date']} ({result_data['days_in_range']} 天)\n"
    report_string += f"总可用房晚数: {result_data['total_available_room_nights']:,}\n"
    report_string += f"实际入住房晚数: {result_data['total_occupied_room_nights']:,}\n"
    report_string += f"预定房晚数: {result_data['total_reserved_room_nights']:,}\n"  # M# <--- 新增
    report_string += "------------------\n"  # M# <--- 新增: 分隔线
    report_string += "--- 出租情况 ---\n"
    report_string += f"Roomnights occ (不包含签约但未入住): {result_data['occupancy_rate_percentage']:.2f}%\n"  # M# <--- 修改: 澄清这是仅在住的入住率
    report_string += f"Application occ (包含签约但为入住): {result_data['rental_rate_percentage']:.2f}%\n"  # M# <--- 新增
    report_string += "------------------\n"

    return report_string


# --- 主程序入口（用于快速调试） ---
if __name__ == "__main__":
    TOTAL_ROOMS = 579

    print("--- 酒店入住率与出租率计算器 ---")  # M# <--- 修改: 更新标题

    '''start_input = input("请输入开始日期 (YYYY-MM-DD): ")
    end_input = input("请输入结束日期 (YYYY-MM-DD): ")
    details_input = input("是否包含每日详细计算过程? (y/n，默认为 n): ").lower()'''

    start_input = "2025-08-01"
    end_input = "2025-08-05"
    details_input = "y"

    show_details_flag = True if details_input == 'y' else False

    result_dict, details_string = calculate_occupancy_rate(
        start_input, end_input, TOTAL_ROOMS, show_details=show_details_flag
    )

    if result_dict is None:
        print(details_string)
    else:
        final_report_string = format_result_to_string(result_dict, details_string)
        print(final_report_string)

        '''try:
            with open("occupancy_report.txt", "w", encoding="utf-8") as f:
                f.write(final_report_string)
            print("报告已成功保存到文件: occupancy_report.txt")
        except Exception as e:
            print(f"写入报告文件时出错: {e}")'''