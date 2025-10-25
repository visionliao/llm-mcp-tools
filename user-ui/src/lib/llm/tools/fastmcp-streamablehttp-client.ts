// lib/llm/tools/fastmcp-streamablehttp-client.ts

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { BaseFastMCPClient } from './base-fastmcp-client';

/**
 * FastMCP StreamableHTTP模式客户端实现
 */
export class FastMCPStreamableHttpClient extends BaseFastMCPClient {
    private client: Client | null = null;

    constructor(serverUrl: string) {
        super(serverUrl);
    }

    protected async initializeClient(): Promise<Client> {
        if (this.client) {
            return this.client;
        }

        try {
            console.log(`--- [FastMCP StreamableHTTP Client] Initializing connection to ${this.serverUrl} ---`);

            // 创建StreamableHTTP传输连接，指定正确的/mcp路径
            const mcpUrl = new URL(this.serverUrl);
            // 确保路径以/mcp结尾，这是FastMCP StreamableHTTP的默认端点
            if (!mcpUrl.pathname.endsWith('/mcp')) {
                mcpUrl.pathname = mcpUrl.pathname.replace(/\/$/, '') + '/mcp';
            }
            const transport = new StreamableHTTPClientTransport(mcpUrl);

            // 创建MCP客户端
            this.client = new Client(
                {
                    name: 'nextjs-llm-streamablehttp-client',
                    version: '1.0.0',
                },
                {
                    capabilities: {}
                }
            );

            // 设置连接超时
            const connectPromise = this.client.connect(transport);
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('MCP StreamableHTTP connection timeout')), 10000);
            });

            // 连接到服务器
            await Promise.race([connectPromise, timeoutPromise]);
            console.log(`--- [FastMCP StreamableHTTP Client] Successfully connected to MCP server ---`);

            return this.client;
        } catch (error) {
            console.error("[FastMCP StreamableHTTP Client] Failed to initialize client:", error);
            this.client = null;
            throw new Error(`Failed to initialize MCP StreamableHTTP client: ${error instanceof Error ? error.message : String(error)}`);
        }
    }

    public async close(): Promise<void> {
        if (this.client) {
            try {
                await this.client.close();
                this.client = null;
                this.toolsCache = null;
                console.log(`--- [FastMCP StreamableHTTP Client] Connection closed ---`);
            } catch (error) {
                console.error("[FastMCP StreamableHTTP Client] Error closing connection:", error);
            }
        }
    }

    protected getClientType(): string {
        return 'FastMCP StreamableHTTP';
    }
}