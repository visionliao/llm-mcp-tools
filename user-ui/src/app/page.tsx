"use client";

import { useState, useEffect, useRef } from "react";

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
  const [conversation, setConversation] = useState<ChatMessage[]>([]);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // 自动滚动到聊天记录底部
  useEffect(() => {
    chatContainerRef.current?.scrollTo({ top: chatContainerRef.current.scrollHeight, behavior: 'smooth' });
  }, [conversation]);

  // 组件加载时获取可用模型
  useEffect(() => {
    const loadModelOptions = async () => {
      try {
        const response = await fetch('/api/model-list?type=options');
        if (!response.ok) throw new Error('Failed to fetch model options');
        const options = await response.json();
        setModelOptions(options);
        
        // 如果有模型，默认选择第一个
        if (options.length > 0) {
          setSelectedModel(options[0].value);
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
    // 立即添加一个空的 assistant 消息用于接收流式响应
    setConversation(prev => [...prev, { role: 'assistant', content: '' }]);
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          selectedModel,
          messages: newConversation, // 发送包含最新用户消息的完整历史
        }),
      });

      if (!response.ok || !response.body) {
        const errorData = await response.json();
        throw new Error(errorData.error || '服务器响应错误');
      }

      // 处理流式响应
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let done = false;

      while (!done) {
        const { value, done: readerDone } = await reader.read();
        done = readerDone;
        const chunk = decoder.decode(value, { stream: true });
        
        // 更新最后一条 assistant 消息的内容
        setConversation(prev => {
          const lastMessage = prev[prev.length - 1];
          lastMessage.content += chunk;
          return [...prev.slice(0, -1), lastMessage];
        });
      }
    } catch (error: any) {
      console.error("发送消息失败:", error);
      setConversation(prev => {
        const lastMessage = prev[prev.length - 1];
        lastMessage.content = `错误: ${error.message}`;
        return [...prev.slice(0, -1), lastMessage];
      });
    } finally {
      setIsLoading(false);
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
      <header className="p-4 border-b">
        <h1 className="text-xl font-bold text-center">MCP 客户端</h1>
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
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {modelOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : (
              <div className="w-full px-3 py-2 border border-gray-200 rounded-md bg-gray-100 text-gray-500">
                没有可用的模型配置...
              </div>
            )}
          </div>

          <div ref={chatContainerRef} className="flex-grow bg-white rounded-lg shadow-inner p-4 overflow-y-auto mb-4 space-y-4">
            {conversation.map((msg, index) => (
              <div key={index} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`whitespace-pre-wrap max-w-xl px-4 py-2 rounded-lg ${msg.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-800'}`}>
                  {msg.content}
                  {/* 在流式输出时显示一个光标 */}
                  {isLoading && msg.role === 'assistant' && index === conversation.length - 1 && <span className="animate-pulse">▍</span>}
                </div>
              </div>
            ))}
             {conversation.length === 0 && <p className="text-gray-400 text-center">开始对话吧...</p>}
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