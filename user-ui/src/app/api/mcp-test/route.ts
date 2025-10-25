// app/api/mcp-test/route.ts

import { NextRequest, NextResponse } from 'next/server';
import { ToolClient } from '@/lib/llm/tools/tool-client';

interface TestRequestBody {
  url: string;
}

interface TestResponse {
  status: 'ok' | 'error';
  serverType: string;
  url: string;
  toolsCount: number;
  tools?: unknown[];
  message: string;
  error?: string;
  details?: string;
}

// MCP服务器连通性测试
export async function POST(request: NextRequest): Promise<NextResponse<TestResponse>> {
  try {
    const body = await request.json() as TestRequestBody;
    const url = body.url;

    if (!url || typeof url !== 'string') {
      return NextResponse.json({ 
        status: 'error',
        serverType: 'unknown',
        url: url || '',
        toolsCount: 0,
        message: 'URL is required'
      } as TestResponse, { status: 400 });
    }

    console.log(`--- [MCP Test] Testing connection to: ${url} ---`);

    try {
      // 使用ToolClient测试连接
      const client = new ToolClient(url);

      // 测试获取工具列表
      const tools = await client.getToolsSchema();

      // 验证至少有一个工具
      if (!tools || tools.length === 0) {
        throw new Error('No tools available on the server');
      }

      // 获取检测到的服务器类型
      const detectedServerType = await client.getServerType();
      const serverType = detectedServerType === 'fastmcp-sse' || detectedServerType === 'fastmcp-streamablehttp' ? 'FastMCP' :
                        detectedServerType === 'fastapi' ? 'FastAPI' : 'Unknown';

      const result: TestResponse = {
        status: 'ok',
        serverType,
        url,
        toolsCount: tools.length,
        tools: tools.slice(0, 3), // 返回前3个工具作为示例
        message: `Successfully connected to ${serverType} server with ${tools.length} tools`
      };

      return NextResponse.json(result, { status: 200 });
    } catch (clientError) {
      console.error('[MCP Test] ToolClient error:', clientError);
      // 回退到简单的HTTP健康检查
      try {
        const targetUrl = url.endsWith('/sse') ? url.replace('/sse', '') : url;
        const response = await fetch(targetUrl, {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
        });

        if (!response.ok) {
          throw new Error(`HTTP status: ${response.status}`);
        }

        await response.json(); // 确保可以解析JSON
        return NextResponse.json({
          status: 'ok',
          serverType: 'FastAPI (HTTP fallback)',
          url,
          toolsCount: 0,
          message: 'Connected via HTTP fallback (ToolClient failed)'
        } as TestResponse, { status: 200 });
      } catch (httpError) {
        const errorMessage = `Both ToolClient and HTTP fallback failed. ToolClient: ${(clientError as Error).message}, HTTP: ${httpError instanceof Error ? httpError.message : String(httpError)}`;
        return NextResponse.json({ 
          status: 'error',
          serverType: 'unknown',
          url,
          toolsCount: 0,
          message: 'Failed to connect to MCP server',
          error: errorMessage,
          details: errorMessage
        } as TestResponse, { status: 500 });
      }
    }
  } catch (error) {
    console.error('MCP Test JSON Parse Error:', error);
    return NextResponse.json({ 
      status: 'error',
      serverType: 'unknown',
      url: '',
      toolsCount: 0,
      message: 'Invalid request format',
      error: error instanceof Error ? error.message : String(error)
    } as TestResponse, { status: 400 });
  }
}