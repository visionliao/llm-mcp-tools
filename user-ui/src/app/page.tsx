"use client";

import { useState, useEffect } from "react";

interface ModelOption {
  value: string;
  label: string;
  provider: string;
}

export default function Home() {
  const [serverUrl, setServerUrl] = useState("");
  const [message, setMessage] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);

  useEffect(() => {
    // 在组件挂载时获取可用的模型选项
    const loadModelOptions = async () => {
      try {
        const response = await fetch('/api/model-list?type=options');
        if (response.ok) {
          const options = await response.json();
          setModelOptions(options);
          
          // 如果有可用的模型，默认选择第一个
          if (options.length > 0 && !selectedModel) {
            setSelectedModel(options[0].value);
          }
        }
      } catch (error) {
        console.error('获取模型选项失败:', error);
      }
    };
    
    loadModelOptions();
  }, [selectedModel]);

  const handleSendMessage = async () => {
    if (!message.trim()) {
      alert("请输入消息");
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`/api/model-list?type=parse&value=${encodeURIComponent(selectedModel)}`);
      if (response.ok) {
        const modelInfo = await response.json();
        console.log("发送消息到服务器:", serverUrl);
        console.log("消息内容:", message);
        console.log("选择的模型:", modelInfo);
        
        // 清空消息输入框
        setMessage("");
      } else {
        console.error("解析模型选择失败");
      }
    } catch (error) {
      console.error("发送消息失败:", error);
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
    <div className="min-h-screen bg-gray-50 py-8">
      <div className="max-w-4xl mx-auto px-4">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            MCP 客户端
          </h1>
          <p className="text-gray-600">
            连接到 MCP 服务器并发送消息
          </p>
        </div>

        <div className="bg-white rounded-lg shadow-md p-6 mb-6">
          <div className="mb-6">
            <label htmlFor="serverUrl" className="block text-sm font-medium text-gray-700 mb-2">
              MCP 服务器地址
            </label>
            <input
              type="text"
              id="serverUrl"
              value={serverUrl}
              onChange={(e) => setServerUrl(e.target.value)}
              placeholder="例如: http://localhost:3001"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div className="mb-6">
            <label htmlFor="modelSelect" className="block text-sm font-medium text-gray-700 mb-2">
              选择大模型
            </label>
            {modelOptions.length > 0 ? (
              <select
                id="modelSelect"
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
              >
                {modelOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : (
              <div className="w-full px-3 py-2 border border-gray-300 rounded-md bg-gray-50 text-gray-500">
                没有可用的模型配置，请检查 .env 文件中的 API_KEY 和 MODEL_LIST 配置
              </div>
            )}
          </div>

          <div className="mb-6">
            <label htmlFor="message" className="block text-sm font-medium text-gray-700 mb-2">
              消息
            </label>
            <textarea
              id="message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyPress}
              placeholder="输入要发送的消息..."
              rows={4}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            />
          </div>

          <button
            onClick={handleSendMessage}
            disabled={isLoading || !message.trim() || modelOptions.length === 0}
            className={`w-full py-2 px-4 rounded-md font-medium text-white transition-colors ${
              isLoading || !message.trim() || modelOptions.length === 0
                ? "bg-gray-400 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-700"
            }`}
          >
            {isLoading ? "发送中..." : "发送消息"}
          </button>
        </div>

        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">大模型回复</h2>
          <div className="bg-gray-50 rounded-md p-4 min-h-[200px] max-h-[400px] overflow-y-auto">
            <p className="text-gray-400">大模型的回复将在这里显示...</p>
          </div>
        </div>
      </div>
    </div>
  );
}