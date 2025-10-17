// lib/llm/providers/ollama.ts

import { Ollama, type Message, type ChatResponse } from 'ollama';
import { BaseChatProvider } from '../base-provider';
import {
  BaseProviderConfig,
  ChatMessage,
  LlmGenerationOptions,
  ToolCall,
  LlmProviderResponse,
  StreamingResult,
  TokenUsage
} from '../types';
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
  ): Promise<StreamingResult | LlmProviderResponse> {
    const options = this.buildOllamaOptions();

    // --- 日志记录 ---
    console.log('\n--- [LLM Request Log - Streaming] ---');
    console.log(`Timestamp: ${new Date().toISOString()}`);
    console.log('Provider: Ollama');
    console.log('Model:', model);
    console.log('参数配置信息:', JSON.stringify(options, null, 2));
    if (tools) console.log('可用工具数量: ', tools.length);
    console.log('最大工具调用次数限制:', this.config.maxToolCalls ?? 5);
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
        think: false, // 关闭思考过程的输出
      });

      // 1. 获取流的异步迭代器，以便获取第一个块
      const streamIterator = response[Symbol.asyncIterator]();
      const firstPartResult = await streamIterator.next();

      // 2. 如果流一开始就是空的，直接返回一个空的流
      if (firstPartResult.done) {
        // 如果流为空
        // Ollama SDK 在空流时不会返回最终的 ChatResponse，所以返回一个空的用量。
        return { content: null, tool_calls: undefined, usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 } };
      }

      // 获取第一个有内容的流块
      const firstPart = firstPartResult.value;
      const toolCallsInPart = firstPart.message.tool_calls;

      // 3. 检查第一个数据块是否包含工具调用
      if (toolCallsInPart && toolCallsInPart.length > 0) {
        // 工具调用
        console.log('ollama大模型返回工具调用消息:', JSON.stringify(toolCallsInPart, null, 2));

        // 从 firstPart 拿到了所有的 tool_calls。
        // 所以只需要消耗掉流的剩余部分，从而得到最后的token数据。
        let finalResponse: ChatResponse = firstPart;
        while (true) {
          const nextPartResult = await streamIterator.next();
          if (nextPartResult.done) {
            // 如果 nextPartResult.done 为 true, 它的 value (即最后一个块) 是 undefined。
            // 所以最后一个有效的块是上一次循环的 finalResponse。
            break;
          }
          finalResponse = nextPartResult.value;
        }

        // 确保拿到最后一个 done: true 的块
        if (!finalResponse.done) {
            console.warn("[Ollama Provider] Stream ended unexpectedly without a 'done' message.");
        }

        // 从最后一个数据块中提取token消耗数据
        const usage: TokenUsage = {
          prompt_tokens: finalResponse.prompt_eval_count ?? 0,
          completion_tokens: finalResponse.eval_count ?? 0,
          total_tokens: (finalResponse.prompt_eval_count ?? 0) + (finalResponse.eval_count ?? 0),
        };

        // 4. 将 Ollama 的工具调用格式转换为 ToolCall[] 格式
        const toolCalls: ToolCall[] = toolCallsInPart.map((tc, index) => ({
          id: `${tc.function.name}_${Date.now()}_${index}`, // Ollama 不提供ID，手动创建一个
          type: 'function',
          function: {
            name: tc.function.name,
            // Ollama 返回的是对象，将其字符串化以符合ToolCall的类型
            arguments: JSON.stringify(tc.function.arguments)
          }
        }));

        // 5. 返回工具调用的结构化数据和本地工具调用的token用量
        return {
          content: finalResponse.message.content || null,
          tool_calls: toolCalls,
          usage: usage,
        };
      } else {
        // 普通文本流，表示没有工具调用，或者工具调用完毕这是大模型最终的回复
        console.log('流式输出第一个数据块是文本，将返回 ReadableStream');

        // finalUsagePromise 将在流结束后解析
        let finalUsageResolver: (usage: TokenUsage | undefined) => void;
        const finalUsagePromise = new Promise<TokenUsage | undefined>(resolve => {
          finalUsageResolver = resolve;
        });

        // 将 Ollama SDK 的流转换为标准的 Web ReadableStream
        const stream = new ReadableStream<string>({
          async start(controller) {
            try {
              // 推入第一个块的文本
              const firstContent = firstPart.message.content;
              if (firstContent) {
                console.log('ollama大模型返回文本流:', firstContent);
                controller.enqueue(firstContent);
              }

              // 继续处理流中剩余的块
              let finalResponse: ChatResponse = firstPart;
              // 注意：不能直接 for await...next()，因为 firstPart 已经被消费
              // 所以重新创建一个迭代器来处理剩余部分 (或者可以直接在循环中处理 firstPart)
              // 直接在循环中处理
              for await (const part of response) {
                  finalResponse = part; // 始终保留最后一个 part
                  if (part.message.content) {
                      console.log('ollama大模型返回文本流:', part.message.content);
                      controller.enqueue(part.message.content);
                  }
              }

              // 流结束时，`finalResponse` 就是那个 done: true 的块
              if (finalResponse.done) {
                const usage: TokenUsage = {
                  prompt_tokens: finalResponse.prompt_eval_count ?? 0,
                  completion_tokens: finalResponse.eval_count ?? 0,
                  total_tokens: (finalResponse.prompt_eval_count ?? 0) + (finalResponse.eval_count ?? 0),
                };
                finalUsageResolver(usage);
              } else {
                finalUsageResolver(undefined); // 异常情况
              }
            } catch (e) {
                console.error("Ollama stream processing error:", e);
                finalUsageResolver(undefined);
                controller.error(e);
            } finally {
                controller.close();
            }
          },
        });
        // 返回大模型回复的文本流和token消耗统计结构体
        return {
          stream: stream,
          finalUsagePromise: finalUsagePromise
        };
      }
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
    console.log('最大工具调用次数限制:', this.config.maxToolCalls ?? 5);
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
        think: false, // 关闭思考过程的输出
      });

      const responseMessage = response.message;
      console.log('ollama大模型响应非流式输出:', JSON.stringify(responseMessage, null, 2));

      // 提取 Token 用量
      const usage: TokenUsage = {
        prompt_tokens: response.prompt_eval_count ?? 0,
        completion_tokens: response.eval_count ?? 0,
        // 对于 Ollama，total 就是两者之和
        total_tokens: (response.prompt_eval_count ?? 0) + (response.eval_count ?? 0),
      };

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
        usage: usage,
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