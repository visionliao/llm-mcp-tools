import { NextRequest, NextResponse } from 'next/server';
import { handleChat } from '@/lib/llm/model-service';
import { ChatMessage, LlmGenerationOptions } from '@/lib/llm/types';

/**
 * API 端点 (Controller)，处理聊天请求。
 * 职责：解析 HTTP 请求，调用服务层，返回 HTTP 响应。
 */
export async function POST(request: NextRequest) {
  try {
    // 1. 解析 HTTP 请求体
    const body = await request.json();
    const { selectedModel, messages, options } = body as { 
      selectedModel: string; 
      messages: ChatMessage[];
      options?: LlmGenerationOptions;
    };

    // 基本的输入验证
    if (!selectedModel || !messages || !Array.isArray(messages)) {
      return NextResponse.json({ error: 'Missing or invalid parameters: selectedModel and messages are required.' }, { status: 400 });
    }

    // 2. 调用服务层处理核心业务逻辑
    const result = await handleChat(selectedModel, messages, options);

    // 3. 将服务层返回的结果作为 HTTP 响应返回给前端
    if (result instanceof ReadableStream) {
      // 如果是流
      return new NextResponse(result, {
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    } else {
      // 如果是字符串，直接返回 JSON 响应
      return NextResponse.json({ response: result });
    }
  } catch (error: any) {
    console.error('Chat API error:', error);
    // 根据错误类型返回不同的状态码
    const status = error instanceof TypeError ? 400 : 500;
    return NextResponse.json(
      { error: error.message || 'An internal server error occurred.' },
      { status }
    );
  }
}