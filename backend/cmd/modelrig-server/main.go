package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"modelrig/internal/config"
	"modelrig/internal/httpapi"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

func main() {
	pairFlag := flag.Bool("pair", false, "mint a pairing code through the running server and exit")
	flag.Parse()

	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	// Keep the server's store path stable across launch directories. Pair mode no
	// longer opens this path at all: the running backend is the sole supported
	// writer for pairing, device and grant state.
	cfg.ResolveDataPath()

	if *pairFlag {
		if err := pairCLI(cfg); err != nil {
			log.Fatalf("pair: %v", err)
		}
		return
	}

	log.Printf("  device store: %s", cfg.DataPath)
	st, err := store.Open(cfg.DataPath)
	if err != nil {
		log.Fatalf("store: %v", err)
	}

	ollamaClient := proxy.New(cfg.OllamaBaseURL, cfg.RequestTimeout).WithHealthPath("/api/tags").WithAuthToken(cfg.OllamaKey)
	workerClient := proxy.New(cfg.WorkerBaseURL, cfg.RequestTimeout).WithHealthPath("/healthz")
	// Voice turns and large ingests legitimately exceed the chat timeout:
	// the first voice turn loads Whisper large-v3 into VRAM before the LLM
	// even runs. The shortest timeout in the chain wins, so the server
	// needs its own long-timeout client, not just the Android app.
	workerSlowClient := proxy.New(cfg.WorkerBaseURL, 10*time.Minute).WithHealthPath("/healthz")

	handler := httpapi.New(httpapi.Deps{
		Cfg:        cfg,
		Store:      st,
		Ollama:     ollamaClient,
		Worker:     workerClient,
		WorkerSlow: workerSlowClient,
	})

	httpServer := &http.Server{
		Addr:              cfg.Addr(),
		Handler:           handler,
		ReadHeaderTimeout: 10 * time.Second,
	}

	stop := make(chan struct{})
	go purgeLoop(st, stop)

	go func() {
		log.Printf("ModelRig server %s listening on http://%s", config.Version, cfg.Addr())
		log.Printf("  ollama upstream: %s", cfg.OllamaBaseURL)
		log.Printf("  worker upstream: %s", cfg.WorkerBaseURL)
		if cfg.IsLoopback() {
			log.Printf("WARNING: bound to loopback (%s). Android/LAN clients CANNOT reach this.", cfg.ServerHost)
			log.Printf("         Set MODELRIG_HOST=0.0.0.0 or a Tailscale IP, then restart.")
		}
		if os.Getenv("MODELRIG_ADMIN_KEY") == "" {
			log.Printf("NOTE: MODELRIG_ADMIN_KEY unset - POST /api/v1/pair/start accepts loopback callers only (the -pair CLI). Set MODELRIG_ADMIN_KEY to allow pairing through a concrete LAN/Tailscale bind.")
		}
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("listen: %v", err)
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	log.Println("shutting down...")
	close(stop)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = httpServer.Shutdown(ctx)
}

func purgeLoop(st *store.Store, stop <-chan struct{}) {
	t := time.NewTicker(30 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-t.C:
			st.PurgeExpiredPairings(time.Now())
		case <-stop:
			return
		}
	}
}

// pairCLI mints a pairing code exclusively through the running backend. The CLI
// never opens cfg.DataPath: pairing, device and agent4:read grant mutations must
// share the backend's single Store instance so one process cannot overwrite
// another process's newer security state.
func pairCLI(cfg config.Config) error {
	baseURL, err := pairServerBaseURL(cfg)
	if err != nil {
		return err
	}
	code, err := requestPairStart(baseURL)
	if err != nil {
		return fmt.Errorf(
			"running ModelRig server at %s is required for pairing: %w",
			baseURL,
			err,
		)
	}
	printCode(code, cfg.PairingTTL, "issued by the running server")
	return nil
}

// pairServerBaseURL resolves the local process address that corresponds to the
// configured listener. Wildcard binds are reached over loopback; a concrete
// LAN/Tailscale bind is reached through that exact configured address. This
// avoids mistaking an unrelated loopback listener for the live store owner.
func pairServerBaseURL(cfg config.Config) (string, error) {
	host := strings.TrimSpace(cfg.ServerHost)
	switch host {
	case "":
		return "", fmt.Errorf("MODELRIG_HOST/server.host is required for pairing")
	case "0.0.0.0":
		host = "127.0.0.1"
	case "::":
		host = "::1"
	}
	if cfg.ServerPort <= 0 || cfg.ServerPort > 65535 {
		return "", fmt.Errorf("invalid ModelRig server port %d", cfg.ServerPort)
	}
	return "http://" + net.JoinHostPort(host, strconv.Itoa(cfg.ServerPort)), nil
}

func requestPairStart(baseURL string) (string, error) {
	req, err := http.NewRequest(http.MethodPost, baseURL+"/api/v1/pair/start", nil)
	if err != nil {
		return "", err
	}
	if key := os.Getenv("MODELRIG_ADMIN_KEY"); key != "" {
		req.Header.Set("X-Admin-Key", key)
	}
	client := &http.Client{
		Timeout: 3 * time.Second,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}
	var out struct {
		Code string `json:"code"`
	}
	if err := json.Unmarshal(body, &out); err != nil {
		return "", err
	}
	if out.Code == "" {
		return "", fmt.Errorf("response contained no code")
	}
	return out.Code, nil
}

func printCode(code string, ttl time.Duration, note string) {
	fmt.Printf("\n  ModelRig pairing code:  %s\n", code)
	fmt.Printf("  Valid for:              %.0f min  (%s)\n\n", ttl.Minutes(), note)
	fmt.Printf("  Enter this code in the ModelRig desktop or Android client.\n\n")
}
