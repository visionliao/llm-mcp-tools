// lib/llm/providers/google.ts

import { GoogleGenerativeAI, Content, GenerationConfig, SingleRequestOptions, FunctionDeclaration, Part } from "@google/generative-ai";
import { BaseChatProvider } from "../base-provider";
import { ChatMessage, ToolCall, LlmProviderResponse } from "../types";
import { McpToolSchema } from "../tools/tool-client";

export class GoogleChatProvider extends BaseChatProvider {
  /**
   * 将通用消息格式转换为 Google API 的特定格式。
   * @param messages 通用消息数组
   * @returns Google API 格式的 Content 数组
   */
  private mapMessagesToGoogleFormat(messages: ChatMessage[]): Content[] {
    // 用于在处理 tool 消息时查找其对应的 function name
    const toolCallIdToFunctionNameMap = new Map<string, string>();

    return messages
      .filter(msg => msg.role !== 'system') // 过滤掉 system 消息
      .map(msg => {
        switch (msg.role) {
          case 'user':
            return {
              role: 'user',
              parts: [{ text: msg.content ?? '' }],
            };

          case 'assistant':
            const assistantParts: Part[] = [];
            // 如果助手消息有文本内容，则添加 text part
            if (msg.content) {
              assistantParts.push({ text: msg.content });
            }
            // 如果助手消息有工具调用请求，则添加 functionCall part
            if (msg.tool_calls) {
              for (const toolCall of msg.tool_calls) {
                // 缓存 tool_call_id 和 function name 的映射关系
                toolCallIdToFunctionNameMap.set(toolCall.id, toolCall.function.name);
                assistantParts.push({
                  functionCall: {
                    name: toolCall.function.name,
                    args: JSON.parse(toolCall.function.arguments),
                  },
                });
              }
            }
            return { role: 'model', parts: assistantParts };

          case 'tool':
            // Google API 要求 tool 角色被称为 'function'
            // 从缓存中找到这个 tool call 对应的函数名
            const functionName = toolCallIdToFunctionNameMap.get(msg.tool_call_id!);
            if (!functionName) {
              // 如果找不到函数名，这通常是一个逻辑错误，但我们可以先跳过此消息
              console.warn(`Could not find function name for tool_call_id: ${msg.tool_call_id}`);
              return null; // 返回 null，之后会被过滤掉
            }
            return {
              role: 'function',
              parts: [
                {
                  functionResponse: {
                    name: functionName,
                    // Google 期望 response 是一个对象，而不是字符串
                    response: { result: msg.content },
                  },
                },
              ],
            };

          default:
            return null; // 理论上不会发生
        }
      })
      .filter((msg): msg is Content => msg !== null); // 过滤掉所有 null 的结果
  }

  // 流式输出
  protected async _generateChatStream(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal,
    tools?: McpToolSchema[]
  ): Promise<ReadableStream<string> | LlmProviderResponse> {
    // 使用从基类继承的配置初始化 SDK
    const genAI = new GoogleGenerativeAI(this.config.apiKey);
    // 从 this.config 中提取并适配 Google SDK 的参数
    const generationConfig: GenerationConfig = {};
    if (this.config.maxOutputTokens !== undefined) generationConfig.maxOutputTokens = this.config.maxOutputTokens;
    if (this.config.temperature !== undefined) generationConfig.temperature = this.config.temperature;
    if (this.config.topP !== undefined) generationConfig.topP = this.config.topP;
    // gemini-2.5-xxx 不支持这两个参数
    // if (this.config.presencePenalty !== undefined) generationConfig.presencePenalty = this.config.presencePenalty;
    // if (this.config.frequencyPenalty !== undefined) generationConfig.frequencyPenalty = this.config.frequencyPenalty;

    // 格式化工具以适配 Google API
    // Google API 需要一个 Tool 数组，每个 Tool 包含一个 functionDeclarations 数组
    const googleTools = tools?.map(tool => tool.function as FunctionDeclaration);

    // 初始化模型，配置温度、topP、topK、maxOutputTokens等
    const generativeModel = genAI.getGenerativeModel({ 
      model,
      generationConfig,
      tools: googleTools ? [{ functionDeclarations: googleTools }] : undefined,
      systemInstruction: this.config.systemPrompt || undefined,
    });

    // 格式化消息
    const formattedMessages = this.mapMessagesToGoogleFormat(messages);

    console.log('\n--- [LLM Request Log - Streaming] ---');
    console.log(`Timestamp: ${new Date().toISOString()}`);
    console.log('Provider: Google');
    console.log('Model:', model);
    console.log('系统提示词:', this.config.systemPrompt);
    console.log('参数配置信息:', JSON.stringify(generationConfig, null, 2));
    if (googleTools) console.log('可用工具数量: ', googleTools.length);
    console.log('Final Messages Payload:', JSON.stringify(formattedMessages, null, 2));
    console.log('-------------------------------------\n');

    // 使用 Promise 来等待流的第一个有效块，并据此决定返回什么
    // 对于google大模型，如果是工具调用信息，会一次性返回所有内容，只有最终的回复才会通过流式块的打字机效果一点点蹦出来结果
    return new Promise(async (resolve, reject) => {
      try {
        // 1. 设定超时参数构造，每次对话请求时的配置
        const requestOptions: SingleRequestOptions = {
          signal: signal,
          timeout: this.config.timeoutMs,
        };

        // 2. 调用google的流逝输出接口
        const result = await generativeModel.generateContentStream(
          { contents: formattedMessages },
          requestOptions
        );

        // 3. 获取流的异步迭代器，以便可以获取第一个流块
        const streamIterator = result.stream[Symbol.asyncIterator]();
        const firstChunkResult = await streamIterator.next();

        // 如果流一开始就是空的，直接返回一个空的流
        if (firstChunkResult.done) {
          resolve(new ReadableStream({ start(controller) { controller.close(); } }));
          return;
        }

        // 获取第一个流块
        const firstChunk = firstChunkResult.value;
        const functionCalls = firstChunk.functionCalls();

        // 4. 检查第一个有数据的块是否是工具调用信息
        if (functionCalls && functionCalls.length > 0) {
          // 是工具调用
          console.log('google大模型返回工具调用消息:', JSON.stringify(functionCalls, null, 2));

          // 5. 工具格式转换
          const toolCalls: ToolCall[] = functionCalls.map((fc, index) => ({
            id: `${fc.name}_${Date.now()}_${index}`,
            type: 'function',
            function: {
              name: fc.name,
              arguments: JSON.stringify(fc.args)
            },
          }));

          // 6. 通过 Promise 的 resolve 返回工具调用的结构化数据
          resolve({
            content: firstChunk.text() || null,
            tool_calls: toolCalls,
          });
        } else {
          // 普通文本流，表示没有工具调用，或者工具调用完毕这是大模型最终的回复
          console.log('流式输出第一个数据块是文本，将返回 ReadableStream');

          // 7. 将 Google SDK 的流转换为标准的 Web ReadableStream
          resolve(new ReadableStream<string>({
            async start(controller) {
              const firstText = firstChunk.text();
              if (firstText) {
                console.log('google大模型返回文本流:', firstText);
                controller.enqueue(firstText);
              }
              while (true) {
                const nextChunkResult = await streamIterator.next();
                if (nextChunkResult.done) break;
                const nextText = nextChunkResult.value.text();
                if (nextText) {
                  console.log('google大模型返回文本流:', nextText);
                  controller.enqueue(nextText);
                }
              }
              controller.close();
            },
          }));
        }
      } catch (error: any) {
        if (error.name === 'AbortError' || (error.cause && error.cause.name === 'TimeoutError')) {
          console.error("Google Gemini API request was aborted due to timeout.", { model });
          // 从基类中获取超时信息，使错误消息更准确
          const timeoutSeconds = (this.config.timeoutMs || 60000) / 1000;
          throw new Error(`Request to Google Gemini timed out after ${timeoutSeconds} seconds.`);
        }
        console.error("Google Gemini API Error:", error.message);
        throw new Error(`Failed to get response from Google Gemini: ${error.message}`);
      }
    });
  }

  // 非流式输出
  protected async _generateChatNonStreaming(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal,
    tools?: McpToolSchema[]
  ): Promise<LlmProviderResponse> {
    const genAI = new GoogleGenerativeAI(this.config.apiKey);
    // 从 this.config 中提取并适配 Google SDK 的参数
    const generationConfig: GenerationConfig = {};
    if (this.config.maxOutputTokens !== undefined) generationConfig.maxOutputTokens = this.config.maxOutputTokens;
    if (this.config.temperature !== undefined) generationConfig.temperature = this.config.temperature;
    if (this.config.topP !== undefined) generationConfig.topP = this.config.topP;
    // gemini-2.5-xxx 不支持这两个参数
    // if (this.config.presencePenalty !== undefined) generationConfig.presencePenalty = this.config.presencePenalty;
    // if (this.config.frequencyPenalty !== undefined) generationConfig.frequencyPenalty = this.config.frequencyPenalty;

    // 格式化工具以适配 Google API
    // Google API 需要一个 Tool 数组，每个 Tool 包含一个 functionDeclarations 数组
    const googleTools = tools?.map(tool => tool.function as FunctionDeclaration);

    const generativeModel = genAI.getGenerativeModel({ 
      model,
      generationConfig,
      tools: googleTools ? [{ functionDeclarations: googleTools }] : undefined,
      systemInstruction: this.config.systemPrompt || undefined,
    });
    
    const formattedMessages = this.mapMessagesToGoogleFormat(messages);
    console.log('\n--- [大模型请求日志 - 非流式输出] ---');
    console.log(`Timestamp: ${new Date().toISOString()}`);
    console.log('Provider: Google');
    console.log('Model:', model);
    console.log('系统提示词:', this.config.systemPrompt);
    console.log('参数配置信息:', JSON.stringify(generationConfig, null, 2));
    if (googleTools) console.log('可用工具数量: ', googleTools.length);
    console.log('单次对话工具调用记录:', JSON.stringify(formattedMessages, null, 2));
    console.log('-------------------------------------\n');

    try {
      const requestOptions: SingleRequestOptions = {
        signal,
        timeout: this.config.timeoutMs,
      };

      // 调用 SDK 的非流式 API: generateContent
      const result = await generativeModel.generateContent(
        { contents: formattedMessages },
        requestOptions
      );

      const response = result.response;
      console.log('google大模型响应非流式输出:', JSON.stringify(response, null, 2));
      // 从 Google 的响应中安全地提取文本内容和工具调用
      const candidates = response.candidates;
      if (!candidates || candidates.length === 0) {
        throw new Error("Invalid response structure from Google Gemini: no candidates.");
      }
      const contentParts = candidates[0].content?.parts || [];
      const textContent = contentParts.find(part => part.text)?.text ?? null;

      const toolCalls: ToolCall[] = contentParts
        .filter(part => part.functionCall)
        .map((part, index) => {
          // Google API 不直接提供唯一ID，我们手动创建一个
          const toolCallId = `tool_call_${Date.now()}_${index}`;
          return {
            id: toolCallId,
            type: 'function',
            function: {
              name: part.functionCall!.name,
              arguments: JSON.stringify(part.functionCall!.args),
            },
          };
        });

      return {
        content: textContent,
        tool_calls: toolCalls.length > 0 ? toolCalls : undefined,
      };
    } catch (error: any) {
      if (error.name === 'AbortError' || (error.cause && error.cause.name === 'TimeoutError')) {
        console.error("Google Gemini API request was aborted due to timeout.", { model });
        // 从基类中获取超时信息，使错误消息更准确
        const timeoutSeconds = (this.config.timeoutMs || 60000) / 1000;
        throw new Error(`Request to Google Gemini timed out after ${timeoutSeconds} seconds.`);
      }
      console.error("Google Gemini API Error:", error.message);
      throw new Error(`Failed to get response from Google Gemini: ${error.message}`);
    }
  }
}