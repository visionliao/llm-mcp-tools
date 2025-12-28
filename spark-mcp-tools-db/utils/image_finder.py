import logging
from typing import Optional, Union, List, Set

try:
    from .param_parser import normalize_list_param
except ImportError:
    import sys, os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.param_parser import normalize_list_param

# 配置日志
logger = logging.getLogger("ImageFinder")

# ==========================================
# 1. 图片数据库定义 (Mapping)
# ==========================================
# 核心数据：Key -> 图片列表
IMAGE_DATABASE = {
    # --- 公寓大厅/大堂 (1楼) ---
    "lobby": ["lobby.jpg", "lobby2.jpg"],

    # --- 公区 (7楼) ---
    "bar": ["Bar.jpg"],
    "gym": ["gym.jpg"],
    "ktv": ["KTV.jpg"],
    "music": ["Music_room.jpg"],
    "patio": ["Patio.jpg"],
    "pool": ["POOL01.jpg"],
    "kitchen": ["Privatekitchen.jpg"],
    "booth": ["Telephone_booth.jpg"],
    "yoga": ["Yoga_room.jpg"],

    # --- 房型 ---
    "STD": ["N29_01.jpg", "N29_02.jpg"], # 豪华单间
    "STE": ["S35_01.jpg", "S35_02.jpg", "S35_03.jpg", "S35_04.jpg"], # 行政单间
    "1BD": ["N46_01.jpg", "N46_02.jpg", "N46_03.jpg", "N46_04.jpg"], # 一房豪华
    "1BP": ["N59_01.jpg", "N59_02.jpg", "N59_03.jpg", "N59_04.jpg"], # 一房行政
    "STP": ["S50_01.jpg", "S50_02.jpg", "S50_03.jpg"], # 行政豪华单间
    "2BD": ["S74_01.jpg", "S74_02.jpg", "S74_03.jpg", "S74_04.jpg", "S74_05.jpg"], # 两房 (共用 S74)
    "3BR": ["S74_01.jpg", "S74_02.jpg", "S74_03.jpg", "S74_04.jpg", "S74_05.jpg"], # 三房 (共用 S74)
}

# 定义哪些 Key 属于“所有7楼公区”
PUBLIC_AREAS_7F = [
    "bar", "gym", "ktv", "music", 
    "patio", "pool", "kitchen", "booth", "yoga"
]

def get_image_list_logic(
    targets: Optional[Union[str, List[str]]] = None,
    all_public_areas: Optional[str] = None
) -> List[str]:
    """
    根据参数返回图片文件名列表。
    """
    # 使用 Set 进行自动去重
    collected_images: Set[str] = set()
    
    # 1. 处理 targets 参数 (结构清洗)
    # normalize_list_param 仅负责将 '["gym"]' 转为 ['gym']，不负责中文映射
    targets = normalize_list_param(targets) 
    
    # 2. 处理 all_public_areas (7楼公区)
    # 如果标记为真，将所有7楼设施图片加入集合
    if all_public_areas and str(all_public_areas).lower() in ['true', 'yes', '1']:
        for key in PUBLIC_AREAS_7F:
            if key in IMAGE_DATABASE:
                collected_images.update(IMAGE_DATABASE[key])

    # 3. 处理 targets 列表
    if targets:
        # 确保是列表 (normalize_list_param 可能会返回 str 如果不是json格式)
        if isinstance(targets, str):
            targets = [targets]
            
        for t in targets:
            key = str(t).strip()
            # 精确匹配 Key，不搞任何模糊搜索或中文映射
            if key in IMAGE_DATABASE:
                collected_images.update(IMAGE_DATABASE[key])
            else:
                # 记录一下无效的 key，但不报错
                logger.warning(f"Key '{key}' not found in IMAGE_DATABASE")

    # 4. 返回简单的列表 (排序以保证确定性)
    return sorted(list(collected_images))


# ==========================================
# Main 测试入口
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(">>> 调试 utils/image_finder.py <<<")

    print("\n--- 测试 1: 单个参数 ---")
    # 预期: ['gym.jpg']
    print(get_image_list_logic(targets="gym"))

    print("\n--- 测试 2: 多个参数 (含重复图片) ---")
    # 2BD 和 3BR 图片一样，预期结果应该自动去重，只返回一套 S74 图片
    print(get_image_list_logic(targets=["2BD", "3BR"]))

    print("\n--- 测试 3: 获取7楼公区 + 大厅 ---")
    # 预期: 所有7楼图片 + lobby 图片
    print(get_image_list_logic(targets=["lobby"], all_public_areas="true"))

    print("\n--- 测试 4: 错误参数 ---")
    # 预期: 空列表 [] (因为不支持中文别名了)
    print(get_image_list_logic(targets=["游泳池"]))

    print("\n--- 测试 5: 获取7楼公区---")
    # 预期: 所有7楼图片 + lobby 图片
    print(get_image_list_logic(all_public_areas="true"))