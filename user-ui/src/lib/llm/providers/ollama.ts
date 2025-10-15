import { Ollama, type Message } from 'ollama';
import { BaseChatProvider } from '../base-provider';
import { BaseProviderConfig, ChatMessage, LlmGenerationOptions, ToolCall, LlmProviderResponse } from '../types';
import { McpToolSchema } from '../tools/tool-client';

// Ollama API 使用不同的参数名，我们需要一个映射
// 例如：maxOutputTokens -> num_predict
const paramMapping: { [K in keyof LlmGenerationOptions]?: string } = {
  maxOutputTokens: 'num_predict',
  temperature: 'temperature',
  topP: 'top_p',
  // Ollama 的核心 API 不直接支持 presence_penalty 或 frequency_penalty
  // 它有一个 'repeat_penalty' 参数，但含义不完全相同。
  // 为保持简洁，我们暂时不映射这两个参数。
};

export class OllamaChatProvider extends BaseChatProvider {
  private ollama: Ollama;

  constructor(config: BaseProviderConfig) {
    super(config);
    // 使用 OLLAMA_PROXY_URL 作为 host
    this.ollama = new Ollama({ host: this.config.proxyUrl || 'http://127.0.0.1:11434' });
  }

  /**
   * 将通用选项转换为 Ollama 特定格式的 options 对象
   */
  private buildOllamaOptions() {
    const options: any = {};
    for (const genericName in paramMapping) {
      // 确保 genericName 是 LlmGenerationOptions 的一个键
      const key = genericName as keyof LlmGenerationOptions;
      const ollamaName = paramMapping[key];

      if (ollamaName && this.config[key] !== undefined) {
        options[ollamaName] = this.config[key];
      }
    }
    return options;
  }

  /**
   * 将 ChatMessage[] 格式化为 Ollama 库所需的 Message[] 格式。
   * @param messages 消息数组
   * @returns 符合 Ollama SDK 要求的消息数组
   */
  private formatMessagesForOllama(messages: ChatMessage[]): Message[] {
    return messages.map(msg => {
      // 创建一个符合 Ollama.Message 基础结构的对象
      const formattedMessage: Message = {
        role: msg.role as 'user' | 'assistant' | 'system' | 'tool',
        content: msg.content ?? '', // 确保 content 是 string
      };

      // 如果是 assistant 发出的工具调用，需要特殊处理 tool_calls 字段
      if (msg.role === 'assistant' && msg.tool_calls) {
        formattedMessage.tool_calls = msg.tool_calls.map(tc => ({
          function: {
            name: tc.function.name,
            // 将 JSON 字符串解析回 JavaScript 对象
            arguments: JSON.parse(tc.function.arguments),
          },
        }));
      }

      return formattedMessage;
    });
  }

  // 辅助函数，用于构建每次 API 请求所需的消息体，主要是为了把系统提示词放进去
  private buildMessagesForApi(messages: ChatMessage[]): ChatMessage[] {
    // 创建一个全新的数组副本，以避免修改原始历史
    const apiMessages = [...messages];

    // 如果配置了 systemPrompt
    if (this.config.systemPrompt) {
      const firstMessage = apiMessages[0];
      // 检查第一条消息是否已经是 system prompt
      if (firstMessage && firstMessage.role === 'system') {
        // 如果是，就用新的内容更新它，以支持动态修改
        firstMessage.content = this.config.systemPrompt;
      } else {
        // 如果不是，就在最前面插入一个新的 system prompt
        apiMessages.unshift({ role: 'system', content: this.config.systemPrompt });
      }
    }
    return apiMessages;
  }

  protected async _generateChatStream(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal,
    tools?: McpToolSchema[]
  ): Promise<ReadableStream<string>> {
    const options = this.buildOllamaOptions();

    // --- 日志记录 ---
    console.log('\n--- [LLM Request Log - Streaming] ---');
    console.log(`Timestamp: ${new Date().toISOString()}`);
    console.log('Provider: Ollama');
    console.log('Model:', model);
    console.log('参数配置信息:', JSON.stringify(options, null, 2));
    if (tools) console.log('可用工具数量: ', tools.length);
    console.log('-------------------------------------\n');

    try {
      // 将系统提示词添加消息中
      const messagesForApi = this.buildMessagesForApi(messages);
      // 消息格式转换
      const formattedMessages = this.formatMessagesForOllama(messagesForApi);
      console.log('ollama发送给大模型的消息:', JSON.stringify(formattedMessages, null, 2));

      const response = await this.ollama.chat({
        model: model,
        messages: formattedMessages,
        stream: true,
        options: options,
        tools: tools,
      });

      // 将 Ollama SDK 的流转换为标准的 Web ReadableStream
      const stream = new ReadableStream<string>({
        async start(controller) {
          // Ollama SDK 的 AbortSignal 处理
          signal.addEventListener('abort', () => {
            // SDK 内部可能没有直接的 abort 方法，但这是一种尝试
            // 实际上超时由 base-provider 的 Promise.race 控制
            controller.error(new Error("Request was aborted."));
          });

          for await (const part of response) {
            const messageChunk = part.message.content;
            if (messageChunk) {
              console.log(`ollama大模型流式输出: "${messageChunk}"`);
              controller.enqueue(messageChunk);
            }
          }
          controller.close();
        },
      });

      return stream;
    } catch (error: any) {
      console.error("Ollama API Error (Streaming):", error.message);
      throw new Error(`Failed to get response from Ollama: ${error.message}`);
    }
  }

  protected async _generateChatNonStreaming(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal,
    tools?: McpToolSchema[]
  ): Promise<LlmProviderResponse> {
    const options = this.buildOllamaOptions();
    
    // --- 日志记录 ---
    console.log('\n--- [LLM Request Log - Non-Streaming] ---');
    console.log(`Timestamp: ${new Date().toISOString()}`);
    console.log('Provider: Ollama');
    console.log('Model:', model);
    console.log('参数配置信息:', JSON.stringify(options, null, 2));
    if (tools) console.log('可用工具数量: ', tools.length);
    console.log('-----------------------------------------\n');

    try {
      // 将系统提示词添加消息中
      const messagesForApi = this.buildMessagesForApi(messages);
      // 消息格式转换
      const formattedMessages = this.formatMessagesForOllama(messagesForApi);
      console.log('ollama发送给大模型的消息:', JSON.stringify(formattedMessages, null, 2));
      // 非流式调用，可以通过 AbortSignal 和超时来控制
      // Ollama 库的 fetch 调用会继承设置的全局 dispatcher
      const response = await this.ollama.chat({
        model: model,
        messages: formattedMessages,
        stream: false,
        options: options,
        tools: tools,
      });

      const responseMessage = response.message;
      console.log('ollama大模型响应非流式输出:', JSON.stringify(responseMessage, null, 2));
      const toolCalls: ToolCall[] | undefined = responseMessage.tool_calls?.map((tc, index) => ({
        // Ollama 不提供ID，创建一个
        id: `${tc.function.name}_${Date.now()}_${index}`,
        type: 'function',
        function: {
          name: tc.function.name,
          // Ollama 返回的是对象，将其字符串化以符合ToolCall的类型
          arguments: JSON.stringify(tc.function.arguments),
        }
      }));

      return {
        content: responseMessage.content,
        tool_calls: toolCalls,
      };
    } catch (error: any) {
      if (error.name === 'AbortError') {
        throw new Error(`Request to Ollama timed out.`);
      }
      console.error("Ollama API Error (Non-Streaming):", error.message);
      throw new Error(`Failed to get non-streaming response from Ollama: ${error.message}`);
    }
  }
}