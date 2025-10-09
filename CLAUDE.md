# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure

This is a Next.js project for LLM MCP (Model Context Protocol) tools with two main components:

- `mcp-server/` - MCP server implementation directory (currently empty)
- `user-ui/` - User interface/frontend directory (Next.js application)

## Architecture

The project follows a typical Next.js architecture with a separate server component for MCP functionality. The MCP server will handle AI model interactions and protocol implementations, while the user-ui provides the frontend interface for connecting to MCP servers and sending messages.

## User Interface (user-ui/)

The user-ui is a Next.js 15 application with:
- Modern React with TypeScript
- Tailwind CSS for styling
- Client-side rendering for interactive components
- MCP server address input field
- Message input and send functionality

## Development Setup

### User Interface
Navigate to `user-ui/` directory:
- `npm install` - Install dependencies
- `npm run dev` - Start development server (default port 3000, currently using 3003)
- `npm run build` - Build for production
- `npm run start` - Start production server
- `npm run lint` - Run ESLint

### MCP Server
The mcp-server directory is currently empty and needs to be set up.

## Common Commands

### User Interface Development
```bash
cd user-ui
npm run dev      # Start development server
npm run build    # Build for production
npm run lint     # Run linting
```

### Current Status
- ✅ User interface implemented with basic MCP client functionality
- ⏳ MCP server implementation pending
- ⏳ Integration between UI and server pending