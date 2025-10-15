// lib/llm/model-config.ts

import { BaseProviderConfig } from './types';

/**
 * 根据提供商名称从环境变量中获取并验证配置。
 * 职责：集中管理配置的读取和验证逻辑。
 * @param providerName 提供商名称 (e.g., 'google', 'openai')
 * @returns 返回一个有效的提供商配置对象。
 * @throws 如果必要的配置缺失，则抛出错误。
 */
export function getProviderConfig(providerName: string): BaseProviderConfig {
  const providerKey = providerName.toLowerCase();
  const upperCaseProvider = providerKey.toUpperCase();

  const apiKey = process.env[`${upperCaseProvider}_API_KEY`];
  const proxyUrl = process.env[`${upperCaseProvider}_PROXY_URL`];

  // 特殊处理 Ollama，其 API Key 可以是 'None'
  if (providerKey === 'ollama' && apiKey === 'None') {
    return { apiKey: 'None', proxyUrl };
  }

  // 对其他提供商进行通用验证
  if (!apiKey || apiKey.trim() === '') {
    throw new Error(
      `Configuration error: API key for ${providerName} is missing. ` +
      `Please set the NEXT_PUBLIC_${upperCaseProvider}_API_KEY environment variable.`
    );
  }

  return { apiKey, proxyUrl };
}