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
  ): Promise<ReadableStream<string>> {
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
    });

    // 格式化消息
    const formattedMessages = this.mapMessagesToGoogleFormat(messages);

    console.log('\n--- [LLM Request Log - Streaming] ---');
    console.log(`Timestamp: ${new Date().toISOString()}`);
    console.log('Provider: Google');
    console.log('Model:', model);
    console.log('Final Generation Config:', JSON.stringify(generationConfig, null, 2));
    if (googleTools) console.log('Final Tools: ', googleTools.length);
    console.log('Final Messages Payload:', JSON.stringify(formattedMessages, null, 2));
    console.log('-------------------------------------\n');

    try {
      // 超时机制参数构造，每次对话请求时的配置
      const requestOptions: SingleRequestOptions = {
        signal: signal,
        timeout: this.config.timeoutMs,
      };

      const result = await generativeModel.generateContentStream(
        { contents: formattedMessages },
        requestOptions
      );

      // 将 Google SDK 的流转换为标准的 Web ReadableStream
      const stream = new ReadableStream<string>({
        async start(controller) {
          console.log("--- [Backend] Stream from Google Started ---"); // <-- 添加开始日志
          for await (const chunk of result.stream) {
            const text = chunk.text();
            console.log(`[Backend Chunk]: "${text}"`);
            if (text) {
              controller.enqueue(text); // 将每个文本块放入流中
            }
          }
          console.log("--- [Backend] Stream from Google Ended ---"); // <-- 添加结束日志
          controller.close(); // 所有块发送完毕，关闭流
        },
      });

      return stream;
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
    });
    
    const formattedMessages = this.mapMessagesToGoogleFormat(messages);
    console.log('\n--- [大模型请求日志 - 非流式输出] ---');
    console.log(`Timestamp: ${new Date().toISOString()}`);
    console.log('Provider: Google');
    console.log('Model:', model);
    console.log('Final Generation Config:', JSON.stringify(generationConfig, null, 2));
    if (googleTools) console.log('Final Tools: ', googleTools.length);
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