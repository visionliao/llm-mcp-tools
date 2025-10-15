// lib/llm/tools/fastmcp-client.ts

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js';
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

export class FastMCPClient {
    private client: Client | null = null;
    private toolsCache: McpToolSchema[] | null = null;
    private serverUrl: string;

    constructor(serverUrl: string) {
        this.serverUrl = serverUrl;
    }

    /**
     * 初始化MCP客户端连接
     */
    private async initializeClient(): Promise<Client> {
        if (this.client) {
            return this.client;
        }

        try {
            const sseUrl = `${this.serverUrl}/sse`;
            console.log(`--- [FastMCP Client] Initializing connection to ${sseUrl} ---`);

            // 创建SSE传输连接，添加超时控制
            const transport = new SSEClientTransport(new URL(sseUrl));

            // 创建MCP客户端
            this.client = new Client(
                {
                    name: 'nextjs-llm-client',
                    version: '1.0.0',
                },
                {
                    capabilities: {}
                }
            );

            // 设置连接超时
            const connectPromise = this.client.connect(transport);
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('MCP connection timeout')), 10000);
            });

            // 连接到服务器
            await Promise.race([connectPromise, timeoutPromise]);
            console.log(`--- [FastMCP Client] Successfully connected to MCP server ---`);

            return this.client;
        } catch (error) {
            console.error("[FastMCP Client] Failed to initialize client:", error);
            this.client = null;
            throw new Error(`Failed to initialize MCP client: ${error instanceof Error ? error.message : String(error)}`);
        }
    }

    /**
     * 从FastMCP服务器获取工具列表并缓存
     */
    public async getToolsSchema(): Promise<McpToolSchema[] | undefined> {
        if (this.toolsCache) return this.toolsCache;
        try {
            const client = await this.initializeClient();
            console.log(`--- [FastMCP Client] Fetching tools schema ---`);

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
            console.log(`--- FastMCP工具列表结果： ${JSON.stringify(this.toolsCache, null, 2)}`);
            return this.toolsCache;
        } catch (error) {
            console.error("[FastMCP Client] Failed to get tools schema:", error);
            return undefined;
        }
    }

    /**
     * 调用FastMCP服务器执行工具
     * @param toolName 工具名称
     * @param toolArgs 工具参数
     * @returns 工具执行结果
     */
    public async callTool(toolName: string, toolArgs: Record<string, unknown>): Promise<unknown> {
        console.log(`--- [FastMCP Client] Calling tool: ${toolName} with args:`, toolArgs);
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
            console.log(`--- FastMCP工具执行结果： ${JSON.stringify(result, null, 2)}`);

            // 处理不同类型的返回结果
            if (result.content && Array.isArray(result.content)) {
                const textContent = result.content.find(item => item.type === 'text');
                if (textContent && 'text' in textContent) {
                    return textContent.text;
                }
            }
            return result;
        } catch (error) {
            console.error(`[FastMCP Client] Failed to call tool '${toolName}':`, error);
            throw new Error(`FastMCP server failed to execute tool '${toolName}': ${error instanceof Error ? error.message : String(error)}`);
        }
    }

    /**
     * 关闭客户端连接
     */
    public async close(): Promise<void> {
        if (this.client) {
            try {
                await this.client.close();
                this.client = null;
                this.toolsCache = null;
                console.log(`--- [FastMCP Client] Connection closed ---`);
            } catch (error) {
                console.error("[FastMCP Client] Error closing connection:", error);
            }
        }
    }
}