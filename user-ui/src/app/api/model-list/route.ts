import { NextRequest, NextResponse } from 'next/server';

// 大模型配置类型
interface ModelConfig {
  provider: string;
  models: string[];
  proxyUrl?: string;
}

// 从环境变量中动态解析有效的大模型配置
function getAvailableModels(): ModelConfig[] {
  const configs: ModelConfig[] = [];
  // 获取所有环境变量
  const envVars = process.env;

  // 遍历所有环境变量，查找*_API_KEY 格式的变量
  Object.keys(envVars).forEach(key => {
    // 匹配 (PROVIDER)_API_KEY 格式的变量
    const providerMatch = key.match(/^([A-Z0-9]+)_API_KEY$/);
    if (providerMatch) {
      const providerName = providerMatch[1];
      
      // 获取对应的模型列表和代理URL
      const modelsKey = `${providerName}_MODEL_LIST`;
      const proxyKey = `${providerName}_PROXY_URL`;
      
      const apiKey = envVars[key];
      const models = envVars[modelsKey]?.split(',').filter(Boolean) || [];
      const proxyUrl = envVars[proxyKey];
      
      // 检查配置是否有效
      const hasValidApiKey = apiKey && apiKey !== '' && apiKey !== 'None';
      const hasModels = models.length > 0;
      
      // 特殊处理 Ollama：API_KEY为None也算有效，但必须有模型列表
      if (providerName === 'OLLAMA') {
        if (hasModels) {
          configs.push({
            provider: providerName.charAt(0).toUpperCase() + providerName.slice(1).toLowerCase(),
            models: models,
            proxyUrl: proxyUrl
          });
        }
      } else {
        // 其他提供商：必须有有效的API_KEY和模型列表
        if (hasValidApiKey && hasModels) {
          configs.push({
            provider: providerName.charAt(0).toUpperCase() + providerName.slice(1).toLowerCase(),
            models: models,
            proxyUrl: proxyUrl
          });
        }
      }
    }
  });
  
  return configs;
}

// 获取所有可用模型的下拉列表选项
function getModelOptions(): { value: string; label: string; provider: string }[] {
  const configs = getAvailableModels();
  const options: { value: string; label: string; provider: string }[] = [];
  
  configs.forEach(config => {
    config.models.forEach(model => {
      options.push({
        value: `${config.provider}:${model}`,
        label: `${config.provider} - ${model}`,
        provider: config.provider
      });
    });
  });
  
  return options;
}

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const type = searchParams.get('type');
    
    if (type === 'options') {
      return NextResponse.json(getModelOptions());
    }
    
    return NextResponse.json({ error: 'Invalid type parameter. Only "options" is supported.' }, { status: 400 });

  } catch (error) {
    console.error('API error in model-list:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}