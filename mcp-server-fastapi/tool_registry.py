import inspect
from typing import Dict, Any, Callable
from pydantic import create_model, Field
import typing

# 从工具文件中导入所有函数
from tools.functions import (
    get_current_time,
    calculate_expression,
    calculate_occupancy,
    occupancy_details,
    query_guest,
    query_checkins,
    query_by_room,
    query_orders,
    advanced_query_service,
)

# --- 1. 工具注册表 ---
# 将工具名称映射到实际的 Python 函数
TOOL_REGISTRY: Dict[str, Callable] = {
    "get_current_time": get_current_time,
    "calculate_expression": calculate_expression,
    "calculate_occupancy": calculate_occupancy,
    "occupancy_details": occupancy_details,
    "query_guest": query_guest,
    "query_checkins": query_checkins,
    "query_by_room": query_by_room,
    "query_orders": query_orders,
    "advanced_query_service": advanced_query_service,
}

# --- 2. Schema 动态生成器 ---
def get_tools_schema() -> list[Dict[str, Any]]:
    """
    动态生成所有已注册工具的 OpenAI 兼容 JSON Schema。
    """
    tools_schema = []
    for tool_name, tool_function in TOOL_REGISTRY.items():
        sig = inspect.signature(tool_function)
        
        # 解析函数参数来构建 Pydantic 模型
        param_fields = {}
        for name, param in sig.parameters.items():
            # 获取类型提示，处理 Optional 和 Union
            annotation = param.annotation
            
            # Pydantic 需要这种方式来正确处理 Optional[T] -> T
            if typing.get_origin(annotation) is typing.Union and type(None) in typing.get_args(annotation):
                # E.g., Optional[str] becomes (str, None)
                annotation = typing.Union[tuple(t for t in typing.get_args(annotation) if t is not type(None))]

            default_value = ... if param.default == inspect.Parameter.empty else param.default
            param_fields[name] = (annotation, Field(default=default_value))

        # 动态创建 Pydantic 模型
        ParametersModel = create_model(f"{tool_name.capitalize()}Params", **param_fields)
        
        # 提取函数文档字符串作为描述
        description = inspect.getdoc(tool_function)

        tool_schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": description,
                "parameters": ParametersModel.model_json_schema(),
            },
        }
        tools_schema.append(tool_schema)
        
    return tools_schema