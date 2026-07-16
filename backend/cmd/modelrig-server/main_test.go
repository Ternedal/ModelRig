package main

import (
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"modelrig/internal/config"
)

func loopbackServer(t *testing.T, handler http.Handler) (port int, closeFn func()) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := &http.Server{Handler: handler}
	go func() { _ = srv.Serve(ln) }()
	return ln.Addr().(*net.TCPAddr).Port, func() {
		_ = srv.Close()
		_ = ln.Close()
	}
}

func unusedLoopbackPort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	_ = ln.Close()
	return port
}

func TestServerReachableCountsAnyHTTPResponse(t *testing.T) {
	port, closeFn := loopbackServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "temporarily unhealthy", http.StatusServiceUnavailable)
	}))
	defer closeFn()

	if !serverReachable("http://127.0.0.1:" + strconv.Itoa(port)) {
		t.Fatal("a 503 response still proves a live process owns the server port")
	}
}

func TestPairCLIRefusesSecondWriterWhenServerIsReachable(t *testing.T) {
	port, closeFn := loopbackServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/healthz":
			http.Error(w, "unhealthy", http.StatusServiceUnavailable)
		case "/api/v1/pair/start":
			http.Error(w, "pairing unavailable", http.StatusForbidden)
		default:
			http.NotFound(w, r)
		}
	}))
	defer closeFn()

	dataPath := filepath.Join(t.TempDir(), "must-not-be-created.json")
	cfg := config.Default()
	cfg.ServerPort = port
	cfg.DataPath = dataPath

	if err := pairCLI(cfg); err == nil {
		t.Fatal("reachable server with a failed pair endpoint must return an error")
	}
	if _, err := os.Stat(dataPath); !os.IsNotExist(err) {
		t.Fatalf("pairCLI fell back to a second store writer; stat error = %v", err)
	}
}

func TestPairCLIOfflineWritesTheConfiguredStore(t *testing.T) {
	dataPath := filepath.Join(t.TempDir(), "resolved", "modelrig-data.json")
	if err := os.MkdirAll(filepath.Dir(dataPath), 0o755); err != nil {
		t.Fatal(err)
	}
	cfg := config.Default()
	cfg.ServerPort = unusedLoopbackPort(t)
	cfg.DataPath = dataPath
	cfg.PairingTTL = time.Minute

	if err := pairCLI(cfg); err != nil {
		t.Fatalf("offline pair failed: %v", err)
	}
	info, err := os.Stat(dataPath)
	if err != nil {
		t.Fatalf("configured store was not written: %v", err)
	}
	if info.Size() == 0 {
		t.Fatal("configured store file is empty")
	}
}
