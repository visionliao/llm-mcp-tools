/**
 * 通用的消息结构，支持 user, assistant, 和 system 角色
 */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

/**
 * 所有 Provider 构造函数都接受的基础配置对象
 */
export interface BaseProviderConfig {
  apiKey: string;
  proxyUrl?: string;
}