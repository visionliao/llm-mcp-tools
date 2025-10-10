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
  public async chatStreaming(model: string, messages: ChatMessage[]): Promise<ReadableStream<string>> {
    if (messages.length === 0) {
      throw new Error("Message history cannot be empty.");
    }

    const controller = new AbortController();
    // 从实例自身的配置中获取最终确定的超时时间
    const timeoutMs = this.config.timeoutMs || 60000;
    let timeoutId: NodeJS.Timeout | null = null;

    try {
      // 创建实际的聊天请求 Promise，并将 AbortSignal 传递下去
      const chatPromise = this._generateChatStream(model, messages, controller.signal);

      // 创建一个与聊天请求并行的“定时炸弹” Promise
      const timeoutPromise = new Promise<never>((_, reject) => {
        timeoutId = setTimeout(() => {
          controller.abort(); // 超时后，中止请求
          reject(new Error(`Request timed out after ${timeoutMs / 1000} seconds.`));
        }, timeoutMs);
      });

      // Promise.race 会返回最先完成的那个 Promise 的结果
      const stream = await Promise.race([chatPromise, timeoutPromise]);
      return stream;
    } finally {
      // 无论成功、失败还是超时，都必须清除定时器以防内存泄漏
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    }
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
    signal: AbortSignal
  ): Promise<ReadableStream<string>>;

  /**
   * 非流式聊天方法。
   * 内置超时逻辑。
   * @returns 返回一个包含完整回复内容的字符串
   */
  public async chatNonStreaming(model: string, messages: ChatMessage[]): Promise<string> {
    if (messages.length === 0) {
      throw new Error("Message history cannot be empty.");
    }

    const controller = new AbortController();
    const timeoutMs = this.config.timeoutMs || 60000;
    let timeoutId: NodeJS.Timeout | null = null;

    try {
      const chatPromise = this._generateChatNonStreaming(model, messages, controller.signal);

      const timeoutPromise = new Promise<never>((_, reject) => {
        timeoutId = setTimeout(() => {
          controller.abort();
          reject(new Error(`Request timed out after ${timeoutMs / 1000} seconds.`));
        }, timeoutMs);
      });
      
      const result = await Promise.race([chatPromise, timeoutPromise]);
      return result;

    } finally {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    }
  }

  /**
   * 抽象方法，子类必须实现它以支持非流式调用。
   */
  protected abstract _generateChatNonStreaming(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal
  ): Promise<string>;
}