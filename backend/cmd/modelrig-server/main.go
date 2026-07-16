package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"modelrig/internal/config"
	"modelrig/internal/httpapi"
	"modelrig/internal/pairing"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

func main() {
	pairFlag := flag.Bool("pair", false, "mint a pairing code and exit")
	flag.Parse()

	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	// Resolve the store path before EVERY execution mode. Previously this only
	// happened on normal server startup, so `modelrig-server -pair` with the
	// server stopped wrote a relative modelrig-data.json in the caller's working
	// directory while the later server opened the exe-anchored store. The CLI
	// printed a valid-looking code that the running server could never claim.
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
			log.Printf("NOTE: MODELRIG_ADMIN_KEY unset - POST /api/v1/pair/start accepts loopback callers only (the -pair CLI). Set MODELRIG_ADMIN_KEY to allow remote pairing.")
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

// pairCLI mints a pairing code. It prefers talking to an already-running server
// on localhost (so the code lands in the live in-memory store — no dual-writer
// corruption). Only if no server answers does it fall back to writing the store
// file directly.
func pairCLI(cfg config.Config) error {
	localURL := fmt.Sprintf("http://127.0.0.1:%d", cfg.ServerPort)

	// Any HTTP response proves a server owns the port/store. Do not fall back to
	// direct file writes merely because /healthz returns a non-2xx response: that
	// would create a second writer precisely while the live process is unhealthy.
	if serverReachable(localURL) {
		code, err := requestPairStart(localURL)
		if err != nil {
			return fmt.Errorf("server is reachable but pair/start failed: %w", err)
		}
		printCode(code, cfg.PairingTTL, "issued by the running server")
		return nil
	}

	// Fallback: no server responds → write straight to the same exe-anchored store
	// normal startup uses (ResolveDataPath ran before this function).
	st, err := store.Open(cfg.DataPath)
	if err != nil {
		return err
	}
	code, err := pairing.Code()
	if err != nil {
		return err
	}
	if err := st.PutPairing(store.Pairing{Code: code, ExpiresAt: time.Now().Add(cfg.PairingTTL)}); err != nil {
		return err
	}
	printCode(code, cfg.PairingTTL, "written to store — start the server to use it")
	return nil
}

func serverReachable(baseURL string) bool {
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(baseURL + "/healthz")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return true
}

func requestPairStart(baseURL string) (string, error) {
	req, err := http.NewRequest(http.MethodPost, baseURL+"/api/v1/pair/start", nil)
	if err != nil {
		return "", err
	}
	if key := os.Getenv("MODELRIG_ADMIN_KEY"); key != "" {
		req.Header.Set("X-Admin-Key", key)
	}
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
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
