package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/mark3labs/mcp-filesystem-server/filesystemserver"
	"github.com/mark3labs/mcp-go/server"
)

type transportKind string

const (
	transportStdio          transportKind = "stdio"
	transportSSE            transportKind = "sse"
	transportStreamableHTTP transportKind = "streamable-http"
)

type appConfig struct {
	transport       transportKind
	allowedDirs     []string
	addr            string
	baseURL         string
	basePath        string
	ssePath         string
	messagePath     string
	sseKeepAlive    time.Duration
	shutdownTimeout time.Duration
	useFullURL      bool
}

func main() {
	cfg, err := parseConfig()
	if err != nil {
		log.Fatalf("configuration error: %v", err)
	}

	if len(cfg.allowedDirs) == 0 {
		fmt.Fprintf(os.Stderr, "No allowed directories configured. Provide positional arguments, --allowed-dirs, or MCP_ALLOWED_DIRECTORIES.\n")
		os.Exit(1)
	}

	mcpServer, err := filesystemserver.NewFilesystemServer(cfg.allowedDirs)
	if err != nil {
		log.Fatalf("Failed to create server: %v", err)
	}

	switch cfg.transport {
	case transportStdio:
		if err := server.ServeStdio(mcpServer); err != nil {
			log.Fatalf("Server error: %v", err)
		}
	case transportSSE:
		if err := runSSEServer(mcpServer, cfg); err != nil {
			log.Fatalf("SSE server error: %v", err)
		}
	case transportStreamableHTTP:
		if err := runStreamableHTTPServer(mcpServer, cfg); err != nil {
			log.Fatalf("streamable-http server error: %v", err)
		}
	default:
		log.Fatalf("unsupported transport %q", cfg.transport)
	}
}

func parseConfig() (appConfig, error) {
	envTransport := defaultString(os.Getenv("MCP_TRANSPORT"), string(transportStdio))
	envAddr := defaultString(os.Getenv("MCP_ADDR"), ":8080")
	envBasePath := os.Getenv("MCP_BASE_PATH")
	if envBasePath == "" {
		envBasePath = "/mcp"
	}
	envBaseURL := os.Getenv("MCP_BASE_URL")
	envSSEPath := os.Getenv("MCP_SSE_PATH")
	envMessagePath := os.Getenv("MCP_MESSAGE_PATH")
	envAllowed := os.Getenv("MCP_ALLOWED_DIRECTORIES")
	envAdditional := os.Getenv("MCP_ADDITIONAL_DIRECTORIES")

	envKeepAlive := durationFromEnv("MCP_SSE_KEEPALIVE", 0)
	envShutdown := durationFromEnv("MCP_SHUTDOWN_TIMEOUT", 10*time.Second)
	envUseFullURL := boolFromEnv("MCP_SSE_USE_FULL_URL", true)

	transportFlag := flag.String("transport", envTransport, "Transport to use: stdio, sse, or streamable-http")
	addrFlag := flag.String("addr", envAddr, "Address for network transports (sse or streamable-http)")
	baseURLFlag := flag.String("base-url", envBaseURL, "Public base URL used when advertising message endpoints (SSE)")
	basePathFlag := flag.String("base-path", envBasePath, "Base path prefix for HTTP endpoints")
	ssePathFlag := flag.String("sse-path", envSSEPath, "Relative SSE endpoint path (default /sse)")
	messagePathFlag := flag.String("message-path", envMessagePath, "Relative message endpoint path (default /message)")
	allowedDirsFlag := flag.String("allowed-dirs", envAllowed, "Comma or newline separated list of allowed directories")
	keepAliveFlag := flag.Duration("sse-keepalive", envKeepAlive, "Interval for SSE ping messages (0 to disable)")
	shutdownFlag := flag.Duration("shutdown-timeout", envShutdown, "Graceful shutdown timeout for network transports")
	useFullURLFlag := flag.Bool("sse-use-full-url", envUseFullURL, "Include the full base URL in SSE message endpoint events")

	flag.Parse()

	cfg := appConfig{
		transport:       normalizeTransport(*transportFlag),
		addr:            strings.TrimSpace(*addrFlag),
		baseURL:         strings.TrimSpace(*baseURLFlag),
		basePath:        cleanURLPath(*basePathFlag),
		ssePath:         cleanRelativePath(*ssePathFlag),
		messagePath:     cleanRelativePath(*messagePathFlag),
		sseKeepAlive:    *keepAliveFlag,
		shutdownTimeout: *shutdownFlag,
		useFullURL:      *useFullURLFlag,
	}

	cfg.allowedDirs = collectAllowedDirs(flag.Args(), *allowedDirsFlag, envAdditional)

	if cfg.transport != transportStdio {
		if cfg.addr == "" {
			cfg.addr = ":8080"
		}
	}

	return cfg, nil
}

func collectAllowedDirs(positional []string, primaryList, additionalList string) []string {
	seen := make(map[string]struct{})
	var out []string

	add := func(raw string) {
		raw = strings.TrimSpace(raw)
		if raw == "" {
			return
		}
		cleaned := filepath.Clean(raw)
		if cleaned == "." {
			cleaned = raw
		}
		if _, exists := seen[cleaned]; exists {
			return
		}
		seen[cleaned] = struct{}{}
		out = append(out, cleaned)
	}

	for _, dir := range positional {
		add(dir)
	}
	for _, dir := range splitList(primaryList) {
		add(dir)
	}
	for _, dir := range splitList(additionalList) {
		add(dir)
	}
	return out
}

func splitList(input string) []string {
	if input == "" {
		return nil
	}
	fields := strings.FieldsFunc(input, func(r rune) bool {
		switch r {
		case ',', ';', '\n', '\r':
			return true
		}
		return false
	})
	for i := range fields {
		fields[i] = strings.TrimSpace(fields[i])
	}
	return fields
}

func normalizeTransport(value string) transportKind {
	value = strings.TrimSpace(strings.ToLower(value))
	switch value {
	case "", string(transportStdio):
		return transportStdio
	case string(transportSSE):
		return transportSSE
	case "http", string(transportStreamableHTTP):
		return transportStreamableHTTP
	default:
		log.Printf("Unknown transport %q, defaulting to stdio", value)
		return transportStdio
	}
}

func cleanURLPath(path string) string {
	path = strings.TrimSpace(path)
	if path == "" {
		return ""
	}
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	if len(path) > 1 {
		path = strings.TrimRight(path, "/")
	}
	return path
}

func cleanRelativePath(path string) string {
	path = strings.TrimSpace(path)
	if path == "" {
		return ""
	}
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	return path
}

func defaultString(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}

func durationFromEnv(key string, fallback time.Duration) time.Duration {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	parsed, err := time.ParseDuration(raw)
	if err != nil {
		log.Printf("Invalid duration in %s=%q, using %s", key, raw, fallback)
		return fallback
	}
	return parsed
}

func boolFromEnv(key string, fallback bool) bool {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	switch strings.ToLower(raw) {
	case "1", "true", "yes", "y", "on":
		return true
	case "0", "false", "no", "n", "off":
		return false
	default:
		log.Printf("Invalid boolean in %s=%q, using %t", key, raw, fallback)
		return fallback
	}
}

func runSSEServer(mcpServer *server.MCPServer, cfg appConfig) error {
	opts := []server.SSEOption{}
	if cfg.baseURL != "" {
		opts = append(opts, server.WithBaseURL(cfg.baseURL))
	}
	if cfg.basePath != "" {
		opts = append(opts, server.WithStaticBasePath(cfg.basePath))
	}
	if cfg.ssePath != "" {
		opts = append(opts, server.WithSSEEndpoint(cfg.ssePath))
	}
	if cfg.messagePath != "" {
		opts = append(opts, server.WithMessageEndpoint(cfg.messagePath))
	}
	opts = append(opts, server.WithUseFullURLForMessageEndpoint(cfg.useFullURL))
	if cfg.sseKeepAlive > 0 {
		opts = append(opts, server.WithKeepAliveInterval(cfg.sseKeepAlive))
	} else {
		opts = append(opts, server.WithKeepAlive(false))
	}

	sseServer := server.NewSSEServer(mcpServer, opts...)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	errCh := make(chan error, 1)
	go func() {
		log.Printf("Starting SSE server on %s (basePath=%s)", cfg.addr, cfg.basePath)
		if err := sseServer.Start(cfg.addr); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
			return
		}
		errCh <- nil
	}()

	select {
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.shutdownTimeout)
		defer cancel()
		log.Printf("Shutting down SSE server...")
		if err := sseServer.Shutdown(shutdownCtx); err != nil && !errors.Is(err, context.Canceled) && !errors.Is(err, http.ErrServerClosed) {
			return err
		}
		return <-errCh
	case err := <-errCh:
		return err
	}
}

func runStreamableHTTPServer(mcpServer *server.MCPServer, cfg appConfig) error {
	opts := []server.StreamableHTTPOption{}
	if cfg.basePath != "" {
		opts = append(opts, server.WithEndpointPath(cfg.basePath))
	}

	httpServer := server.NewStreamableHTTPServer(mcpServer, opts...)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	errCh := make(chan error, 1)
	go func() {
		log.Printf("Starting streamable-http server on %s (endpoint=%s)", cfg.addr, cfg.basePath)
		if err := httpServer.Start(cfg.addr); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
			return
		}
		errCh <- nil
	}()

	select {
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.shutdownTimeout)
		defer cancel()
		log.Printf("Shutting down streamable-http server...")
		if err := httpServer.Shutdown(shutdownCtx); err != nil && !errors.Is(err, context.Canceled) && !errors.Is(err, http.ErrServerClosed) {
			return err
		}
		return <-errCh
	case err := <-errCh:
		return err
	}
}
