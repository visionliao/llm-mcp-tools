// lib/llm/tools/fastmcp-client-factory.ts

import { BaseFastMCPClient } from './base-fastmcp-client';
import { FastMCPSSEClient } from './fastmcp-sse-client';
import { FastMCPStreamableHttpClient } from './fastmcp-streamablehttp-client';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

/**
 * FastMCP客户端工厂类
 * 负责根据URL和协议类型创建合适的客户端实例
 */
export class FastMCPClientFactory {
    /**
     * 检测服务器支持的FastMCP协议类型
     * @param serverUrl 服务器URL
     * @returns 检测到的协议类型 ('sse' | 'streamablehttp' | undefined)
     */
    public static async detectProtocolType(serverUrl: string): Promise<'sse' | 'streamablehttp' | undefined> {
        try {
            console.log(`--- [Protocol Detection] Detecting FastMCP protocol for ${serverUrl} ---`);

            // 优先尝试检测StreamableHTTP协议
            try {
                // 创建一个临时的MCP客户端来测试连接
                const testClient = new Client(
                    {
                        name: 'protocol-detector',
                        version: '1.0.0'
                    },
                    {
                        capabilities: {}
                    }
                );

                // 创建StreamableHTTP传输（使用正确的/mcp端点）
                const mcpUrl = new URL(serverUrl);
                // 确保路径以/mcp结尾，这是FastMCP StreamableHTTP的默认端点
                if (!mcpUrl.pathname.endsWith('/mcp')) {
                    mcpUrl.pathname = mcpUrl.pathname.replace(/\/$/, '') + '/mcp';
                }
                const transport = new StreamableHTTPClientTransport(mcpUrl);

                // 尝试连接（带超时）
                try {
                    const connectPromise = testClient.connect(transport);
                    const timeoutPromise = new Promise((_, reject) => {
                        setTimeout(() => reject(new Error('StreamableHTTP connection timeout')), 5000);
                    });

                    await Promise.race([connectPromise, timeoutPromise]);

                    // 如果连接成功，清理并返回
                    await testClient.close();
                    console.log(`--- [Protocol Detection] StreamableHTTP connection successful, detected as StreamableHTTP protocol ---`);
                    return 'streamablehttp';
                } catch (connectionError) {
                    // 确保在连接失败时关闭客户端
                    try {
                        await testClient.close();
                    } catch (closeError) {
                        // 忽略关闭错误
                    }
                    throw connectionError;
                }
            } catch (streamableError) {
                console.log(`--- [Protocol Detection] StreamableHTTP connection test failed: ${streamableError instanceof Error ? streamableError.message : String(streamableError)} ---`);
            }

            // 然后尝试检测SSE端点
            const sseUrl = `${serverUrl}/sse`;
            try {
                const sseResponse = await fetch(sseUrl, {
                    method: 'GET',
                    headers: { 'Accept': 'text/event-stream' },
                    signal: AbortSignal.timeout(5000) // 5秒超时
                });

                if (sseResponse.ok || sseResponse.status === 200) {
                    console.log(`--- [Protocol Detection] SSE endpoint available, detected as SSE protocol ---`);
                    return 'sse';
                }
            } catch (sseError) {
                console.log(`--- [Protocol Detection] SSE endpoint test failed: ${sseError instanceof Error ? sseError.message : String(sseError)} ---`);
            }

            console.log(`--- [Protocol Detection] Could not determine FastMCP protocol type ---`);
            return undefined;
        } catch (error) {
            console.error('[Protocol Detection] Protocol detection failed:', error);
            return undefined;
        }
    }

    /**
     * 创建FastMCP客户端实例
     * @param serverUrl 服务器URL
     * @param protocolType 可选的协议类型，如果未提供则自动检测
     * @returns FastMCP客户端实例
     */
    public static async createClient(
        serverUrl: string, 
        protocolType?: 'sse' | 'streamablehttp'
    ): Promise<BaseFastMCPClient | null> {
        try {
            // 如果没有指定协议类型，自动检测
            if (!protocolType) {
                protocolType = await this.detectProtocolType(serverUrl);
                if (!protocolType) {
                    console.log(`--- [Factory] Could not detect FastMCP protocol for ${serverUrl} ---`);
                    return null;
                }
            }

            console.log(`--- [Factory] Creating FastMCP ${protocolType.toUpperCase()} client for ${serverUrl} ---`);

            // 根据协议类型创建相应的客户端
            switch (protocolType) {
                case 'streamablehttp':
                    return new FastMCPStreamableHttpClient(serverUrl);
                case 'sse':
                    return new FastMCPSSEClient(serverUrl);
                default:
                    console.error(`--- [Factory] Unsupported protocol type: ${protocolType} ---`);
                    return null;
            }
        } catch (error) {
            console.error('[Factory] Failed to create FastMCP client:', error);
            return null;
        }
    }
}