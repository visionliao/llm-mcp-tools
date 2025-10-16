// lib/llm/model-provider.ts

import { ChatMessage, BaseProviderConfig, LlmProviderResponse } from './types';
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
   * 公开的聊天方法，是外部调用的统一入口。
   * 采用模板方法模式，内部调用子类必须实现的 _generateChatStream 方法。
   * @param model 要使用的具体模型名称
   * @param messages 对话历史记录
   * @returns 返回一个字符串的可读流 (ReadableStream)
   */
  public async chatStreaming(model: string, messages: ChatMessage[]): Promise<ReadableStream<string> | LlmProviderResponse> {
    if (messages.length === 0) {
      throw new Error("Message history cannot be empty.");
    }

    const MAX_TOOL_CALLS = 5; // 设置最大工具调用次数以防止无限循环
    let toolCallCount = 0;
    // 创建一个可变的消息历史副本，用于在循环中追加消息
    const currentMessages: ChatMessage[] = [...messages];

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

      // 2. 超时判断
      const controller = new AbortController();
      // 从实例自身的配置中获取最终确定的超时时间
      const timeoutMs = this.config.timeoutMs || 60000;
      let timeoutId: NodeJS.Timeout | null = null;
      const timeoutPromise = new Promise<never>((_, reject) => {
        timeoutId = setTimeout(() => {
          controller.abort(); // 超时后，中止请求
          reject(new Error(`Request timed out after ${timeoutMs / 1000} seconds.`));
        }, timeoutMs);
      });

      // 3. 获取 LLM 的响应
      const llmResponsePromise = this._generateChatStream(model, currentMessages, controller.signal, tools);
      const llmResponse = await Promise.race([llmResponsePromise, timeoutPromise]);
      // 收到响应后，清除定时器
      if (timeoutId) clearTimeout(timeoutId);

      // 4. 检查 LLM 的响应中是否包含工具调用请求
      if (llmResponse instanceof ReadableStream) {
        // 返回的是流，说明没有工具调用，或者工具调用完毕后的大模型最终回复
        console.log("接收流式输出文本流，判定流程结束，开始进行最终的异步流式输出。");
        return llmResponse;
      } else {
        // 5. 返回LlmProviderResponse，执行工具调用
        const llmResponseTool = llmResponse as LlmProviderResponse;
        const toolCalls = llmResponseTool.tool_calls;
        // 理论上既然返回的不是流，toolCalls 应该存在，做一个健壮性检查
        if (!toolCalls || toolCalls.length === 0) {
          throw new Error("逻辑错误: LLM 返回了非流式工具响应但没有找到工具调用信息。");
        }
        console.log(`流式输出本次需要调用的工具数量 ${toolCalls.length} 个.`);

        // 6. 将 assistant 的工具调用请求本身也加入到消息历史中
        currentMessages.push({
          role: 'assistant',
          content: llmResponse.content, // content 可能是 null
          tool_calls: llmResponse.tool_calls,
        });

        // 7. 并行执行所有工具调用
        const toolClient = getToolClientInstance(this.config.mcpServerUrl!);
        const toolResultPromises = toolCalls.map(async (toolCall) => {
          const { name, arguments: args } = toolCall.function;
          try {
            console.log(`执行工具: ${name} 参数列表: ${args}`);
            const result = await toolClient.callTool(name, JSON.parse(args))
            // 8. 将每个工具的执行结果包装成一条 'tool' 消息
            return {
              role: 'tool' as const,
              tool_call_id: toolCall.id,
              content: typeof result === 'string' ? result : JSON.stringify(result),
            };
          } catch (error: any) {
            console.error(`执行 ${name} 工具错误:`, error);
            return { // 如果工具执行失败，也返回一条错误信息
              role: 'tool' as const,
              tool_call_id: toolCall.id,
              content: `Error: ${error.message}`,
            };
          }
        });

        // 9. 等待所有工具执行完毕，并将结果追加到消息历史
        const toolResults = await Promise.all(toolResultPromises);
        currentMessages.push(...toolResults);

        toolCallCount++;
        // 循环继续，携带更新后的消息历史再次调用 LLM
        console.error(`工具循环调用次数: ${toolCallCount}`);
      }
    }
    // 10. 如果循环结束（达到最大调用次数），则抛出错误
    throw new Error("已达到单次对话工具最大调用次数限制。");
  }

  /**
   * 核心的抽象方法，每个具体的 Provider 子类都必须实现它。
   * 它负责与特定的 LLM API 进行通信。
   * @param model 模型名称
   * @param messages 对话历史
   * @param signal 用于在超时或外部取消时中止 fetch 请求
   */
  protected abstract _generateChatStream(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal,
    tools?: McpToolSchema[]
  ): Promise<ReadableStream<string> | LlmProviderResponse>;

  /**
   * 非流式聊天方法。
   * 内置超时逻辑。
   * @returns 返回一个包含完整回复内容的字符串
   */
  public async chatNonStreaming(model: string, messages: ChatMessage[]): Promise<string> {
    if (messages.length === 0) {
      throw new Error("传入的消息不能为空.");
    }

    const MAX_TOOL_CALLS = 5; // 设置最大工具调用次数以防止无限循环
    let toolCallCount = 0;
    // 创建一个可变的消息历史副本，用于在循环中追加消息
    const currentMessages: ChatMessage[] = [...messages];

    while (toolCallCount < MAX_TOOL_CALLS) {
      // 1. 如果配置了 mcp，则获取工具列表
      let tools: McpToolSchema[] | undefined;
      if (this.config.mcpServerUrl) {
        try {
          console.log(`[BaseProvider] MCP server URL found: ${this.config.mcpServerUrl}. Fetching tools...`);
          const toolClient = getToolClientInstance(this.config.mcpServerUrl);
          tools = await toolClient.getToolsSchema();
        } catch (error) {
          console.error("[BaseProvider] Failed to get tools schema, proceeding without tools.", error);
        }
      }

      // 2. 超时判断
      const controller = new AbortController();
      const timeoutMs = this.config.timeoutMs || 60000;
      let timeoutId: NodeJS.Timeout | null = null;
      const timeoutPromise = new Promise<never>((_, reject) => {
        timeoutId = setTimeout(() => {
          controller.abort();
          reject(new Error(`Request timed out after ${timeoutMs / 1000} seconds.`));
        }, timeoutMs);
      });

       // 3. 检查 LLM 的响应中是否包含工具调用请求
      const llmResponsePromise = this._generateChatNonStreaming(model, currentMessages, controller.signal, tools);
      const llmResponse = await Promise.race([llmResponsePromise, timeoutPromise]);
      const toolCalls = llmResponse.tool_calls;
      if (!toolCalls || toolCalls.length === 0) {
        // 如果没有工具调用，说明我们得到了最终答案，直接返回
        return llmResponse.content || "";
      }
      console.log(`非流式输出本次需要调用的工具数量 ${toolCalls.length} 个.`);

      // 将 assistant 的工具调用请求本身也加入到消息历史中
      currentMessages.push({
        role: 'assistant',
        content: llmResponse.content, // content 可能是 null
        tool_calls: llmResponse.tool_calls,
      });

      // 4. 执行所有请求的工具调用
      const toolClient = getToolClientInstance(this.config.mcpServerUrl!);
      const toolResultPromises = toolCalls.map(async (toolCall) => {
        const { name, arguments: args } = toolCall.function;
        try {
          console.log(`执行工具: ${name} 参数列表: ${args}`);
          const result = await toolClient.callTool(name, JSON.parse(args))
          // 5. 将每个工具的执行结果包装成一条 'tool' 消息
          return {
            role: 'tool' as const,
            tool_call_id: toolCall.id,
            content: typeof result === 'string' ? result : JSON.stringify(result),
          };
        } catch (error: any) {
          console.error(`执行 ${name} 工具错误:`, error);
          return { // 如果工具执行失败，也返回一条错误信息
            role: 'tool' as const,
            tool_call_id: toolCall.id,
            content: `Error: ${error.message}`,
          };
        }
      });

      // 6. 并行执行所有工具调用，并将结果追加到消息历史
      const toolResults = await Promise.all(toolResultPromises);
      currentMessages.push(...toolResults);

      toolCallCount++;
      // 循环继续，携带更新后的消息历史再次调用 LLM
      console.error(`工具循环调用次数: ${toolCallCount}`);
    }
    // 7. 如果循环结束（达到最大调用次数），则抛出错误
    throw new Error("已经达到单次对话工具最大调用次数限制.");
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