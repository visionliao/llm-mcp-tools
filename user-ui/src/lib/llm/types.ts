// lib/llm/types.ts

/**
 * 代表一个由 assistant 发起的工具调用请求。
 */
export interface ToolCall {
  id: string; // 该工具调用的唯一 ID
  type: 'function';
  function: {
    name: string;
    arguments: string; // 参数通常是一个 JSON 字符串
  };
}

/**
 * 定义 Token 使用情况的结构
 */
export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}


// 定义从 Provider 返回的复杂响应结构，可能是字符串，可能是工具调用信息
export interface LlmProviderResponse {
  content: string | null;
  tool_calls?: ToolCall[];
  usage?: TokenUsage;
}

/**
 * 为非流式响应定义的标准返回接口。
 * 这个结构同时携带最终的聊天内容和完整的 Token 消耗统计。
 */
export interface NonStreamingResult {
  content: string;
  usage: TokenUsage;
}

/**
 * 为流式响应定义的标准容器接口。
 * 这个结构同时传递大模型回复的数据流和在流结束后才能获取的token消耗信息。
 */
export interface StreamingResult {
  /**
   * 大模型返回的最终结果
   */
  stream: ReadableStream<string>;
  /**
   * 一个在流完全结束后才会兑现的 Promise。
   * 本次对话所消耗的 Token 总量(包含工具调用等)。
   */
  finalUsagePromise: Promise<TokenUsage | undefined>;
}

/**
 * 通用的消息结构，支持 user, assistant, 和 system 角色
 */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string | null; // 如果 assistant 消息只包含工具调用，内容可能为 null
  tool_calls?: ToolCall[]; // 用于 assistant 消息，存放一个或多个工具调用请求
  tool_call_id?: string;   // 用于 tool 消息，关联它所响应的那个 tool_call 请求
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
  systemPrompt?: string; // 系统提示词
  maxToolCalls?: number; // 最大工具调用次数
}

/**
 * 所有 Provider 构造函数都接受的基础配置对象
 */
export interface BaseProviderConfig extends LlmGenerationOptions {
  apiKey: string;
  proxyUrl?: string;
}

/**
 * 定义在流中传输的数据块的结构。
 * 为了将token统计数据也发送到前端，在同一个流中混合发送文本内容和结构化的token消耗元数据。
 */
export type StreamChunk = {
  type: 'text';
  payload: string; // 聊天文本内容
} | {
  type: 'usage';
  payload: TokenUsage; // Token 用量数据
};