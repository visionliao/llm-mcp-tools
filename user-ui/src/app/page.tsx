"use client";

import { useState, useEffect, useRef } from "react";
import { LlmGenerationOptions, TokenUsage, StreamChunk, DurationUsage } from "@/lib/llm/types";

// 定义与后端 lib/llm/types.ts 匹配的类型
interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  duration?: DurationUsage;
  overhead_ms?: number; // 传输耗时
}

interface ModelOption {
  value: string;
  label: string;
  provider: string;
}

export default function Home() {
  const [message, setMessage] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  // 主对话历史
  const [conversation, setConversation] = useState<ChatMessage[]>([]);
  // 专门用于接收当前流式响应的 state
  const [streamingResponse, setStreamingResponse] = useState("");
  const chatContainerRef = useRef<HTMLDivElement>(null);
  // 公共参数添加 state
  const [isStreamingEnabled, setIsStreamingEnabled] = useState(true);
  const [temperature, setTemperature] = useState(1.0);
  const [topP, setTopP] = useState(1.0);
  const [presencePenalty, setPresencePenalty] = useState(0);
  const [frequencyPenalty, setFrequencyPenalty] = useState(0);
  const [maxOutputTokens, setMaxOutputTokens] = useState(8192);
  // 控制历史记录长度
  const [historyLength, setHistoryLength] = useState(4); // 默认保留最近4条消息
  // MCP 相关 state
  const [mcpServerUrl, setMcpServerUrl] = useState("http://127.0.0.1:8001");
  const [mcpStatus, setMcpStatus] = useState<'unchecked' | 'ok' | 'error' | 'testing'>('unchecked');
  // System Prompt
  const [systemPrompt, setSystemPrompt] = useState(
`You are a helpful assistant with access to external tools.
Your primary goal is to answer the user's questions using these tools.

CRITICAL RULES:
1. DO NOT write or execute any code (Python, JavaScript, etc.).
2. To use a tool, you MUST output a standard JSON Function Call.
3. If a task requires multiple steps, break it down. Call the first tool, wait for the result, then call the next tool.
4. Only use the tools that have been provided to you.`
  );
  // 工具调用最大循环次数
  const [maxToolCalls, setMaxToolCalls] = useState(5); // 默认5次
  // 用于控制高级设置面板的展开和收起
  const [isSettingsExpanded, setIsSettingsExpanded] = useState(false); // 默认不展开
  // 用于显示【单条】消息的 Token 消耗
  const [currentMessageUsage, setCurrentMessageUsage] = useState<TokenUsage | null>(null);
  // 用于累加并显示【当前页面会话】的总 Token 消耗
  const [totalSessionTokens, setTotalSessionTokens] = useState(0);
  // 用于显示【单条】消息LLM耗时的 State
  const [currentMessageDuration, setCurrentMessageDuration] = useState<DurationUsage | null>(null);
  // 用于存储和显示单条消息数据传输开销耗时
  const [currentMessageOverhead, setCurrentMessageOverhead] = useState<number | null>(null);

  // 连接测试处理函数
  const handleConnectivityTest = async () => {
    if (!mcpServerUrl.trim()) {
      alert("请输入 MCP 服务器地址");
      return;
    }
    setMcpStatus('testing');
    try {
      const response = await fetch('/api/mcp-test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: mcpServerUrl }),
      });
      if (!response.ok) {
        // 如果服务器返回了错误状态码（如 404, 500）
        // 我们尝试解析错误信息，如果没有，就用状态码作为错误
        const errorData = await response.json().catch(() => null); // 尝试解析json，失败则返回null
        throw new Error(errorData?.error || `服务器返回错误: ${response.status}`);
      }
      const data = await response.json();
      if (response.ok && data.status === 'ok') {
        setMcpStatus('ok');
        console.log("MCP Server Test successful:", data);
      } else {
        throw new Error(data.error || '连接测试失败');
      }
    } catch (error: any) {
      console.error("MCP Server Test failed:", error.message);
      setMcpStatus('error');
      // Network errors often don't have a specific message, so we provide a clearer one.
      if (error.message.includes('fetch failed')) {
        alert(`连接失败: 无法访问地址 ${mcpServerUrl}。请检查地址是否正确，以及 MCP 服务是否正在运行。`);
      } else {
        alert(`连接失败: ${error.message}`);
      }
    }
  };

  // 自动滚动到聊天记录底部
  useEffect(() => {
    chatContainerRef.current?.scrollTo({ top: chatContainerRef.current.scrollHeight, behavior: 'smooth' });
  }, [conversation, streamingResponse]);

  // 组件加载时获取可用模型
  useEffect(() => {
    const loadModelOptions = async () => {
      try {
        const response = await fetch('/api/model-list?type=options');
        if (!response.ok) throw new Error('Failed to fetch model options');
        const options = await response.json();
        setModelOptions(options);
        
        // 如果有模型，默认选择gemini-2.5-flash
        if (options.length > 0) {
          setSelectedModel(options[2].value);
        }
      } catch (error) {
        console.error('获取模型选项失败:', error);
      }
    };
    
    loadModelOptions();
  }, []);

  const handleSendMessage = async () => {
    if (!message.trim() || !selectedModel) {
      alert("请输入消息并选择模型");
      return;
    }
    // 在发送消息时记录起始时间戳
    const startTime = Date.now(); // 记录发送时刻 (毫秒)

    setIsLoading(true);
    // 在每次发送新消息时，重置上一条消息的 Token 显示 和 耗时统计
    setCurrentMessageUsage(null);
    setCurrentMessageDuration(null);
    setCurrentMessageOverhead(null);
    const userMessage: ChatMessage = { role: 'user', content: message };
    // 从完整的对话历史中，只截取用户指定的最后几条，如果为0则将历史消息变为空
    const messagesForApi = historyLength > 0 ? conversation.slice(-historyLength) : [];
    // 将新消息和截取后的历史合并，作为最终发送的 payload
    const messagesPayload = [...messagesForApi, userMessage];
    // 更新UI时，依然使用完整的对话历史
    setConversation(prev => [...prev, userMessage]);
    // 清空输入框并重置流式响应状态
    setMessage("");
    setStreamingResponse("");

    const generationOptions: LlmGenerationOptions = {
      stream: isStreamingEnabled,
      temperature,
      topP,
      presencePenalty,
      frequencyPenalty,
      maxOutputTokens,
      mcpServerUrl: mcpServerUrl,
      systemPrompt: systemPrompt,
      maxToolCalls: maxToolCalls,
    };
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          selectedModel,
          messages: messagesPayload, // 发送包含最新用户消息的完整历史
          options: generationOptions, // 发送模型参数
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || '服务器响应错误');
      }

      // 根据开关状态，决定如何处理响应
      if (isStreamingEnabled) {
        // 处理流式响应
        if (!response.body) throw new Error("Streaming response has no body");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let completeResponse = "";
        let finalDuration: DurationUsage | null = null;

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          // SSE 消息以 "data: " 开头，并以 "\n\n" 结尾，我们按这个格式解析
          const lines = chunk.split('\n\n').filter(line => line.trim().startsWith('data:'));
          for (const line of lines) {
            const jsonString = line.replace('data: ', '');
            try {
              const parsedChunk: StreamChunk = JSON.parse(jsonString);
              // 根据数据块的类型，更新不同的 state
              if (parsedChunk.type === 'text') {
                const textPayload = parsedChunk.payload;
                completeResponse += textPayload;
                // 更新正在流式显示的回复
                setStreamingResponse(prev => prev + textPayload);
              } else if (parsedChunk.type === 'usage') {
                const usagePayload = parsedChunk.payload;
                console.log("从 SSE 流接收到 Token 数据:", usagePayload);
                // 更新单条消息的 Token 显示
                setCurrentMessageUsage(usagePayload);
                // 累加到会话总 Token
                setTotalSessionTokens(prev => prev + usagePayload.total_tokens);
              } else if (parsedChunk.type === 'duration') { // 处理耗时数据块
                const durationPayload = parsedChunk.payload;
                console.log("从 SSE 流接收到 Duration 数据:", durationPayload);
                // 更新单条消息的 耗时 显示
                setCurrentMessageDuration(durationPayload);
                finalDuration = durationPayload; // 存起来，流结束后用
              }
            } catch (error) {
              console.error("解析 SSE 数据块失败:", jsonString, error);
            }
          }
        }
        // 流结束后，将完整的回复一次性加入对话历史(包含耗时信息)
        const endTime = Date.now(); // 记录接收完毕的时刻
        const totalFrontendTime = endTime - startTime; // 端到端总耗时 (ms)

        if (finalDuration) {
          const modelTimeMs = finalDuration.total_duration / 1e6; // 模型总耗时 (ms)
          const overheadMs = Math.round(totalFrontendTime - modelTimeMs);
          console.log(`总耗时: ${totalFrontendTime}ms, 模型耗时: ${modelTimeMs.toFixed(0)}ms, 开销: ${overheadMs}ms`);
          setCurrentMessageOverhead(overheadMs);

          // 将所有信息（包括开销）存入对话历史
          setConversation(prev => [...prev, {
            role: 'assistant',
            content: completeResponse,
            duration: finalDuration,
            overhead_ms: overheadMs > 0 ? overheadMs : 0 // 避免显示负数
          }]);
        } else {
          // 如果没有收到耗时信息，只保存内容
          setConversation(prev => [...prev, { role: 'assistant', content: completeResponse }]);
        }
      } else {
        // 处理非流式响应(仅需要大模型回复可用这个简单方式)
        // const data = await response.json();
        // const completeResponse = data.response;
        // setConversation(prev => [...prev, { role: 'assistant', content: completeResponse }]);

        // 非流式带token消耗统计的流程
        // 1. 解析返回的 JSON，{ content: string, usage: TokenUsage }
        const data = await response.json();

        // 在非流式响应接收后，计算并设置耗时
        const endTime = Date.now(); // 记录接收完毕的时刻
        const totalFrontendTime = endTime - startTime; // 端到端总耗时 (ms)

        let overheadMs: number | undefined = undefined;
        if (data.duration) {
          const modelTimeMs = data.duration.total_duration / 1e6; // 模型总耗时 (ms)
          overheadMs = Math.round(totalFrontendTime - modelTimeMs);
          console.log(`总耗时: ${totalFrontendTime}ms, 模型耗时: ${modelTimeMs.toFixed(0)}ms, 开销: ${overheadMs}ms`);
          setCurrentMessageOverhead(overheadMs);
        }

        // 2. 提取聊天内容并更新对话历史
        const completeResponse = data.content;
        // 将聊天内容和耗时信息一起存入对话历史
        setConversation(prev => [...prev, {
          role: 'assistant',
          content: completeResponse,
          duration: data.duration || undefined,
          overhead_ms: overheadMs !== undefined && overheadMs > 0 ? overheadMs : undefined
        }]);

        // 3. 提取token消耗并更新UI
        if (data.usage) {
          const usagePayload: TokenUsage = data.usage;
          console.log("从非流式响应接收到 Token 数据:", usagePayload);
          // 更新单条消息的 Token 显示
          setCurrentMessageUsage(usagePayload);
          // 累加到会话总 Token
          setTotalSessionTokens(prev => prev + usagePayload.total_tokens);
        }
        // 4. 提取耗时信息并更新UI
        if (data.duration) {
          const durationPayload: DurationUsage = data.duration;
          console.log("从非流式响应接收到 Duration 数据:", durationPayload);
          setCurrentMessageDuration(durationPayload);
        }
      }
    } catch (error: any) {
      console.error("发送消息失败:", error);
      // 如果出错，也将错误信息加入对话历史
      setConversation(prev => [...prev, { role: 'assistant', content: `错误: ${error.message}` }]);
    } finally {
      setIsLoading(false);
      // 流结束后清空，准备下一次接收
      setStreamingResponse(""); 
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      <header className="p-4 border-b bg-white shadow-sm">
        <h1 className="text-xl font-bold text-center text-gray-800">矩乘 AI studio</h1>
      </header>
      
      <main className="flex-grow p-4 overflow-hidden">
        <div className="max-w-4xl mx-auto h-full flex flex-col">
          <div className="mb-4">
            <label htmlFor="modelSelect" className="block text-sm font-medium text-gray-700 mb-1">
              选择大模型
            </label>
            {modelOptions.length > 0 ? (
              <select
                id="modelSelect"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                {modelOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : (
              <div className="w-full px-3 py-2 border border-gray-200 rounded-md bg-gray-100 text-gray-500">
                正在加载或没有可用的模型配置...
              </div>
            )}
          </div>

          {/* --- 创建可折叠的高级设置面板 --- */}
          <div className="mb-4 border border-gray-200 rounded-lg bg-white shadow-sm">
            {/* --- 面板标题和折叠按钮 --- */}
            <div
              className="flex justify-between items-center p-3 cursor-pointer bg-gray-50 rounded-t-lg hover:bg-gray-100"
              onClick={() => setIsSettingsExpanded(!isSettingsExpanded)}
            >
              <h3 className="font-medium text-gray-800">高级参数设置</h3>
              <span className="text-xl text-gray-500 transform transition-transform duration-300"
                style={{ transform: isSettingsExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
              >
                ▼
              </span>
            </div>

            {/* --- 可折叠的内容区域 --- */}
            <div
              className={`transition-all duration-500 ease-in-out overflow-hidden ${
                isSettingsExpanded ? 'max-h-[1000px] opacity-100' : 'max-h-0 opacity-0'
              }`}
            >
              <div className="p-4 border-t border-gray-200">
                {/* --- 系统提示词  --- */}
                <div className="mb-4">
                  <label htmlFor="systemPrompt" className="block text-sm font-medium text-gray-700 mb-1">
                    系统提示词 (System Prompt)
                  </label>
                  <textarea
                    id="systemPrompt"
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e.target.value)}
                    placeholder="输入系统提示词..."
                    rows={5}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y text-sm"
                  />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-4 mb-4 p-4 border rounded-lg bg-white text-sm">
                  {/* --- 第一行：创意活跃度 和 思维开放度 和 表述发散度 --- */}
                  <div>
                    <label htmlFor="temperature" className="flex justify-between"><span>创意活跃度 (Temperature)</span> <span>{temperature.toFixed(1)}</span></label>
                    <input type="range" id="temperature" min="0" max="2" step="0.1" value={temperature} onChange={(e) => setTemperature(parseFloat(e.target.value))}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
                  </div>
                  <div>
                    <label htmlFor="topP" className="flex justify-between"><span>思维开放度 (Top-P)</span> <span>{topP.toFixed(2)}</span></label>
                    <input type="range" id="topP" min="0" max="1" step="0.05" value={topP} onChange={(e) => setTopP(parseFloat(e.target.value))}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
                  </div>
                  <div>
                    <label htmlFor="presencePenalty" className="flex justify-between"><span>表述发散度 (Presence Penalty)</span> <span>{presencePenalty.toFixed(1)}</span></label>
                    <input type="range" id="presencePenalty" min="-2" max="1.9" step="0.1" value={presencePenalty} onChange={(e) => setPresencePenalty(parseFloat(e.target.value))}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
                  </div>
                  {/* --- 第二行：词汇丰富度 和 Max Tokens 和 历史记录条数 --- */}
                  <div>
                    <label htmlFor="frequencyPenalty" className="flex justify-between"><span>词汇丰富度 (Frequency Penalty)</span> <span>{frequencyPenalty.toFixed(1)}</span></label>
                    <input type="range" id="frequencyPenalty" min="-2" max="1.9" step="0.1" value={frequencyPenalty} onChange={(e) => setFrequencyPenalty(parseFloat(e.target.value))}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
                  </div>
                  <div>
                    <label htmlFor="maxTokens" className="flex justify-between"><span>单次回复限制 (Max Tokens)</span> <span>{maxOutputTokens}</span></label>
                    <input type="range" id="maxTokens" min="256" max="32000" step="256" value={maxOutputTokens} onChange={(e) => setMaxOutputTokens(parseInt(e.target.value, 10))}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
                  </div>
                  <div>
                    <label htmlFor="historyLength" className="flex justify-between"><span>附加历史消息条数</span> <span>{historyLength}</span></label>
                    <input type="range" id="historyLength" min="0" max="100" step="1" value={historyLength} onChange={(e) => setHistoryLength(parseInt(e.target.value, 10))}
                      className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
                  </div>
                  {/* --- 第三行：启用流式输出 和 MCP服务器地址 和最大工具调用次数限制  --- */}
                  <div className="md:col-span-3 grid grid-cols-1 md:grid-cols-3 gap-x-6 items-center">
                    {/* 第一部分: 流式开关 和 MCP 服务器地址 */}
                    <div className="md:col-span-2 flex items-center space-x-4">
                      <div className="flex items-center">
                        <input
                          type="checkbox" id="stream-toggle" checked={isStreamingEnabled}
                          onChange={(e) => setIsStreamingEnabled(e.target.checked)}
                          className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500"
                        />
                        <label htmlFor="stream-toggle" className="ml-2 font-medium text-gray-900 whitespace-nowrap">
                          启用流式输出
                        </label>
                      </div>

                      <div className="flex-grow flex items-center space-x-2">
                        <input
                          type="text"
                          value={mcpServerUrl}
                          onChange={(e) => {
                            setMcpServerUrl(e.target.value);
                            setMcpStatus('unchecked'); // 地址变化后重置状态
                          }}
                          placeholder="MCP 服务器地址"
                          className="w-full px-2 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
                        />
                        <button
                          onClick={handleConnectivityTest}
                          disabled={mcpStatus === 'testing'}
                          className={`px-3 py-1 rounded-md text-white text-xs transition-colors whitespace-nowrap ${
                            mcpStatus === 'testing' ? 'bg-gray-400' :
                            mcpStatus === 'ok' ? 'bg-green-500 hover:bg-green-600' :
                            mcpStatus === 'error' ? 'bg-red-500 hover:bg-red-600' :
                            'bg-blue-500 hover:bg-blue-600'
                          }`}
                        >
                          {mcpStatus === 'testing' ? '测试中...' : '连接测试'}
                        </button>
                      </div>
                    </div>

                    {/* 第二部分: 最大工具调用次数滑块 */}
                    <div className="mt-4 md:mt-0">
                      <label htmlFor="maxToolCount" className="flex justify-between"><span>最大工具调用次数</span> <span>{maxToolCalls}</span></label>
                      <input type="range" id="maxToolCount" min="1" max="10" step="1" value={maxToolCalls} onChange={(e) => setMaxToolCalls(parseInt(e.target.value, 10))}
                        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* --- Token 消耗显示 --- */}
          <div className="mb-4 text-xs text-gray-500 text-center">
            <span>输入token: </span>
            <span className="font-medium text-gray-700">{currentMessageUsage?.prompt_tokens ?? '...'}</span>
            <span className="mx-2">|</span>
            <span>输出token: </span>
            <span className="font-medium text-gray-700">{currentMessageUsage?.completion_tokens ?? '...'}</span>
            <span className="mx-2">|</span>
            <span>当前消息总token: </span>
            <span className="font-bold text-gray-800">{currentMessageUsage?.total_tokens ?? '...'}</span>
            <span className="mx-2">|</span>
            <span>会话总token: </span>
            <span className="font-bold text-blue-600">{totalSessionTokens > 0 ? totalSessionTokens : '...'}</span>
          </div>

          <div ref={chatContainerRef} className="flex-grow bg-white rounded-lg shadow-inner p-4 overflow-y-auto mb-4 space-y-4">
            {/* 渲染已完成的对话历史 */}
            {conversation.map((msg, index) => (
              <div key={index} className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div className={`whitespace-pre-wrap max-w-xl px-4 py-2 rounded-lg shadow-sm ${msg.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-800'}`}>
                  {msg.content}
                </div>
                {/* 如果是助理消息并且有耗时信息，则显示它 --- */}
                {msg.role === 'assistant' && msg.duration && (
                  <div className="text-xs text-gray-400 mt-1">
                    {/* LLM总耗时 */}
                    {msg.duration.total_duration > 0 && (
                      <>
                        <span>LLM总耗时: </span>
                        <span className="font-medium">{Math.round(msg.duration.total_duration / 1e6)}ms</span>
                      </>
                    )}
                    {/* LLM加载 */}
                    {msg.duration.load_duration > 0 && (
                      <>
                        <span className="mx-1">|</span>
                        <span>LLM加载: </span>
                        <span className="font-medium">{Math.round(msg.duration.load_duration / 1e6)}ms</span>
                      </>
                    )}
                    {/* LLM思考 */}
                    {msg.duration.prompt_eval_duration > 0 && (
                      <>
                        <span className="mx-1">|</span>
                        <span>LLM思考: </span>
                        <span className="font-medium">{Math.round(msg.duration.prompt_eval_duration / 1e6)}ms</span>
                      </>
                    )}
                    {/* 生成内容 */}
                    {msg.duration.eval_duration > 0 && (
                      <>
                        <span className="mx-1">|</span>
                        <span>生成内容: </span>
                        <span className="font-medium">{Math.round(msg.duration.eval_duration / 1e6)}ms</span>
                      </>
                    )}
                    {/* 如果有传输开销数据 */}
                    {msg.overhead_ms !== undefined && msg.overhead_ms > 0 && (
                      <>
                        <span className="mx-1">|</span>
                        <span>传输耗时: </span>
                        <span className="font-medium">{msg.overhead_ms}ms</span>
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
            {/* 如果正在接收流式响应，则渲染这个临时消息块 */}
            {streamingResponse && (
              <div className="flex flex-col items-start">
                <div className="whitespace-pre-wrap max-w-xl px-4 py-2 rounded-lg shadow-sm bg-gray-200 text-gray-800">
                  {streamingResponse}
                  <span className="animate-pulse">▍</span>
                </div>
                {/* 在流式响应下方也显示实时更新的耗时信息 */}
                {currentMessageDuration && (
                  <div className="text-xs text-gray-400 mt-1">
                    {currentMessageDuration.total_duration > 0 && (
                      <>
                        <span>LLM总耗时: </span>
                        <span className="font-medium">{Math.round(currentMessageDuration.total_duration / 1e6)}ms</span>
                      </>
                    )}
                    {currentMessageDuration.load_duration > 0 && (
                      <>
                        <span className="mx-1">|</span>
                        <span>LLM加载: </span>
                        <span className="font-medium">{Math.round(currentMessageDuration.load_duration / 1e6)}ms</span>
                      </>
                    )}
                    {currentMessageDuration.prompt_eval_duration > 0 && (
                      <>
                        <span className="mx-1">|</span>
                        <span>LLM思考: </span>
                        <span className="font-medium">{Math.round(currentMessageDuration.prompt_eval_duration / 1e6)}ms</span>
                      </>
                    )}
                    {currentMessageDuration.eval_duration > 0 && (
                      <>
                        <span className="mx-1">|</span>
                        <span>生成内容: </span>
                        <span className="font-medium">{Math.round(currentMessageDuration.eval_duration / 1e6)}ms</span>
                      </>
                    )}
                    {/* 如果有传输开销数据 */}
                    {currentMessageOverhead !== null && currentMessageOverhead > 0 && (
                      <>
                        <span className="mx-1">|</span>
                        <span>传输耗时: </span>
                        <span className="font-medium">{currentMessageOverhead}ms</span>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}
            {conversation.length === 0 && !streamingResponse && <p className="text-gray-400 text-center">开始对话吧...</p>}
          </div>

          <div className="flex items-start space-x-4">
            <textarea
              id="message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyPress}
              placeholder="输入消息..."
              rows={2}
              className="flex-grow px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              disabled={isLoading}
            />
            <button
              onClick={handleSendMessage}
              disabled={isLoading || !message.trim() || modelOptions.length === 0}
              className="px-6 py-2 rounded-md font-medium text-white transition-colors disabled:bg-gray-400 disabled:cursor-not-allowed bg-blue-600 hover:bg-blue-700"
            >
              {isLoading ? "思考中..." : "发送"}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}