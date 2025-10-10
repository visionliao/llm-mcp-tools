/**
 * 通用的消息结构，支持 user, assistant, 和 system 角色
 */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

/**
 * @description 所有模型在生成内容时可以接受的、通用的运行时选项。
 * 所有属性都设为可选，以便调用者可以只提供他们想覆盖的参数。
 */
export interface LlmGenerationOptions {
  stream?: boolean;  // 启用流式输出
  timeoutMs?: number;  // 大模型回复超时时间，默认60s
  maxOutputTokens?: number; // 单次回复限制 ，默认8192，范围0-32000
  temperature?: number; // 创意活跃度 ，temperature  默认1.0，范围0-2.0
  topP?: number;  // 思维开放度  top_p ，默认1.0，范围0-1.0,考虑多少种可能性，值越大，接受更多可能的回答；值越小，倾向选择最可能的回答。不推荐和创意活跃度一起更改
  presencePenalty?: number;  // 表述发散度,默认0，范围-2.0-2.0,值越大，越倾向不同的表达方式，避免概念重复；值越小，越倾向使用重复的概念或叙述，表达更具一致性
  frequencyPenalty?: number; // 词汇丰富度,默认0，范围-2.0-2.0,值越大，用词越丰富多样；值越低，用词更朴实简单
  mcpServerUrl?: string; // mcp服务器地址
}

/**
 * 所有 Provider 构造函数都接受的基础配置对象
 */
export interface BaseProviderConfig extends LlmGenerationOptions {
  apiKey: string;
  proxyUrl?: string;
}