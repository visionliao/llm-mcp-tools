import { GoogleGenerativeAI, Content } from "@google/generative-ai";
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
    messages: ChatMessage[]
  ): Promise<ReadableStream<string>> {
    // 使用从基类继承的配置初始化 SDK
    const genAI = new GoogleGenerativeAI(this.config.apiKey);
    const generativeModel = genAI.getGenerativeModel({ model });

    // 格式化消息
    const formattedMessages = this.mapMessagesToGoogleFormat(messages);

    try {
      const result = await generativeModel.generateContentStream({
        contents: formattedMessages,
      });

      // 将 Google SDK 的流转换为标准的 Web ReadableStream
      const stream = new ReadableStream<string>({
        async start(controller) {
          for await (const chunk of result.stream) {
            const text = chunk.text();
            if (text) {
              controller.enqueue(text); // 将每个文本块放入流中
            }
          }
          controller.close(); // 所有块发送完毕，关闭流
        },
      });

      return stream;
    } catch (error: any) {
      console.error("Google Gemini API Error:", error.message);
      // 抛出更具体的错误信息
      throw new Error(`Failed to get response from Google Gemini: ${error.message}`);
    }
  }
}