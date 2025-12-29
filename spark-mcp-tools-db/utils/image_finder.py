import logging
import json
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
    "bar": ["bar.jpg"],
    "gym": ["gym.jpg"],
    "ktv": ["ktv.jpg"],
    "music": ["music_room.jpg"],
    "patio": ["patio.jpg"],
    "pool": ["pool.jpg"],
    "kitchen": ["privatekitchen.jpg"],
    "booth": ["telephone_booth.jpg"],
    "yoga": ["yoga_room.jpg"],

    # --- 房型 ---
    "STD": ["n29_01.jpg", "n29_02.jpg"], # 豪华单间
    "STE": ["s35_01.jpg", "s35_02.jpg", "s35_03.jpg", "s35_04.jpg"], # 行政单间
    "1BD": ["n46_01.jpg", "n46_02.jpg", "n46_03.jpg", "n46_04.jpg"], # 一房豪华
    "1BP": ["n59_01.jpg", "n59_02.jpg", "n59_03.jpg", "n59_04.jpg"], # 一房行政
    "STP": ["s50_01.jpg", "s50_02.jpg", "s50_03.jpg"], # 行政豪华单间
    "2BD": ["s74_01.jpg", "s74_02.jpg", "s74_03.jpg", "s74_04.jpg", "s74_05.jpg"], # 两房 (共用 S74)
    "3BR": ["s74_01.jpg", "s74_02.jpg", "s74_03.jpg", "s74_04.jpg", "s74_05.jpg"], # 三房 (共用 S74)
}

# 定义哪些 Key 属于“所有7楼公区”
PUBLIC_AREAS_7F = [
    "bar", "gym", "ktv", "music", 
    "patio", "pool", "kitchen", "booth", "yoga"
]

def get_image_list_logic(
    targets: Optional[Union[str, List[str]]] = None,
    all_public_areas: Optional[str] = None
) -> str:
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
        target_list = []
        if isinstance(targets, list):
            target_list = targets
        elif isinstance(targets, str):
            # 处理 "lobby,gym" 这种非JSON格式
            # 去除可能存在的括号引号，按逗号分割
            clean_str = targets.replace('[', '').replace(']', '').replace('"', '').replace("'", "")
            target_list = [t.strip() for t in clean_str.split(',') if t.strip()]
            
        for t in target_list:
            key = str(t).strip()
            # 精确匹配 Key，不搞任何模糊搜索或中文映射
            if key in IMAGE_DATABASE:
                collected_images.update(IMAGE_DATABASE[key])
            else:
                # 记录一下无效的 key，但不报错
                logger.warning(f"Key '{key}' not found in IMAGE_DATABASE")

    # 4. 返回 JSON 字符串 (解决 Output validation error)
    final_list = sorted(list(collected_images))
    return json.dumps(final_list, ensure_ascii=False)


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

    print("\n--- 测试 6: JSON 字符串列表 ---")
    print(get_image_list_logic(targets='["STE", "1BD"]'))

    print("\n--- 测试 7: 逗号分隔字符串 (之前的报错点) ---")
    print(get_image_list_logic(targets="lobby,gym,pool"))

    print("\n--- 测试 8: Python 列表 ---")
    print(get_image_list_logic(targets=["STD", "2BD"]))