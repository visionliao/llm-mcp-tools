import { ChatMessage, BaseProviderConfig } from './types';

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
  public chat(model: string, messages: ChatMessage[]): Promise<ReadableStream<string>> {
    if (messages.length === 0) {
      throw new Error("Message history cannot be empty.");
    }
    return this._generateChatStream(model, messages);
  }

  /**
   * 核心抽象方法，子类必须实现此方法以适配特定的 LLM API。
   * @param model 模型名称
   * @param messages 对话历史
   */
  protected abstract _generateChatStream(
    model: string,
    messages: ChatMessage[]
  ): Promise<ReadableStream<string>>;
}