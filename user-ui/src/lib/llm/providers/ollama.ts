import { Ollama } from 'ollama';
import { BaseChatProvider } from '../base-provider';
import { BaseProviderConfig, ChatMessage, LlmGenerationOptions } from '../types';

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

  protected async _generateChatStream(
    model: string,
    messages: ChatMessage[],
    signal: AbortSignal
  ): Promise<ReadableStream<string>> {
    const options = this.buildOllamaOptions();

    // --- 日志记录 ---
    console.log('\n--- [LLM Request Log - Streaming] ---');
    console.log(`Timestamp: ${new Date().toISOString()}`);
    console.log('Provider: Ollama');
    console.log('Model:', model);
    console.log('Final Generation Options:', JSON.stringify(options, null, 2));
    console.log('Final Messages Payload:', JSON.stringify(messages, null, 2));
    console.log('-------------------------------------\n');

    try {
      const response = await this.ollama.chat({
        model: model,
        messages: messages,
        stream: true,
        options: options,
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
            if (part.message.content) {
              controller.enqueue(part.message.content);
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
    signal: AbortSignal
  ): Promise<string> {
    const options = this.buildOllamaOptions();
    
    // --- 日志记录 ---
    console.log('\n--- [LLM Request Log - Non-Streaming] ---');
    console.log(`Timestamp: ${new Date().toISOString()}`);
    console.log('Provider: Ollama');
    console.log('Model:', model);
    console.log('Final Generation Options:', JSON.stringify(options, null, 2));
    console.log('Final Messages Payload:', JSON.stringify(messages, null, 2));
    console.log('-----------------------------------------\n');

    try {
      // 非流式调用，但我们可以通过 AbortSignal 和超时来控制
      // Ollama 库的 fetch 调用会继承我们设置的全局 dispatcher
      const response = await this.ollama.chat({
        model: model,
        messages: messages,
        stream: false,
        options: options,
      });

      return response.message.content;
    } catch (error: any) {
      if (error.name === 'AbortError') {
        throw new Error(`Request to Ollama timed out.`);
      }
      console.error("Ollama API Error (Non-Streaming):", error.message);
      throw new Error(`Failed to get non-streaming response from Ollama: ${error.message}`);
    }
  }
}