import os
import requests
import logging
import re
import time
from typing import Optional, Tuple, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("GeoNavigation")

# ==========================================
# 通用重试请求函数
# ==========================================
def _request_api_with_retry(url: str, params: dict, timeout: int = 5, max_retries: int = 2) -> dict:
    """
    带重试机制的 API 请求函数。
    如果遇到网络错误或 API 返回状态非成功，则等待 1s 后重试。
    """
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            data = resp.json()
            
            # 判断成功标准: 
            # v3接口用 status=="1"
            # v4接口(骑行)用 errcode==0
            is_v3_success = data.get("status") == "1"
            is_v4_success = "errcode" in data and data.get("errcode") == 0
            
            if is_v3_success or is_v4_success:
                return data
            
            # 如果是鉴权失败(Key错误)，重试也没用，直接返回
            info = data.get("info", "")
            if "INVALID_USER_KEY" in info or "USERKEY_PLAT_NOMATCH" in info:
                return data

            # 其他情况(如QPS超限)，记录警告并准备重试
            if attempt < max_retries:
                logger.warning(f"API请求失败 (尝试 {attempt+1}/{max_retries+1}): {info}。等待1s重试...")
        
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"网络请求异常 (尝试 {attempt+1}/{max_retries+1}): {e}。等待1s重试...")
        
        # 延时重试
        if attempt < max_retries:
            time.sleep(1)
            
    # 如果重试耗尽仍失败，返回最后一次的结果或空字典
    return locals().get("data", {})


def plan_route_logic(origin: str, destination: str, mode: str = "transit") -> str:
    """
    路径规划核心逻辑函数 (含重试机制)。
    """
    api_key = os.getenv("GAODE_API_KEY")
    if not api_key:
        return "❌ 高德地图服务未配置（缺少 GAODE_API_KEY 环境变量）。"

    # --- 内部辅助：地理编码 ---
    def _geocode(addr: str) -> Tuple[Optional[str], Optional[str]]:
        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {"address": addr, "key": api_key, "output": "json"}
        
        data = _request_api_with_retry(url, params)
        
        if data.get("status") == "1" and data.get("geocodes"):
            item = data["geocodes"][0]
            city = item.get("city")
            if not city or isinstance(city, list):
                city = item.get("adcode")
            return item["location"], city
        return None, None

    # 1. 获取起终点
    origin_loc, origin_city = _geocode(origin)
    dest_loc, _ = _geocode(destination)

    if not origin_loc:
        return f"❌ 无法解析起点地址: {origin}，请尝试补充城市名。"
    if not dest_loc:
        return f"❌ 无法解析终点地址: {destination}，请尝试补充城市名。"

    # 2. 模式分发
    try:
        mode_clean = mode.lower()
        if mode_clean in ['walking', '步行', 'walk']:
            return _plan_walking_detailed(origin, destination, origin_loc, dest_loc, api_key, force=True)
        
        elif mode_clean in ['driving', '驾车', 'car', '打车']:
            return _plan_driving(origin, destination, origin_loc, dest_loc, api_key)
            
        elif mode_clean in ['bicycling', '骑行', 'bike', '自行车']:
            return _plan_bicycling(origin, destination, origin_loc, dest_loc, api_key)
            
        else:
            # 默认为 transit (混合双轨)
            return _plan_smart_transit(origin, destination, origin_loc, dest_loc, origin_city, api_key)

    except Exception as e:
        logger.error(f"路线规划异常: {e}", exc_info=True)
        return f"❌ 内部错误: {str(e)}"

# --- 通用辅助：无省略的步骤格式化 ---
def _format_steps(steps_data, indent=""):
    lines = []
    for i, step in enumerate(steps_data, 1):
        instruction = step.get("instruction", "")
        road = step.get("road", "")
        instruction = re.sub(r'<[^>]+>', '', instruction)
        if road and road not in instruction:
            instruction += f" (沿{road})"
        lines.append(f"{indent}{i}. {instruction}")
    return lines

# --- [修复] 辅助：格式化纯步行结果 ---
def _format_pure_walking(origin_name, dest_name, path_data):
    """格式化纯步行结果"""
    distance = int(path_data["distance"])
    duration = int(path_data["duration"]) // 60
    
    # [修复点] 之前这里多了一行错误的生成器代码，已删除，直接传列表
    steps_lines = _format_steps(path_data.get("steps", []))
    
    steps_str = "\n".join(steps_lines)

    return (
        f"🚶 **步行导航**\n"
        f"📍 {origin_name} -> {dest_name}\n"
        f"📏 {distance}米  ⏱️ {duration}分钟\n"
        f"--------------------------------\n"
        f"{steps_str}\n"
        f"--------------------------------"
    )

# --- 辅助：独立请求步行API获取详情 ---
def _get_detailed_walk_steps(origin_loc, dest_loc, api_key):
    url = "https://restapi.amap.com/v3/direction/walking"
    params = {"origin": origin_loc, "destination": dest_loc, "key": api_key}
    
    data = _request_api_with_retry(url, params, timeout=3)
    
    if data.get("status") == "1" and data.get("route", {}).get("paths"):
        path = data["route"]["paths"][0]
        dist = int(path["distance"])
        steps = path.get("steps", [])
        return dist, steps
    return 0, []

# ==========================================
# 模式 1: 纯步行
# ==========================================
def _plan_walking_detailed(origin_name, dest_name, origin_loc, dest_loc, api_key, force=False):
    url = "https://restapi.amap.com/v3/direction/walking"
    params = {"origin": origin_loc, "destination": dest_loc, "key": api_key}
    
    data = _request_api_with_retry(url, params)

    if data.get("status") != "1" or not data.get("route", {}).get("paths"):
        if force: return f"⚠️ 步行规划失败: 路途过远或无路可走。"
        return None

    path = data["route"]["paths"][0]
    distance = int(path["distance"])
    
    if not force and distance > 1500:
        return None

    return _format_pure_walking(origin_name, dest_name, path)

# ==========================================
# 模式 2: 驾车
# ==========================================
def _plan_driving(origin_name, dest_name, origin_loc, dest_loc, api_key):
    url = "https://restapi.amap.com/v3/direction/driving"
    params = {"origin": origin_loc, "destination": dest_loc, "key": api_key, "strategy": 0}
    
    data = _request_api_with_retry(url, params)

    if data.get("status") != "1" or not data.get("route", {}).get("paths"):
        return f"⚠️ 驾车规划失败: {data.get('info', '未知错误')}"

    path = data["route"]["paths"][0]
    distance = int(path["distance"]) / 1000
    duration = int(path["duration"]) // 60
    taxi_cost = data.get("route", {}).get("taxi_cost", "未知")
    traffic_lights = path.get("traffic_lights", "0")

    steps_lines = _format_steps(path.get("steps", []))
    steps_str = "\n".join(steps_lines)

    return (
        f"🚗 **驾车导航**\n"
        f"📍 {origin_name} -> {dest_name}\n"
        f"📏 {distance:.1f}km  ⏱️ {duration}分钟  🚦 红绿灯{traffic_lights}个\n"
        f"🚕 打车约: ¥{taxi_cost}\n"
        f"--------------------------------\n"
        f"{steps_str}\n"
        f"--------------------------------"
    )

# ==========================================
# 模式 3: 骑行
# ==========================================
def _plan_bicycling(origin_name, dest_name, origin_loc, dest_loc, api_key):
    url = "https://restapi.amap.com/v4/direction/bicycling"
    params = {"origin": origin_loc, "destination": dest_loc, "key": api_key}
    
    data = _request_api_with_retry(url, params)

    if data.get("errcode") != 0 or not data.get("data", {}).get("paths"):
        return f"⚠️ 骑行规划失败: {data.get('errmsg', '距离太远或无法骑行')}"

    path = data["data"]["paths"][0]
    distance = int(path["distance"])
    duration = int(path["duration"]) // 60
    
    steps_lines = _format_steps(path.get("steps", []))
    steps_str = "\n".join(steps_lines)
    dist_display = f"{distance}米" if distance < 1000 else f"{distance/1000:.1f}km"

    return (
        f"🚲 **骑行导航**\n"
        f"📍 {origin_name} -> {dest_name}\n"
        f"📏 {dist_display}  ⏱️ {duration}分钟\n"
        f"--------------------------------\n"
        f"{steps_str}\n"
        f"--------------------------------"
    )

# ==========================================
# 模式 4: 公共交通 (智能混合模式)
# ==========================================
def _plan_smart_transit(origin_name, dest_name, origin_loc, dest_loc, city_code, api_key):
    # 1. 尝试获取步行距离
    walk_url = "https://restapi.amap.com/v3/direction/walking"
    w_params = {"origin": origin_loc, "destination": dest_loc, "key": api_key}
    w_data = _request_api_with_retry(walk_url, w_params)
    
    real_walk_distance = 999999
    walk_path_data = None

    if w_data.get("status") == "1" and w_data.get("route", {}).get("paths"):
        walk_path_data = w_data["route"]["paths"][0]
        real_walk_distance = int(walk_path_data["distance"])

    # 2. 阈值判断
    if real_walk_distance <= 1500:
        return _format_pure_walking(origin_name, dest_name, walk_path_data)
    
    # 3. 走公交
    return _plan_transit_enhanced(origin_name, dest_name, origin_loc, dest_loc, city_code, api_key, real_walk_distance)

def _plan_transit_enhanced(origin_name, dest_name, origin_loc, dest_loc, city_code, api_key, straight_dist):
    url = "https://restapi.amap.com/v3/direction/transit/integrated"
    params = {
        "origin": origin_loc, "destination": dest_loc, "city": city_code,
        "key": api_key, "output": "json", "strategy": "0" 
    }
    
    data = _request_api_with_retry(url, params, timeout=6)

    if data.get("status") != "1":
        return f"⚠️ 公交规划失败: {data.get('info')}。建议打车 (步行约{straight_dist}米)。"

    transits = data.get("route", {}).get("transits", [])
    if not transits:
        return f"📍 未找到公交方案。建议打车 (步行约{straight_dist}米)。"

    best = transits[0]
    cost = float(best.get("cost", "0") or 0)
    duration = int(best.get("duration", 0)) // 60
    total_dist = int(best.get("distance", 0)) / 1000

    segments = best.get("segments", [])
    route_details = []
    step_idx = 1
    
    for seg in segments:
        # 1. 步行接驳段 (精细化)
        walking = seg.get("walking")
        if walking and int(walking.get("distance", 0)) > 0:
            w_origin = walking.get("origin")
            w_dest = walking.get("destination")
            w_dist_show = int(walking.get("distance"))
            
            real_steps = []
            if w_origin and w_dest:
                _d, _s = _get_detailed_walk_steps(w_origin, w_dest, api_key)
                if _s: 
                    real_steps = _s
                    w_dist_show = _d
                else:
                    real_steps = walking.get("steps", [])
            else:
                real_steps = walking.get("steps", [])

            if real_steps:
                route_details.append(f"{step_idx}. 步行 {w_dist_show}米:")
                formatted_steps = _format_steps(real_steps, indent="   - ")
                route_details.extend(formatted_steps)
                step_idx += 1
        
        # 2. 乘车段
        bus = seg.get("bus")
        if bus and bus.get("buslines"):
            line = bus["buslines"][0]
            name = line.get("name", "").split("(")[0]
            departure = line.get("departure_stop", {}).get("name", "起点站")
            arrival = line.get("arrival_stop", {}).get("name", "终点站")
            via_num = int(line.get("via_num", 0))
            ride_count = via_num + 1 
            icon = "🚇" if "地铁" in line.get("type", "") else "🚌"
            
            route_details.append(f"{step_idx}. 在 [{departure}] 乘坐 {icon} **{name}**")
            route_details.append(f"   ↓ (坐 {ride_count} 站)")
            route_details.append(f"   在 [{arrival}] 下车")
            step_idx += 1

    route_str = "\n".join(route_details)
    return (
        f"🚍 **公共交通方案**\n"
        f"📍 {origin_name} -> {dest_name}\n"
        f"📏 {total_dist:.1f}km  ⏱️ {duration}分钟  💰 ¥{cost}\n"
        f"================================\n"
        f"{route_str}\n"
        f"================================"
    )

# ==========================================
# Main 测试入口
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(">>> 调试 utils/geo_navigation.py <<<")

    # 测试 1: 短距离 (步行)
    print("\n--- 测试 1: 短距离 (步行) ---")
    origin_1 = "上海市静安区虬江路931号" # 假设这是公寓位置
    dest_1 = "上海市静安区西藏北路地铁站"
    print(plan_route_logic(origin_1, dest_1))

    # 测试 2: 长距离 (公交/地铁)
    print("\n--- 测试 2: 长距离 (地铁) ---")
    dest_2 = "上海市人民广场"
    print(plan_route_logic(origin_1, dest_2, mode="transit"))

    print("\n--- 测试 3: 驾车 ---")
    dest_3 = "上海市浦江镇城市生活广场"
    print(plan_route_logic(origin_1, dest_3, mode="driving"))

    print("\n--- 测试 4: 骑行 ---")
    dest_4 = "上海市滴水湖"
    print(plan_route_logic(origin_1, dest_4, mode="bicycling"))

    print("\n--- 测试 5: 强制步行 (即使很远) ---")
    dest_5 = "上海市宝山路派出所"
    print(plan_route_logic(origin_1, dest_5, mode="walking"))

    # 测试 3: 跨城或超远距离 (测试稳定性)
    print("\n--- 测试 6: 较远距离 (苏州) ---")
    dest_6 = "苏州中心"
    print(plan_route_logic(origin_1, dest_6, mode="driving"))

    print("\n--- 测试 7: 地铁 ---")
    dest_7 = "上海迪士尼乐园"
    print(plan_route_logic(origin_1, dest_7, mode="transit"))
    
    # 测试 4: 错误地址
    print("\n--- 测试 8: 错误地址 ---")
    print(plan_route_logic("火星的一个坑", "月球的一个海"))