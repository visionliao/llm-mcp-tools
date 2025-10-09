// 通用大模型调用接口
export interface LLMModel {
  provider: string;
  model: string;
  apiKey: string;
  proxyUrl?: string;
}

// 聊天消息接口
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

// 模型调用请求
export interface ModelRequest {
  messages: ChatMessage[];
  temperature?: number;
  maxTokens?: number;
  stream?: boolean;
}

// 模型调用响应
export interface ModelResponse {
  content: string;
  role: 'assistant';
  usage?: {
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
  };
  model: string;
}

// 模型调用接口
export interface ModelClient {
  name: string;
  supportedModels: string[];
  
  /**
   * 调用模型
   */
  chat(request: ModelRequest): Promise<ModelResponse>;
  
  /**
   * 流式调用模型
   */
  chatStream(request: ModelRequest): Promise<AsyncIterable<string>>;
}

// 模型配置接口
export interface ModelConfig {
  provider: string;
  apiKey: string;
  models: string[];
  proxyUrl?: string;
}

// 错误类型
export class ModelError extends Error {
  constructor(
    message: string,
    public provider: string,
    public model: string,
    public statusCode?: number
  ) {
    super(message);
    this.name = 'ModelError';
  }
}