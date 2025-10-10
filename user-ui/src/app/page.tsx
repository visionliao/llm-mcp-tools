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
  const [temperature, setTemperature] = useState(1.0);
  const [topP, setTopP] = useState(1.0);
  const [presencePenalty, setPresencePenalty] = useState(0);
  const [frequencyPenalty, setFrequencyPenalty] = useState(0);
  const [maxOutputTokens, setMaxOutputTokens] = useState(8192);

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
    const newConversation = [...conversation, userMessage];
    setConversation(newConversation);
    setMessage("");
    setStreamingResponse(""); // 清空上一次的流式响应

    const generationOptions: LlmGenerationOptions = {
      temperature,
      topP,
      presencePenalty,
      frequencyPenalty,
      maxOutputTokens,
    };
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          selectedModel,
          messages: newConversation, // 发送包含最新用户消息的完整历史
          options: generationOptions, // 发送模型参数
        }),
      });

      if (!response.ok || !response.body) {
        const errorData = await response.json();
        throw new Error(errorData.error || '服务器响应错误');
      }

      // 处理流式响应
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

          {/* --- 在模型选择下方添加参数滑块 --- */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 mb-4 p-4 border rounded-lg bg-white text-sm">
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
            <div>
              <label htmlFor="frequencyPenalty" className="flex justify-between"><span>词汇丰富度 (Frequency Penalty)</span> <span>{frequencyPenalty.toFixed(1)}</span></label>
              <input type="range" id="frequencyPenalty" min="-2" max="1.9" step="0.1" value={frequencyPenalty} onChange={(e) => setFrequencyPenalty(parseFloat(e.target.value))}
                className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
            </div>
            <div className="md:col-span-2">
              <label htmlFor="maxTokens" className="flex justify-between"><span>单次回复限制 (Max Tokens)</span> <span>{maxOutputTokens}</span></label>
              <input type="range" id="maxTokens" min="256" max="32000" step="256" value={maxOutputTokens} onChange={(e) => setMaxOutputTokens(parseInt(e.target.value, 10))}
                className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"/>
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
            {/* 【新增】如果正在接收流式响应，则渲染这个临时消息块 */}
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