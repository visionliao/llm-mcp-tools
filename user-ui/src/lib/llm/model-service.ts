// lib/llm/model-service.ts

import { createChatProvider } from './model-factory';
import { ChatMessage, LlmGenerationOptions } from './types';
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
): Promise<ReadableStream<string> | string> {
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
    return chatProvider.chatNonStreaming(model, messages);
  } else {
    // return chatProvider.chatStreaming(model, messages);
    // 返回一个包含了大模型最终结果(ReadableStream)和本次token消耗统计(TokenUsage)的结构体(StreamingResult)
    const result = await chatProvider.chatStreaming(model, messages);

    // 在这里，您可以访问 finalUsagePromise 并决定如何处理它。
    // 例如，您可以等待它，然后将结果存入数据库或缓存。
    // 现在，我们只把它打印出来，证明数据已经成功传递到了顶层。
    result.finalUsagePromise.then(usage => {
      if (usage) {
        // console.log(`[handleChat] 成功接收到最终的流式用量数据:`, usage);
        // 在这里可以添加数据库记录等操作
      }
    });

    // *** 最重要的是，我们只将 stream 部分返回给 Next.js 的响应体 ***
    return result.stream;
  }
}