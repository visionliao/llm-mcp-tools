// lib/llm/model-provider.ts

import {
  ChatMessage,
  BaseProviderConfig,
  LlmProviderResponse,
  TokenUsage,
  DurationUsage,
  StreamingResult,
  NonStreamingResult
} from './types';
import { getToolClientInstance } from './tools/tool-client-manager';
import { McpToolSchema } from './tools/tool-client';

/**
 * 所有聊天提供商（Provider）必须继承的抽象基类。
 * 它定义了统一的接口和基础架构。
 */
export abstract class BaseChatProvider {
  protected config: BaseProviderConfig;

  constructor(config: BaseProviderConfig) {
    this.config = config;
  }

  /**
   * 核心的工具调用循环，封装了流式和非流式共享的逻辑。
   * @param model 模型名称
   * @param messages 初始消息历史
   * @param isStreaming 标志位，用于区分调用模式
   * @returns 一个包含了流式输出模式下大模型最终结果(ReadableStream)和本次token消耗统计(TokenUsage)的结构体(StreamingResult)
   *      或者 非流式输出模式下包含文本字符串(content)和本次token消耗统计(TokenUsage)的结构体(NonStreamingResult)
   */
  private async _toolCallingLoop(
    model: string,
    messages: ChatMessage[],
    isStreaming: boolean
  ): Promise<StreamingResult | NonStreamingResult> {
    const MAX_TOOL_CALLS = this.config.maxToolCalls ?? 5; // 设置最大工具调用次数以防止无限循环
    let toolCallCount = 0;
    // 创建一个可变的消息历史副本，用于在循环中追加消息
    const currentMessages: ChatMessage[] = [...messages];
    // 初始化 Token 累加器
    let totalUsage: TokenUsage = {
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
    };
    console.log('[TokenCount] 初始token计数:', totalUsage);
    // 初始化耗时累加器
    let totalDuration: DurationUsage = {
        total_duration: 0,
        load_duration: 0,
        prompt_eval_duration: 0,
        eval_duration: 0,
    };

    while (toolCallCount < MAX_TOOL_CALLS) {
      // 1. 如果配置了 mcp，则获取工具列表
      let tools: McpToolSchema[] | undefined;
      if (this.config.mcpServerUrl) {
        try {
          console.log(`[BaseProvider] MCP server URL found: ${this.config.mcpServerUrl}. Fetching tools...`);
          const toolClient = getToolClientInstance(this.config.mcpServerUrl);
          tools = await toolClient.getToolsSchema();
        } catch (error) {
          // 如果工具获取失败，只打印错误，不中断聊天流程
          console.error("[BaseProvider] Failed to get tools schema, proceeding without tools.", error);
        }
      }

      // 2. 设置超时
      const controller = new AbortController();
      // 从配置中获取用户设置的超时时间，默认60s
      const timeoutMs = this.config.timeoutMs || 60000;
      let timeoutId: NodeJS.Timeout | null = null;
      const timeoutPromise = new Promise<never>((_, reject) => {
        timeoutId = setTimeout(() => {
          controller.abort(); // 超时，中止请求
          reject(new Error(`Request timed out after ${timeoutMs / 1000} seconds.`));
        }, timeoutMs);
      });

      // 3. 根据 isStreaming 标志调用不同的大模型子类实现
      const llmResponsePromise = isStreaming
        ? this._generateChatStream(model, currentMessages, controller.signal, tools)
        : this._generateChatNonStreaming(model, currentMessages, controller.signal, tools);

      const llmResponse = await Promise.race([llmResponsePromise, timeoutPromise]);
      // 收到响应后，清除定时器
      if (timeoutId) clearTimeout(timeoutId);

      // 使用类型守卫来判断是否为 StreamingResult
      function isStreamingResult(response: any): response is StreamingResult {
          return response && response.stream instanceof ReadableStream;
      }

      // 4. 根据模式和响应类型判断是否结束循环
      if (isStreamingResult(llmResponse)) {
      // if (isStreaming && llmResponse instanceof ReadableStream) {
        // console.log("接收流式输出文本流，判定流程结束，开始进行最终的异步流式输出。");
        // return llmResponse; // 流式模式下，收到流就直接返回

        // 一个包含了大模型最终结果和本次token消耗统计的结构体。
        const streamingResult = llmResponse as StreamingResult;

        // 异步地等待最终回复的token数据生成，在流式输出中，最终答案是一字一字蹦出来，等这个结束后才能拿到token消耗的信息。
        // 对于流式输出，这里是最终大模型回复的那次token消耗
        const finalAccumulationPromise: Promise<TokenUsage> = new Promise(async (resolve, reject) => {
          try {
            // 等待原始的、只包含最后一步用量的 Promise 完成
            const finalStepUsage = await streamingResult.finalUsagePromise;

            // 将最后一步的用量，累加到已经包含所有工具调用步骤的 totalUsage 中
            if (finalStepUsage) {
              totalUsage.prompt_tokens += finalStepUsage.prompt_tokens;
              totalUsage.completion_tokens += finalStepUsage.completion_tokens;
              totalUsage.total_tokens += finalStepUsage.total_tokens;
            }

            // 在控制台打印最终的、完整的总账单（用于调试）
            console.log("[TokenCount] 所有步骤完成后的最终token消耗情况:", JSON.stringify(totalUsage, null, 2));

            // 将包含了所有步骤总和的、最终的 totalUsage 对象，作为这个新 Promise 的结果
            resolve(totalUsage);
          } catch (e) {
            // 如果原始的 finalUsagePromise 失败，或者累加过程中出现任何错误
            console.error("[TokenCount] 在累加最终流式用量时发生错误:", e);
            reject(new Error("Failed to accumulate final token usage."));
          }
        });

        // 异步等待耗时数据
        const finalDurationAccumulationPromise: Promise<DurationUsage> = new Promise(async (resolve, reject) => {
          try {
            const finalStepDuration = await streamingResult.finalDurationPromise;
            if (finalStepDuration) {
                totalDuration.total_duration += finalStepDuration.total_duration;
                totalDuration.load_duration += finalStepDuration.load_duration;
                totalDuration.prompt_eval_duration += finalStepDuration.prompt_eval_duration;
                totalDuration.eval_duration += finalStepDuration.eval_duration;
            }
            console.log("[DurationCount] 所有步骤完成后的最终耗时情况:", JSON.stringify(totalDuration, null, 2));
            resolve(totalDuration);
          } catch (e) {
              console.error("[DurationCount] 在累加最终流式耗时发生错误:", e);
              reject(new Error("Failed to accumulate final duration."));
          }
        });
        // 立即返回 streamingResult 的通道，相当于一个引用地址，使用者实时从这个地址获取流数据。
        // 并且等待最终token统计结果数据，然后进行累加的最终token总消耗结果
        // 并且等待最终耗时统计结果数据...
        return {
          stream: streamingResult.stream,
          finalUsagePromise: finalAccumulationPromise,
          finalDurationPromise: finalDurationAccumulationPromise,
        };
      }

      const llmProviderResponse = llmResponse as LlmProviderResponse;
      // 对于非流式输出，这里包含了每一次工具调用的token消耗和大模型最终回复的token消耗统计
      if (llmProviderResponse.usage) {
        console.log(`[TokenCount] Step ${toolCallCount + 1} usage received from API:`, llmProviderResponse.usage);
        totalUsage.prompt_tokens += llmProviderResponse.usage.prompt_tokens;
        totalUsage.completion_tokens += llmProviderResponse.usage.completion_tokens;
        totalUsage.total_tokens += llmProviderResponse.usage.total_tokens;
        console.log(`[TokenCount] Accumulated total usage so far:`, totalUsage);
      } else {
        console.warn(`[TokenCount] Warning: Step ${toolCallCount + 1} did not return usage information.`);
      }
      // 累加每一步的耗时 (工具调用 或 非流式最终回复)
      if (llmProviderResponse.duration) {
        console.log(`[DurationCount] 第 ${toolCallCount + 1} 步耗时信息:`, llmProviderResponse.duration);
        totalDuration.total_duration += llmProviderResponse.duration.total_duration;
        totalDuration.load_duration += llmProviderResponse.duration.load_duration;
        totalDuration.prompt_eval_duration += llmProviderResponse.duration.prompt_eval_duration;
        totalDuration.eval_duration += llmProviderResponse.duration.eval_duration;
        console.log(`[DurationCount] 当前累积总耗时:`, totalDuration);
      } else {
        console.warn(`[DurationCount] Warning: Step ${toolCallCount + 1} did not return duration information.`);
      }
      const toolCalls = llmProviderResponse.tool_calls;
      
      if (!toolCalls || toolCalls.length === 0) {
        // 两种模式下，没有工具调用都意味着流程结束
        // 非流式直接返回内容，流式理论上应该在前一步返回流，但作为兜底
        // return llmProviderResponse.content || "";
        return {
          content: llmProviderResponse.content || "",
          usage: totalUsage,
          duration: totalDuration,
        };
      }

      // 5. 执行工具调用
      console.log(`模式: ${isStreaming ? '流式' : '非流式'} - 本次需要调用的工具数量 ${toolCalls.length} 个.`);
      // 将 assistant 的工具调用请求本身也加入到消息历史中
      currentMessages.push({
        role: 'assistant',
        content: llmProviderResponse.content, // content 可能是 null
        tool_calls: toolCalls,
      });

      // 6. 并行执行所有工具调用
      const toolClient = getToolClientInstance(this.config.mcpServerUrl!);
      const toolResultPromises = toolCalls.map(async (toolCall) => {
        const { name, arguments: args } = toolCall.function;
        try {
          console.log(`执行工具: ${name} 参数列表: ${args}`);
          const result = await toolClient.callTool(name, JSON.parse(args));
          // 7. 将每个工具的执行结果包装成一条 'tool' 消息
          return {
            role: 'tool' as const,
            tool_call_id: toolCall.id,
            content: typeof result === 'string' ? result : JSON.stringify(result),
          };
        } catch (error: any) {
          console.error(`执行 ${name} 工具错误:`, error);
          return { // 如果工具执行失败，也返回一条错误信息给大模型，大模型可以将失败原因作为最终输出返回给前端
            role: 'tool' as const,
            tool_call_id: toolCall.id,
            content: `Error: ${error.message}`,
          };
        }
      });

      // 8. 等待所有工具执行完毕，并将结果追加到消息历史
      const toolResults = await Promise.all(toolResultPromises);
      currentMessages.push(...toolResults);

      toolCallCount++;
      console.error(`工具循环调用次数: ${toolCallCount}`);
    }

    // 9. 循环结束（达到最大调用次数），抛出错误
    throw new Error("已达到单次对话工具最大调用次数限制。");
  }

  /**
   * 公开的聊天方法，是外部调用的统一入口。
   * 采用模板方法模式，内部调用子类必须实现的 _generateChatStream 方法。
   * @param model 要使用的具体模型名称
   * @param messages 对话历史记录
   * @returns 一个包含了大模型最终结果(ReadableStream)和本次token消耗统计(TokenUsage)的结构体(StreamingResult)
   */
  public async chatStreaming(model: string, messages: ChatMessage[]): Promise<StreamingResult> {
    if (messages.length === 0) {
      throw new Error("Message history cannot be empty.");
    }
    const result = await this._toolCallingLoop(model, messages, true);
    return result as StreamingResult // 确认返回类型
  }

  /**
   * 核心的抽象方法，每个具体的 Provider 子类都必须实现它。
   * 它负责与特定的 LLM API 进行通信。
   * @param model 模型名称
   * @param messages 对话历史
   * @param signal 用于在超时或外部取消时中止 fetch 请求
   * @return 一个包含了大模型最终结果(ReadableStream)和本次token消耗统计(TokenUsage)的结构体(StreamingResult)或者LlmProviderResponse
   */
  protected abstract _generateChatStream(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal,
    tools?: McpToolSchema[]
  ): Promise<StreamingResult | LlmProviderResponse>;

  /**
   * 非流式聊天方法。
   * 内置超时逻辑。
   * @returns 返回一个包含完整回复内容的字符串(content)和token消耗统计(TokenUsage)的结构体(NonStreamingResult)
   */
  public async chatNonStreaming(model: string, messages: ChatMessage[]): Promise<NonStreamingResult> {
    if (messages.length === 0) {
      throw new Error("传入的消息不能为空.");
    }
    const result = await this._toolCallingLoop(model, messages, false);
    return result as NonStreamingResult; // 确认返回类型
  }

  /**
   * 抽象方法，子类必须实现它以支持非流式调用。
   */
  protected abstract _generateChatNonStreaming(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal,
    tools?: McpToolSchema[]
  ): Promise<LlmProviderResponse>;
}