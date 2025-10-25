// lib/llm/tools/fastmcp-sse-client.ts

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js';
import { BaseFastMCPClient } from './base-fastmcp-client';

/**
 * FastMCP SSE模式客户端实现
 */
export class FastMCPSSEClient extends BaseFastMCPClient {
    private client: Client | null = null;

    constructor(serverUrl: string) {
        super(serverUrl);
    }

    protected async initializeClient(): Promise<Client> {
        if (this.client) {
            return this.client;
        }

        try {
            const sseUrl = `${this.serverUrl}/sse`;
            console.log(`--- [FastMCP SSE Client] Initializing connection to ${sseUrl} ---`);

            // 创建SSE传输连接，添加超时控制
            const transport = new SSEClientTransport(new URL(sseUrl));

            // 创建MCP客户端
            this.client = new Client(
                {
                    name: 'nextjs-llm-sse-client',
                    version: '1.0.0',
                },
                {
                    capabilities: {}
                }
            );

            // 设置连接超时
            const connectPromise = this.client.connect(transport);
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('MCP SSE connection timeout')), 10000);
            });

            // 连接到服务器
            await Promise.race([connectPromise, timeoutPromise]);
            console.log(`--- [FastMCP SSE Client] Successfully connected to MCP server ---`);

            return this.client;
        } catch (error) {
            console.error("[FastMCP SSE Client] Failed to initialize client:", error);
            this.client = null;
            throw new Error(`Failed to initialize MCP SSE client: ${error instanceof Error ? error.message : String(error)}`);
        }
    }

    public async close(): Promise<void> {
        if (this.client) {
            try {
                await this.client.close();
                this.client = null;
                this.toolsCache = null;
                console.log(`--- [FastMCP SSE Client] Connection closed ---`);
            } catch (error) {
                console.error("[FastMCP SSE Client] Error closing connection:", error);
            }
        }
    }

    protected getClientType(): string {
        return 'FastMCP SSE';
    }
}