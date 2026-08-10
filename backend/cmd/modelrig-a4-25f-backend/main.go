package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
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

const (
	operatorFlag = "KALIV_AGENT4_OPERATOR_API"
	grantFlag    = "KALIV_AGENT4_GRANT_ADMIN"
)

func main() {
	lanHost := flag.String("lan-host", "", "exact private IPv4 address for the physical Pixel listener")
	lanPort := flag.Int("lan-port", 18080, "physical Pixel listener port")
	adminPort := flag.Int("admin-port", 18081, "loopback-only pairing/grant administration port")
	workerURL := flag.String("worker-url", "http://127.0.0.1:18099", "loopback A4-25f v2 worker URL")
	dataPath := flag.String("data", "", "isolated A4-25f backend device store")
	flag.Parse()

	if err := run(*lanHost, *lanPort, *adminPort, *workerURL, *dataPath); err != nil {
		log.Fatal(err)
	}
}

func run(lanHost string, lanPort, adminPort int, workerURL, dataPath string) error {
	lanHost, err := requirePrivateIPv4(lanHost)
	if err != nil {
		return err
	}
	if err := requirePort("lan-port", lanPort); err != nil {
		return err
	}
	if err := requirePort("admin-port", adminPort); err != nil {
		return err
	}
	if lanPort == adminPort {
		return errors.New("LAN and admin ports must differ")
	}
	if strings.TrimSpace(dataPath) == "" {
		return errors.New("isolated --data path is required")
	}
	if strings.TrimSpace(os.Getenv("MODELRIG_ADMIN_KEY")) == "" {
		return errors.New("MODELRIG_ADMIN_KEY is required for A4-25f")
	}
	if err := requireLoopbackWorkerURL(workerURL); err != nil {
		return err
	}

	if err := os.Setenv(operatorFlag, "1"); err != nil {
		return err
	}
	if err := os.Setenv(grantFlag, "1"); err != nil {
		return err
	}

	st, err := store.Open(dataPath)
	if err != nil {
		return fmt.Errorf("open isolated A4-25f store: %w", err)
	}
	cfg := config.Default()
	cfg.ServerHost = lanHost
	cfg.ServerPort = lanPort
	cfg.DataPath = dataPath
	cfg.WorkerBaseURL = strings.TrimRight(workerURL, "/")
	cfg.RequestTimeout = 30 * time.Second

	worker := proxy.New(cfg.WorkerBaseURL, cfg.RequestTimeout).WithHealthPath("/healthz")
	workerSlow := proxy.New(cfg.WorkerBaseURL, 2*time.Minute).WithHealthPath("/healthz")
	// A4-25f never exercises model routes. Use a deliberately dead loopback
	// upstream so /status can report Ollama=false without contacting any external
	// destination.
	ollama := proxy.New("http://127.0.0.1:1", 2*time.Second)
	shared := httpapi.New(httpapi.Deps{
		Cfg:        cfg,
		Store:      st,
		Ollama:     ollama,
		Worker:     worker,
		WorkerSlow: workerSlow,
	})

	lanListener, err := net.Listen("tcp4", net.JoinHostPort(lanHost, strconv.Itoa(lanPort)))
	if err != nil {
		return fmt.Errorf("listen on physical LAN address: %w", err)
	}
	defer lanListener.Close()
	adminListener, err := net.Listen("tcp4", net.JoinHostPort("127.0.0.1", strconv.Itoa(adminPort)))
	if err != nil {
		return fmt.Errorf("listen on loopback admin address: %w", err)
	}
	defer adminListener.Close()

	lanServer := &http.Server{
		Handler:           lanOnlyHandler(shared),
		ReadHeaderTimeout: 10 * time.Second,
	}
	adminServer := &http.Server{
		Handler:           shared,
		ReadHeaderTimeout: 10 * time.Second,
	}
	errCh := make(chan error, 2)
	go func() {
		log.Printf("A4-25f Pixel backend listening on http://%s", lanListener.Addr())
		if err := lanServer.Serve(lanListener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- fmt.Errorf("LAN server: %w", err)
		}
	}()
	go func() {
		log.Printf("A4-25f admin backend listening on loopback port %d", adminPort)
		if err := adminServer.Serve(adminListener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- fmt.Errorf("admin server: %w", err)
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	select {
	case err := <-errCh:
		return err
	case <-sig:
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = lanServer.Shutdown(ctx)
	_ = adminServer.Shutdown(ctx)
	return nil
}

func lanOnlyHandler(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Pair claim is intentionally available to the Pixel. Pair-code minting
		// and all grant mutation remain loopback-only and are hidden rather than
		// merely relying on their inner authorization checks.
		if r.URL.Path == "/api/v1/pair/start" || strings.HasPrefix(r.URL.Path, "/api/v1/admin/") {
			http.NotFound(w, r)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func requirePrivateIPv4(raw string) (string, error) {
	host := strings.TrimSpace(raw)
	ip := net.ParseIP(host)
	if ip == nil || ip.To4() == nil {
		return "", errors.New("--lan-host must be one exact IPv4 address")
	}
	if ip.IsLoopback() || ip.IsUnspecified() || !ip.IsPrivate() {
		return "", fmt.Errorf("--lan-host must be a concrete private IPv4 address, got %q", host)
	}
	return ip.To4().String(), nil
}

func requirePort(name string, value int) error {
	if value < 1024 || value > 65535 {
		return fmt.Errorf("--%s must be between 1024 and 65535", name)
	}
	return nil
}

func requireLoopbackWorkerURL(raw string) error {
	const prefix = "http://"
	value := strings.TrimSpace(raw)
	if !strings.HasPrefix(value, prefix) {
		return errors.New("--worker-url must use http on loopback")
	}
	hostPort := strings.TrimPrefix(value, prefix)
	if strings.ContainsAny(hostPort, "/?#@") {
		return errors.New("--worker-url must be a simple loopback origin")
	}
	host, port, err := net.SplitHostPort(hostPort)
	if err != nil {
		return fmt.Errorf("invalid --worker-url: %w", err)
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return errors.New("--worker-url must target loopback")
	}
	parsedPort, err := strconv.Atoi(port)
	if err != nil {
		return errors.New("--worker-url port is invalid")
	}
	return requirePort("worker-url port", parsedPort)
}
