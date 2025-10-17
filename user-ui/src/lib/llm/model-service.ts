// lib/llm/model-service.ts

import { createChatProvider } from './model-factory';
import { ChatMessage, LlmGenerationOptions, StreamingResult, NonStreamingResult, StreamChunk } from './types';
import { ProxyAgent, setGlobalDispatcher } from 'undici';

// 使用一个模块级别的变量确保代理设置只执行一次
let isProxyInitialized = false;
/**
 * 检查环境变量并设置全局网络代理。
 * 这将拦截所有由 undici（Next.js 后端 fetch 的基础）发出的请求。
 */
function initializeGlobalProxy() {
  if (isProxyInitialized) {
    return;
  }

  // 从环境变量中读取代理地址
  const proxyUrl = process.env.HTTPS_PROXY || process.env.HTTP_PROXY;

  if (proxyUrl) {
    try {
      console.log(`[ProxySetup] Global proxy found: ${proxyUrl}. Setting dispatcher...`);
      const dispatcher = new ProxyAgent(proxyUrl);
      setGlobalDispatcher(dispatcher);
      console.log(`[ProxySetup] Global dispatcher set successfully.`);
    } catch (error) {
      console.error("[ProxySetup] Failed to create or set global proxy dispatcher:", error);
    }
  } else {
    console.log("[ProxySetup] No HTTPS_PROXY or HTTP_PROXY environment variable found. Skipping proxy setup.");
  }
  
  isProxyInitialized = true;
}

/**
 * 解析从前端传来的模型值
 * @param selectedValue 格式为 "provider:model"
 * @returns 返回包含 provider 和 model 的对象
 */
function parseModelSelection(selectedValue: string): { provider: string; model: string } {
  if (!selectedValue) {
    throw new TypeError('Invalid selectedModel format. Value cannot be empty.');
  }

  // 解决ollama模型名称中带冒号导致解析模型名称异常的问题，如qwen3:0.6b
  const firstColonIndex = selectedValue.indexOf(':');
  // 检查：冒号必须存在，且不能是第一个或最后一个字符
  if (firstColonIndex <= 0 || firstColonIndex === selectedValue.length - 1) {
    throw new TypeError(`Invalid selectedModel format. Expected "provider:model", but received "${selectedValue}".`);
  }

  const provider = selectedValue.substring(0, firstColonIndex);
  const model = selectedValue.substring(firstColonIndex + 1);

  return { provider, model };
}

/**
 * 聊天服务的核心业务逻辑。
 * 职责：编排业务流程（解析、创建实例、调用方法）。
 * @param selectedModel 从前端传来的模型值
 * @param messages 对话历史
 * @returns 返回一个可读的文本流
 */
export async function handleChat(
  selectedModel: string,
  messages: ChatMessage[],
  options?: LlmGenerationOptions
): Promise<ReadableStream<Uint8Array> | NonStreamingResult> {
  // 在处理任何请求之前，首先确保代理已初始化
  initializeGlobalProxy();

  // 1. 解析输入参数
  const { provider, model } = parseModelSelection(selectedModel);

  // 2. 使用工厂创建对应的 Provider 实例
  const chatProvider = await createChatProvider(provider, options);

  // 3. 调用 Provider 的方法执行核心操作
  // 如果 stream 选项为 false，则调用非流式方法。
  // 默认（undefined）或 true 时，调用流式方法。
  if (options?.stream === false) {
    const result: NonStreamingResult = await chatProvider.chatNonStreaming(model, messages);
    console.log(`[handleChat] 成功接收到非流式用量数据:`, result.usage);

    return result;
  } else {
    // return chatProvider.chatStreaming(model, messages);
    // 1. 返回一个包含了大模型最终结果(ReadableStream)和本次token消耗统计(TokenUsage)的结构体(StreamingResult)
    const result: StreamingResult = await chatProvider.chatStreaming(model, messages);

    // 2. 创建一个新的 TransformStream 来处理和转换数据为字节流
    const { readable, writable } = new TransformStream<Uint8Array, Uint8Array>();

    const writer = writable.getWriter();
    const reader = result.stream.getReader(); // 这是原始的文本流 reader
    const encoder = new TextEncoder();

    // 3. 异步地将原始文本流转换为包含 StreamChunk 的 SSE 字节流
    (async () => {
      try {
        // 首先处理文本流
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const textChunk: StreamChunk = { type: 'text', payload: value };
          await writer.write(encoder.encode(toSSE(textChunk)));
        }

        // 文本流结束后，等待 finalUsagePromise
        const finalUsage = await result.finalUsagePromise;
        if (finalUsage) {
          console.log(`[handleChat] 将最终用量数据注入 SSE 流中:`, finalUsage);
          const usageChunk: StreamChunk = { type: 'usage', payload: finalUsage };
          await writer.write(encoder.encode(toSSE(usageChunk)));
        }
      } catch (e) {
        console.error("在 SSE 流转换中发生错误:", e);
        writer.abort(e);
      } finally {
        writer.close();
      }
    })();

    // 4. 返回包含了大模型回复流和token消耗结构数据的流
    return readable;
  }
}

// 流式输出中，将模型回复流和token消耗结构数据格式化为 SSE 字符串
function toSSE(chunk: StreamChunk): string {
  return `data: ${JSON.stringify(chunk)}\n\n`;
}