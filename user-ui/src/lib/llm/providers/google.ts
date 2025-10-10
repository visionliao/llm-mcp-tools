import { GoogleGenerativeAI, Content, GenerationConfig, SingleRequestOptions } from "@google/generative-ai";
import { BaseChatProvider } from "../base-provider";
import { ChatMessage } from "../types";

export class GoogleChatProvider extends BaseChatProvider {
  /**
   * 将通用消息格式转换为 Google API 的特定格式。
   * @param messages 通用消息数组
   * @returns Google API 格式的 Content 数组
   */
  private mapMessagesToGoogleFormat(messages: ChatMessage[]): Content[] {
    // Google API 不支持 'system' 角色，这里我们将其过滤掉。
    // 在更复杂的场景中，可以考虑将其内容附加到第一条用户消息前。
    return messages
      .filter(msg => msg.role !== 'system')
      .map(msg => ({
        role: msg.role === 'assistant' ? 'model' : 'user', // Google 使用 'model' 代表 'assistant'
        parts: [{ text: msg.content }],
      }));
  }

  protected async _generateChatStream(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal
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


    // 初始化模型，配置温度、topP、topK、maxOutputTokens等
    const generativeModel = genAI.getGenerativeModel({ 
      model,
      generationConfig,
    });

    // 格式化消息
    const formattedMessages = this.mapMessagesToGoogleFormat(messages);

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
}