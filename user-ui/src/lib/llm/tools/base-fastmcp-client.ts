// lib/llm/tools/base-fastmcp-client.ts

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { McpToolSchema } from './tool-client';

// 定义MCP工具接口
interface MCPTool {
    name: string;
    description?: string;
    inputSchema: Record<string, unknown>;
}

interface ListToolsResult {
    tools: MCPTool[];
}

interface CallToolResult {
    content: Array<{
        type: string;
        text?: string;
    }>;
}

/**
 * FastMCP客户端抽象基类
 * 定义所有FastMCP传输方式的通用接口
 */
export abstract class BaseFastMCPClient {
    protected serverUrl: string;
    protected toolsCache: McpToolSchema[] | null = null;

    constructor(serverUrl: string) {
        this.serverUrl = serverUrl;
    }

    /**
     * 初始化客户端连接
     */
    protected abstract initializeClient(): Promise<Client>;

    /**
     * 获取工具列表
     */
    public async getToolsSchema(): Promise<McpToolSchema[] | undefined> {
        if (this.toolsCache) return this.toolsCache;

        try {
            const client = await this.initializeClient();
            console.log(`--- [${this.getClientType()}] Fetching tools schema ---`);

            // 获取工具列表，添加超时控制
            const toolsPromise = client.listTools();
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('Tool discovery timeout')), 15000);
            });

            const toolsResponse = await Promise.race([toolsPromise, timeoutPromise]) as ListToolsResult;

            // 转换为统一的McpToolSchema格式
            this.toolsCache = toolsResponse.tools.map(tool => ({
                type: 'function' as const,
                function: {
                    name: tool.name,
                    description: tool.description,
                    parameters: tool.inputSchema
                }
            }));

            console.log(`--- [${this.getClientType()}] 工具列表结果： ${JSON.stringify(this.toolsCache, null, 2)}`);
            return this.toolsCache;
        } catch (error) {
            console.error(`[${this.getClientType()}] Failed to get tools schema:`, error);
            return undefined;
        }
    }

    /**
     * 调用工具
     */
    public async callTool(toolName: string, toolArgs: Record<string, unknown>): Promise<unknown> {
        console.log(`--- [${this.getClientType()}] Calling tool: ${toolName} with args:`, toolArgs);

        try {
            const client = await this.initializeClient();

            // 调用工具，添加超时控制
            const toolPromise = client.callTool({
                name: toolName,
                arguments: toolArgs
            });
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('Tool execution timeout')), 30000);
            });

            const result = await Promise.race([toolPromise, timeoutPromise]) as CallToolResult;

            // 处理不同类型的返回结果
            if (result.content && Array.isArray(result.content)) {
                const textContent = result.content.find(item => item.type === 'text');
                if (textContent && 'text' in textContent) {
                    return textContent.text;
                }
            }
            return result;
        } catch (error) {
            console.error(`[${this.getClientType()}] Failed to call tool '${toolName}':`, error);
            throw new Error(`${this.getClientType()} server failed to execute tool '${toolName}': ${error instanceof Error ? error.message : String(error)}`);
        }
    }

    /**
     * 关闭连接
     */
    public abstract close(): Promise<void>;

    /**
     * 获取客户端类型名称（用于日志）
     */
    protected abstract getClientType(): string;
}