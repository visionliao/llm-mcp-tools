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
    private serverTypeCache: 'fastmcp' | 'fastapi' | null = null;

    constructor(serverUrl: string) {
        this.serverUrl = serverUrl;
    }

    /**
     * 动态检测MCP服务器类型
     * 通过测试不同的端点来判断是FastMCP还是FastAPI
     */
    private async detectServerType(): Promise<'fastmcp' | 'fastapi'> {
        // 如果已经检测过，直接返回缓存结果
        if (this.serverTypeCache) {
            return this.serverTypeCache;
        }

        try {
            console.log(`--- [Server Detection] Detecting server type for ${this.serverUrl} ---`);

            // 首先尝试检测FastMCP的SSE端点
            const sseUrl = `${this.serverUrl}/sse`;
            console.log(`--- [Server Detection] Testing FastMCP SSE endpoint: ${sseUrl} ---`);

            try {
                const sseResponse = await fetch(sseUrl, {
                    method: 'GET',
                    headers: { 'Accept': 'text/event-stream' },
                    signal: AbortSignal.timeout(5000) // 5秒超时
                });

                if (sseResponse.ok || sseResponse.status === 200) {
                    console.log(`--- [Server Detection] FastMCP SSE endpoint responded, detected as FastMCP server ---`);
                    this.serverTypeCache = 'fastmcp';
                    return 'fastmcp';
                }
            } catch (sseError) {
                console.log(`--- [Server Detection] SSE endpoint test failed: ${sseError instanceof Error ? sseError.message : String(sseError)} ---`);
            }

            // 尝试检测FastAPI的tools端点
            const toolsUrl = `${this.serverUrl}/tools`;
            console.log(`--- [Server Detection] Testing FastAPI tools endpoint: ${toolsUrl} ---`);

            try {
                const toolsResponse = await fetch(toolsUrl, {
                    method: 'GET',
                    headers: { 'Content-Type': 'application/json' },
                    signal: AbortSignal.timeout(5000)
                });

                if (toolsResponse.ok) {
                    // 尝试解析JSON，确认是有效的FastAPI响应
                    const data = await toolsResponse.json();
                    if (Array.isArray(data) || (data && typeof data === 'object')) {
                        console.log(`--- [Server Detection] FastAPI tools endpoint responded with valid JSON, detected as FastAPI server ---`);
                        this.serverTypeCache = 'fastapi';
                        return 'fastapi';
                    }
                }
            } catch (toolsError) {
                console.log(`--- [Server Detection] Tools endpoint test failed: ${toolsError instanceof Error ? toolsError.message : String(toolsError)} ---`);
            }

            // 如果两个端点都测试失败，尝试基础的HTTP连接测试
            console.log(`--- [Server Detection] Testing basic HTTP connectivity to ${this.serverUrl} ---`);
            try {
                const basicResponse = await fetch(this.serverUrl, {
                    method: 'GET',
                    signal: AbortSignal.timeout(3000)
                });

                if (basicResponse.ok) {
                    console.log(`--- [Server Detection] Basic HTTP connection succeeded, defaulting to FastAPI server ---`);
                    this.serverTypeCache = 'fastapi';
                    return 'fastapi';
                }
            } catch (basicError) {
                console.log(`--- [Server Detection] Basic HTTP connection failed: ${basicError instanceof Error ? basicError.message : String(basicError)} ---`);
            }

            // 如果所有检测都失败，抛出错误
            throw new Error('Unable to determine MCP server type. Both FastMCP SSE and FastAPI endpoints are not accessible.');
        } catch (error) {
            console.error('[Server Detection] Server type detection failed:', error);
            throw new Error(`Failed to detect MCP server type: ${error instanceof Error ? error.message : String(error)}`);
        }
    }

    /**
     * 判断是否为FastMCP服务器（使用动态检测）
     */
    private async isFastMCPServer(): Promise<boolean> {
        try {
            const serverType = await this.detectServerType();
            return serverType === 'fastmcp';
        } catch {
            // 如果检测失败，默认为FastAPI
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
     * 获取检测到的服务器类型
     */
    public async getServerType(): Promise<'fastmcp' | 'fastapi' | 'unknown'> {
        try {
            return await this.detectServerType();
        } catch {
            return 'unknown';
        }
    }

    /**
     * 从 MCP 服务器获取工具列表并缓存。
     */
    public async getToolsSchema(): Promise<McpToolSchema[] | undefined> {
        if (!this.serverUrl) return undefined;
        if (this.toolsCache) return this.toolsCache;

        try {
            const isFastMCP = await this.isFastMCPServer();

            if (isFastMCP) {
                console.log(`--- [Tool Discovery] Using FastMCP client for ${this.serverUrl} ---`);
                this.toolsCache = await this.getFastMCPClient().getToolsSchema();
            } else {
                console.log(`--- [Tool Discovery] Using FastAPI client for ${this.serverUrl} ---`);
                const response = await fetch(`${this.serverUrl}/tools`);
                if (!response.ok) throw new Error(`Failed to fetch tools: ${response.statusText}`);
                const schema = await response.json();
                this.toolsCache = schema as McpToolSchema[];
            }

            // console.log(`--- 获取工具列表结果： ${JSON.stringify(this.toolsCache, null, 2)}`);
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
            const isFastMCP = await this.isFastMCPServer();

            if (isFastMCP) {
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