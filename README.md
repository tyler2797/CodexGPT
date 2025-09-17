# MCP Filesystem Server

This MCP server provides secure, read/write access to a curated portion of the
filesystem through the [Model Context Protocol](https://modelcontextprotocol.io/).
It now supports both the traditional stdio transport **and** the HTTP transports
required for [Claude web custom connectors](https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp).

## Components

### Resources

- **file://** – *File System*: Access to files and directories on the local file system.

### Tools

#### File Operations

- **read_file** – Read the complete contents of a file. `path` (required).
- **read_multiple_files** – Batch read multiple files. `paths` (required array of strings).
- **write_file** – Create or overwrite a file. `path`, `content` (required).
- **copy_file** – Copy files or directories. `source`, `destination` (required).
- **move_file** – Move or rename files or directories. `source`, `destination` (required).
- **delete_file** – Delete files or directories. `path` (required), `recursive` (optional).
- **modify_file** – Regex/smart find-replace updates. `path`, `find`, `replace` (required).

#### Directory Operations

- **list_directory** – List files in a directory. `path` (required).
- **create_directory** – Create a directory (idempotent). `path` (required).
- **tree** – Hierarchical JSON tree. `path` (required), `depth`, `follow_symlinks` (optional).

#### Search & Metadata

- **search_files** – Glob search by filename. `path`, `pattern` (required).
- **search_within_files** – Substring search inside files. `path`, `substring` (required), `depth`, `max_results` (optional).
- **get_file_info** – Rich metadata (size, mode, timestamps, MIME). `path` (required).
- **list_allowed_directories** – Returns the directories exposed by this server.

## Transports & Configuration

The binary understands three transports. Choose one with `--transport` or the
`MCP_TRANSPORT` environment variable.

| Transport            | Description                                                     |
|----------------------|-----------------------------------------------------------------|
| `stdio` *(default)*  | Classic MCP over stdio. Suitable for Claude Desktop / local use.|
| `sse`                | Server-Sent Events + JSON-RPC POST endpoints for Claude Web.    |
| `streamable-http`    | Implements the 2025-03-26 streamable HTTP draft transport.      |

Common configuration knobs can be provided as flags or environment variables:

| Flag / Env                              | Purpose / Example                                                   |
|----------------------------------------|---------------------------------------------------------------------|
| `--allowed-dirs`, `MCP_ALLOWED_DIRECTORIES` | Comma/newline separated allowlist. e.g. `/srv/shared,/srv/docs`. |
| `MCP_ADDITIONAL_DIRECTORIES`            | Extra directories appended to the allowlist.                       |
| `--transport`, `MCP_TRANSPORT`          | `stdio`, `sse`, or `streamable-http`.                              |
| `--addr`, `MCP_ADDR`                    | Listen address for HTTP transports (default `:8080`).              |
| `--base-path`, `MCP_BASE_PATH`          | URL prefix for HTTP endpoints (default `/mcp`).                    |
| `--base-url`, `MCP_BASE_URL`            | Public origin (e.g. `https://files.example.com`). Required when proxies terminate TLS. |
| `--sse-path`, `MCP_SSE_PATH`            | Override SSE endpoint segment (default `/sse`).                     |
| `--message-path`, `MCP_MESSAGE_PATH`    | Override message endpoint segment (default `/message`).             |
| `--sse-keepalive`, `MCP_SSE_KEEPALIVE`  | Interval for `ping` keepalives (e.g. `25s`). `0` disables.          |
| `--sse-use-full-url`, `MCP_SSE_USE_FULL_URL` | Include the full base URL in SSE endpoint events (default `true`). |
| `--shutdown-timeout`, `MCP_SHUTDOWN_TIMEOUT` | Graceful shutdown timeout (default `10s`).                        |

All directory inputs are deduplicated and normalised, and the underlying server
still enforces its own safety checks (symlink guards, traversal protection, size
limits, MIME sniffing, etc.).

## Running the Server

### Stdio (local workflows)

```bash
./server --transport stdio /path/to/project /path/to/docs
```

Add the command to your MCP-enabled client:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "./server",
      "args": ["--transport", "stdio", "/path/to/project"]
    }
  }
}
```

### SSE for Claude Web custom connectors

```bash
export MCP_TRANSPORT=sse
export MCP_ALLOWED_DIRECTORIES=/srv/shared,/srv/docs
export MCP_BASE_URL=https://files.example.com
export MCP_BASE_PATH=/mcp
export MCP_SSE_KEEPALIVE=25s
./server --addr :8080
```

This exposes:

- `GET https://files.example.com/mcp/sse` – long-lived SSE stream. The first
  event advertises the message endpoint with a `sessionId` query parameter.
- `POST https://files.example.com/mcp/message?sessionId=<id>` – JSON-RPC request
  channel used by Claude. Responses are returned over the SSE stream with status
  `202 Accepted`, matching Anthropic’s remote connector spec.

When deploying behind a reverse proxy/ingress, ensure:

1. TLS certificates are valid (Claude requires HTTPS).
2. The proxy forwards the `/mcp/sse` stream without buffering.
3. `MCP_BASE_URL` reflects the public origin so Claude receives the correct
   message endpoint.
4. Only the desired directories are mounted inside the container/VM.

After the server is reachable, add the connector inside Claude Web:

1. **Settings → Connectors → Add custom connector**.
2. Enter the base URL (`https://files.example.com/mcp`).
3. Approve the connection; Claude will perform the SSE handshake automatically.

### Streamable HTTP (preview)

For clients that understand the `streamable-http` transport:

```bash
./server --transport streamable-http --addr :8080 --base-path /mcp --allowed-dirs /srv/shared
```

The endpoints are served under `/mcp` following the 2025-03-26 MCP draft spec.
Claude Web currently prefers SSE, but this transport is available for future
compatibility and automated testing via the MCP inspector.

## Docker

Build locally:

```bash
docker build -t mcp-filesystem-server .
```

Run with stdio (default):

```bash
docker run -it --rm -v "$PWD:/workspace" mcp-filesystem-server --transport stdio /workspace
```

Run as a remote SSE connector:

```bash
docker run -d --name mcp-fs \
  -e MCP_TRANSPORT=sse \
  -e MCP_ALLOWED_DIRECTORIES=/data/projects \
  -e MCP_BASE_URL=https://files.example.com \
  -p 8080:8080 \
  -v /srv/projects:/data/projects:ro \
  mcp-filesystem-server --addr :8080
```

> **Security tip:** expose the container through a reverse proxy that enforces
> authentication or IP allowlists, and avoid mounting sensitive paths.

## Library Usage

You can embed the handler inside another Go process:

```go
fs, err := filesystemserver.NewFilesystemServer([]string{"/srv/projects"})
if err != nil {
        log.Fatal(err)
}
// Attach fs to your own MCP server or reuse the tools directly.
```

## Testing

```bash
go test ./...
```

The test suite covers the tool handlers plus in-process transport checks for
stdio and SSE.

## Further Reading

- Anthropic: [Getting Started with Custom Connectors Using Remote MCP](https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp)
- Anthropic: [Building Custom Connectors via Remote MCP Servers](https://support.claude.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers)
- MCP Spec: [Basic Transports 2024-11-05](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports)

