# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Next.js project for LLM MCP (Model Context Protocol) tools featuring:
- **user-ui/**: Next.js frontend application for MCP server interaction
- **mcp-server-fastapi/**: FastAPI-based MCP server implementation  
- **mcp-server-fastmcp/**: FastMCP-based MCP server implementation (active development)

The project implements a tool calling system for apartment management data, with capabilities for occupancy calculations, guest data queries, room information retrieval, and service order management.

## Architecture

### Frontend (user-ui/)
- **Next.js 15** with React 19 and TypeScript
- **Turbopack** for fast development builds
- **Multi-provider LLM support**: Google AI and Ollama integration
- **Factory pattern** for dynamic provider instantiation
- **Tool client** for MCP server communication

### Backend Servers
- **FastAPI Server**: REST API with tool registry pattern
- **FastMCP Server**: Native MCP implementation with apartment data tools

## Common Commands

### User Interface Development
```bash
cd user-ui
npm run dev      # Start development server on port 3003
npm run build    # Build for production using Turbopack
npm run start    # Start production server
npm run lint     # Run ESLint
```

### MCP Server Development

#### FastAPI Server
```bash
cd mcp-server-fastapi
pip install -r requirements.txt
python main.py  # Runs on default port 8000
```

#### FastMCP Server
```bash
cd mcp-server-fastmcp
pip install -r requirements.txt
python main.py  # Runs on port 8001
```

### Development with MCP CLI
For FastMCP development, use the official MCP CLI for debugging:
```bash
cd mcp-server-fastmcp
pip install mcp[cli]
mcp dev main.py  # Opens browser debugger
```

## Key Components

### Frontend Architecture
- **Model Factory** (`src/lib/llm/model-factory.ts`): Dynamic provider instantiation
- **Tool Client** (`src/lib/llm/tool-client.ts`): MCP server communication with caching
- **Model Service** (`src/lib/llm/model-service.ts`): Business logic orchestration with proxy support
- **Base Provider** (`src/lib/llm/base-provider.ts`): Abstract interface for LLM providers

### MCP Tools Available
1. **calculate_occupancy**: Calculate occupancy rates for date ranges
2. **occupancy_details**: Analyze room type performance and rental efficiency
3. **query_guest**: Retrieve guest information by ID
4. **query_checkins**: Get check-in records by date range and status
5. **query_by_room**: Find occupancy data by room numbers
6. **query_orders**: Retrieve service orders by room
7. **advanced_query_service**: Complex service order queries with filters
8. **get_current_time**: System time utility
9. **calculate_expression**: Safe mathematical expression evaluation

## Development Setup

### Environment Variables
The UI supports proxy configuration:
- `HTTPS_PROXY` or `HTTP_PROXY`: Global proxy for API requests

### Data Dependencies
- **XML data files**: master_base.xml, master_guest.xml, lease_service_order.xml
- **Pandas**: Data processing and analysis
- **LXML**: XML file parsing
- **RestrictedPython**: Safe expression evaluation

## MCP Protocol Implementation

### FastAPI Server
- REST API following OpenAI Function Calling schema
- Tool discovery endpoint: `/tools`
- Tool execution endpoint: `/call`
- Health check endpoint: `/`

### FastMCP Server  
- Native MCP protocol implementation
- SSE (Server-Sent Events) transport
- Browser debugging support via MCP CLI
- Comprehensive apartment management toolset