from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
import uvicorn

from tool_registry import TOOL_REGISTRY, get_tools_schema

# --- 1. 初始化 FastAPI 应用 ---
app = FastAPI(
    title="MCP (Model Calling Protocol) Tool Server",
    description="一个标准的、可被大模型调用的工具执行服务，用于公寓数据查询。",
    version="1.0.0",
)

# --- 2. 定义 API 的数据模型 ---
class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]

class ToolCallResponse(BaseModel):
    result: Any

# --- 3. 创建 API 接口 ---
@app.get("/tools", 
         summary="发现可用工具 (Tool Discovery)",
         response_model=list[Dict[str, Any]])
async def list_tools():
    """
    返回所有已注册工具的列表，其格式遵循 OpenAI Function Calling/Tool Calling Schema。
    """
    return get_tools_schema()


@app.post("/call", 
          summary="执行指定工具 (Tool Execution)",
          response_model=ToolCallResponse)
async def call_tool(request: ToolCallRequest):
    """
    接收 LLM 的指令，执行一个指定的工具并返回结果。
    """
    tool_name = request.tool_name
    arguments = request.arguments
    
    tool_function = TOOL_REGISTRY.get(tool_name)
    
    if not tool_function:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")
        
    try:
        # 使用 **arguments 将字典解包为函数的关键字参数
        print(f"--- [Tool Executing] Name: {tool_name}, Arguments: {arguments} ---")
        result = tool_function(**arguments)
        print(f"--- [Tool Execution Finished] Result received ---")
        return ToolCallResponse(result=result)
    except Exception as e:
        error_message = f"Error executing tool '{tool_name}': {str(e)}"
        print(f"--- [Tool Execution Error] {error_message} ---")
        raise HTTPException(status_code=500, detail=error_message)


@app.get("/", summary="健康检查")
async def health_check():
    """提供一个简单的健康检查接口，确认服务正在运行。"""
    return {"status": "ok", "available_tools_count": len(TOOL_REGISTRY)}

# 终端启动指令：uvicorn main:app --host 0.0.0.0 --port 8000
if __name__ == "__main__":
    print("Starting MCP FastAPI server on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)