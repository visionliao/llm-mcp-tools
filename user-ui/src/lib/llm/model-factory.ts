// lib/llm/model-factory.ts

import { BaseChatProvider } from './base-provider';
import { getProviderConfig } from './model-config';
import { BaseProviderConfig, LlmGenerationOptions } from './types';

/**
 * 智能工厂，负责创建聊天提供商的实例。
 * 职责：根据名称动态加载并实例化正确的 Provider。
 * @param providerName 提供商名称
 * @returns 一个 BaseChatProvider 的实例。
 */
export async function createChatProvider(
  providerName: string,
  runtimeOptions?: LlmGenerationOptions
): Promise<BaseChatProvider> {
  // 1. 从配置模块获取配置
  const config = getProviderConfig(providerName);
  const finalConfig: BaseProviderConfig = {
    ...config,
    ...runtimeOptions, // 用户传入的运行时参数，实现覆盖
  };

  const providerKey = providerName.toLowerCase();
  try {
    // 2. 动态导入具体的 Provider 模块，实现按需加载
    const providerModule = await import(`./providers/${providerKey}`);
    
    // 3. 遵循命名约定（e.g., 'google' -> 'GoogleChatProvider'）找到类
    const className = `${providerKey.charAt(0).toUpperCase() + providerKey.slice(1)}ChatProvider`;
    const ProviderClass = providerModule[className] as new (config: BaseProviderConfig) => BaseChatProvider;

    if (!ProviderClass) {
      throw new Error(`Could not find class ${className} in module providers/${providerKey}.ts`);
    }

    // 4. 使用配置实例化并返回
    return new ProviderClass(finalConfig);
  } catch (error) {
    console.error(`Factory error: Failed to create provider for '${providerKey}':`, error);
    throw new Error(`Unsupported or failed to load provider: ${providerName}`);
  }
}