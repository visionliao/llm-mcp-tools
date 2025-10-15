"use client";

import { useState, useEffect, useRef } from "react";
import { LlmGenerationOptions } from "@/lib/llm/types"; 

// 定义与后端 lib/llm/types.ts 匹配的类型
interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
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

    setIsLoading(true);
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

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          completeResponse += chunk;
          // 只更新独立的 streamingResponse state
          setStreamingResponse(prev => prev + chunk);
        }
        // 流结束后，将完整的回复一次性加入对话历史
        setConversation(prev => [...prev, { role: 'assistant', content: completeResponse }]);
      } else {
        // 处理非流式响应
        const data = await response.json();
        const completeResponse = data.response;
        setConversation(prev => [...prev, { role: 'assistant', content: completeResponse }]);
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
        <h1 className="text-xl font-bold text-center text-gray-800">MCP 客户端</h1>
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

          {/* --- 在模型选择下方添加参数滑块 --- */}
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
              <label htmlFor="historyLength" className="flex justify-between"><span>历史条数</span> <span>{historyLength}</span></label>
              <input type="range" id="historyLength" min="0" max="100" step="1" value={historyLength} onChange={(e) => setHistoryLength(parseInt(e.target.value, 10))}
                className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
            </div>
            {/* --- 第三行：启用流式输出 和 MCP服务器地址  --- */}
            <div className="md:col-span-2 flex items-center justify-between space-x-2">
              <input
                type="checkbox" id="stream-toggle" checked={isStreamingEnabled}
                onChange={(e) => setIsStreamingEnabled(e.target.checked)}
                className="w-4 h-4 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500"
              />
              <label htmlFor="stream-toggle" className="ml-2 font-medium text-gray-900">
                启用流式输出
              </label>
              {/* MCP 服务器输入框和测试按钮 */}
              <input
                type="text"
                value={mcpServerUrl}
                onChange={(e) => {
                  setMcpServerUrl(e.target.value);
                  setMcpStatus('unchecked'); // 地址变化后重置状态
                }}
                placeholder="MCP 服务器地址"
                className="flex-grow px-2 py-1 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button 
                onClick={handleConnectivityTest} 
                disabled={mcpStatus === 'testing'}
                className={`px-3 py-1 rounded-md text-white text-xs transition-colors ${
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

          <div ref={chatContainerRef} className="flex-grow bg-white rounded-lg shadow-inner p-4 overflow-y-auto mb-4 space-y-4">
            {/* 渲染已完成的对话历史 */}
            {conversation.map((msg, index) => (
              <div key={index} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`whitespace-pre-wrap max-w-xl px-4 py-2 rounded-lg shadow-sm ${msg.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-800'}`}>
                  {msg.content}
                </div>
              </div>
            ))}
            {/* 如果正在接收流式响应，则渲染这个临时消息块 */}
            {streamingResponse && (
              <div className="flex justify-start">
                <div className="whitespace-pre-wrap max-w-xl px-4 py-2 rounded-lg shadow-sm bg-gray-200 text-gray-800">
                  {streamingResponse}
                  <span className="animate-pulse">▍</span>
                </div>
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