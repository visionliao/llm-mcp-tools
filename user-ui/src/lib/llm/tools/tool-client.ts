// lib/llm/tools/tool-client.ts

import { BaseFastMCPClient } from './base-fastmcp-client';
import { FastMCPClientFactory } from './fastmcp-client-factory';

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
    private fastMCPClient: BaseFastMCPClient | null = null;
    private serverTypeCache: 'fastmcp-sse' | 'fastmcp-streamablehttp' | 'fastapi' | null = null;

    constructor(serverUrl: string) {
        this.serverUrl = serverUrl;
    }

    /**
     * 动态检测MCP服务器类型
     * 通过测试不同的端点来判断是FastMCP SSE、FastMCP StreamableHTTP还是FastAPI
     */
    private async detectServerType(): Promise<'fastmcp-sse' | 'fastmcp-streamablehttp' | 'fastapi'> {
        // 如果已经检测过，直接返回缓存结果
        if (this.serverTypeCache) {
            return this.serverTypeCache;
        }

        try {
            console.log(`--- [Server Detection] Detecting server type for ${this.serverUrl} ---`);

            // 使用FastMCPClientFactory检测协议类型
            const protocolType = await FastMCPClientFactory.detectProtocolType(this.serverUrl);

            if (protocolType === 'sse') {
                console.log(`--- [Server Detection] FastMCP SSE protocol detected ---`);
                this.serverTypeCache = 'fastmcp-sse';
                return 'fastmcp-sse';
            } else if (protocolType === 'streamablehttp') {
                console.log(`--- [Server Detection] FastMCP StreamableHTTP protocol detected ---`);
                this.serverTypeCache = 'fastmcp-streamablehttp';
                return 'fastmcp-streamablehttp';
            }

            // 如果没有检测到FastMCP协议，尝试检测FastAPI
            console.log(`--- [Server Detection] Testing FastAPI tools endpoint ---`);
            const toolsUrl = `${this.serverUrl}/tools`;
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

            // 如果所有检测都失败，尝试基础的HTTP连接测试
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
            throw new Error('Unable to determine MCP server type. No supported protocols detected.');
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
            return serverType === 'fastmcp-sse' || serverType === 'fastmcp-streamablehttp';
        } catch {
            // 如果检测失败，默认为FastAPI
            return false;
        }
    }

    /**
     * 获取FastMCP客户端实例
     */
    private async getFastMCPClient(): Promise<BaseFastMCPClient> {
        if (!this.fastMCPClient) {
            // 根据检测到的服务器类型创建相应的客户端
            const serverType = await this.detectServerType();
            let protocolType: 'sse' | 'streamablehttp' | undefined = undefined;

            if (serverType === 'fastmcp-sse') {
                protocolType = 'sse';
            } else if (serverType === 'fastmcp-streamablehttp') {
                protocolType = 'streamablehttp';
            }

            this.fastMCPClient = await FastMCPClientFactory.createClient(this.serverUrl, protocolType);
            if (!this.fastMCPClient) {
                throw new Error('Failed to create FastMCP client');
            }
        }
        return this.fastMCPClient;
    }

    /**
     * 获取检测到的服务器类型
     */
    public async getServerType(): Promise<'fastmcp-sse' | 'fastmcp-streamablehttp' | 'fastapi' | 'unknown'> {
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
                this.toolsCache = await (await this.getFastMCPClient()).getToolsSchema();
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
                const result = await (await this.getFastMCPClient()).callTool(toolName, toolArgs);
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