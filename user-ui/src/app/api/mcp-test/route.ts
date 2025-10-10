// app/api/mcp-test/route.ts

import { NextRequest, NextResponse } from 'next/server';

// MCP服务器连通性测试
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const url = body.url;

    if (!url || typeof url !== 'string') {
      return NextResponse.json({ error: 'URL is required' }, { status: 400 });
    }

    // 调用 MCP 服务的健康检查接口
    const response = await fetch(url, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      throw new Error(`MCP server returned status: ${response.status}`);
    }

    const data = await response.json();

    // 可以在这里添加更严格的检查，例如检查返回的数据结构
    if (data.status !== 'ok') {
        throw new Error('MCP server response format is incorrect.');
    }

    return NextResponse.json(data, { status: 200 });
  } catch (error: any) {
    console.error('MCP Test Error:', error);
    return NextResponse.json({ error: error.message || 'Failed to connect to MCP server' }, { status: 500 });
  }
}