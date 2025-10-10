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
  const parts = selectedValue.split(':');
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    throw new TypeError('Invalid selectedModel format. Expected "provider:model".');
  }
  return { provider: parts[0], model: parts[1] };
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
    return chatProvider.chatStreaming(model, messages);
  }
}