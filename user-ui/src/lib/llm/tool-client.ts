// lib/llm/tool-client.ts

import { FastMCPClient } from './fastmcp-client';

// 定义 MCP 服务返回结构的类型
export interface McpToolSchema {
    type: 'function';
    function: {
        name: string;
        description?: string;
        parameters?: Record<string, unknown>;
    };
}

export class ToolClient {
    private serverUrl: string;
    private toolsCache: McpToolSchema[] | null | undefined = null;
    private fastMCPClient: FastMCPClient | null = null;

    constructor(serverUrl: string) {
        this.serverUrl = serverUrl;
    }

    /**
     * 判断是否为FastMCP服务器（基于端口）
     */
    private isFastMCPServer(): boolean {
        try {
            const url = new URL(this.serverUrl);
            return url.port === '8001'; // FastMCP服务器端口
        } catch {
            return false;
        }
    }

    /**
     * 获取FastMCP客户端实例
     */
    private getFastMCPClient(): FastMCPClient {
        if (!this.fastMCPClient) {
            this.fastMCPClient = new FastMCPClient(this.serverUrl);
        }
        return this.fastMCPClient;
    }

    /**
     * 从 MCP 服务器获取工具列表并缓存。
     */
    public async getToolsSchema(): Promise<McpToolSchema[] | undefined> {
        if (!this.serverUrl) return undefined;
        if (this.toolsCache) return this.toolsCache;

        try {
            if (this.isFastMCPServer()) {
                console.log(`--- [Tool Discovery] Using FastMCP client for ${this.serverUrl} ---`);
                this.toolsCache = await this.getFastMCPClient().getToolsSchema();
            } else {
                console.log(`--- [Tool Discovery] Using FastAPI client for ${this.serverUrl} ---`);
                const response = await fetch(`${this.serverUrl}/tools`);
                if (!response.ok) throw new Error(`Failed to fetch tools: ${response.statusText}`);
                const schema = await response.json();
                this.toolsCache = schema as McpToolSchema[];
            }
            
            console.log(`--- 获取工具列表结果： ${JSON.stringify(this.toolsCache, null, 2)}`);
            return this.toolsCache;
        } catch (error) {
            console.error("[ToolClient] Failed to get tools schema:", error);
            // 在无法获取工具时，不应中断整个流程，而是返回 undefined
            return undefined;
        }
    }

    /**
     * 调用 MCP 服务器执行单个工具。
     * @param toolName 工具名称
     * @param toolArgs 工具参数
     * @returns 工具执行结果
    */
    public async callTool(toolName: string, toolArgs: Record<string, unknown>): Promise<unknown> {
        console.log(`--- [ToolClient] Calling tool: ${toolName} with args:`, toolArgs);
        try {
            if (this.isFastMCPServer()) {
                console.log(`--- [ToolClient] Using FastMCP client for tool execution ---`);
                const result = await this.getFastMCPClient().callTool(toolName, toolArgs);
                console.log(`--- FastMCP工具执行结果： ${JSON.stringify(result, null, 2)}`);
                return result;
            } else {
                console.log(`--- [ToolClient] Using FastAPI client for tool execution ---`);
                const response = await fetch(`${this.serverUrl}/call`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tool_name: toolName, arguments: toolArgs }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({ detail: "Unknown error" }));
                    throw new Error(`MCP server failed to execute tool '${toolName}': ${errorData.detail}`);
                }

                const resultData = await response.json() as { result: unknown };
                console.log(`--- FastAPI工具执行结果： ${JSON.stringify(resultData, null, 2)}`);
                return resultData.result;
            }
        } catch (error) {
            console.error(`[ToolClient] Failed to execute tool '${toolName}':`, error);
            throw error;
        }
    }
}