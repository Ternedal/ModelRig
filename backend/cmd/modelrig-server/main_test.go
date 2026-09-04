package main

import (
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"modelrig/internal/config"
	"modelrig/internal/httpapi"
	"modelrig/internal/store"
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

func TestPairServerBaseURLUsesConfiguredOwnerAddress(t *testing.T) {
	tests := []struct {
		name string
		host string
		port int
		want string
	}{
		{name: "loopback", host: "127.0.0.1", port: 8080, want: "http://127.0.0.1:8080"},
		{name: "wildcard ipv4", host: "0.0.0.0", port: 8081, want: "http://127.0.0.1:8081"},
		{name: "wildcard ipv6", host: "::", port: 8082, want: "http://[::1]:8082"},
		{name: "tailscale", host: "100.64.12.34", port: 8443, want: "http://100.64.12.34:8443"},
		{name: "lan", host: "192.168.50.9", port: 9000, want: "http://192.168.50.9:9000"},
		{name: "ipv6 concrete", host: "fd7a:115c:a1e0::7", port: 8080, want: "http://[fd7a:115c:a1e0::7]:8080"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := config.Default()
			cfg.ServerHost = tt.host
			cfg.ServerPort = tt.port
			got, err := pairServerBaseURL(cfg)
			if err != nil {
				t.Fatalf("pairServerBaseURL: %v", err)
			}
			if got != tt.want {
				t.Fatalf("got %q, want %q", got, tt.want)
			}
		})
	}
}

func TestPairCLIOfflineFailsClosedWithoutTouchingStore(t *testing.T) {
	dataPath := filepath.Join(t.TempDir(), "must-not-be-created.json")
	cfg := config.Default()
	cfg.ServerHost = "127.0.0.1"
	cfg.ServerPort = unusedLoopbackPort(t)
	cfg.DataPath = dataPath

	if err := pairCLI(cfg); err == nil {
		t.Fatal("offline pair must require the running backend")
	}
	if _, err := os.Stat(dataPath); !os.IsNotExist(err) {
		t.Fatalf("offline pair touched device store; stat error = %v", err)
	}
}

func TestPairCLIReachableFailureNeverFallsBackToStore(t *testing.T) {
	port, closeFn := loopbackServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/pair/start" {
			http.NotFound(w, r)
			return
		}
		http.Error(w, "pairing unavailable", http.StatusForbidden)
	}))
	defer closeFn()

	dataPath := filepath.Join(t.TempDir(), "must-not-be-created.json")
	cfg := config.Default()
	cfg.ServerHost = "127.0.0.1"
	cfg.ServerPort = port
	cfg.DataPath = dataPath

	if err := pairCLI(cfg); err == nil {
		t.Fatal("reachable server with a failed pair endpoint must return an error")
	}
	if _, err := os.Stat(dataPath); !os.IsNotExist(err) {
		t.Fatalf("pairCLI fell back to a second store writer; stat error = %v", err)
	}
}

func TestPairCLISuccessUsesServerAndNeverTouchesConfiguredStore(t *testing.T) {
	port, closeFn := loopbackServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/pair/start" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"code":"ABCD-EFGH"}`))
	}))
	defer closeFn()

	dataPath := filepath.Join(t.TempDir(), "sentinel.json")
	const sentinel = "backend-owned-state\n"
	if err := os.WriteFile(dataPath, []byte(sentinel), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg := config.Default()
	cfg.ServerHost = "127.0.0.1"
	cfg.ServerPort = port
	cfg.DataPath = dataPath
	cfg.PairingTTL = time.Minute

	if err := pairCLI(cfg); err != nil {
		t.Fatalf("pairCLI: %v", err)
	}
	got, err := os.ReadFile(dataPath)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != sentinel {
		t.Fatalf("pairCLI modified configured store directly: %q", string(got))
	}
}

func TestRequestPairStartDoesNotFollowRedirect(t *testing.T) {
	var redirected atomic.Int32
	targetPort, targetClose := loopbackServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		redirected.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"code":"LEAK-CODE"}`))
	}))
	defer targetClose()

	redirectPort, redirectClose := loopbackServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(
			w,
			r,
			"http://127.0.0.1:"+strconv.Itoa(targetPort)+"/api/v1/pair/start",
			http.StatusTemporaryRedirect,
		)
	}))
	defer redirectClose()

	if _, err := requestPairStart("http://127.0.0.1:" + strconv.Itoa(redirectPort)); err == nil {
		t.Fatal("redirect response must fail closed")
	}
	if redirected.Load() != 0 {
		t.Fatal("pairing client followed a redirect to another authority")
	}
}

func TestPairAndGrantRevokeShareOneLiveStoreWriter(t *testing.T) {
	t.Setenv("KALIV_AGENT4_GRANT_ADMIN", "1")
	t.Setenv("MODELRIG_ADMIN_KEY", "test-admin-key")

	dataPath := filepath.Join(t.TempDir(), "modelrig-data.json")
	st, err := store.Open(dataPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := st.AddDevice(store.Device{
		ID:        "device-1",
		Name:      "pixel",
		TokenHash: "deadbeef",
		CreatedAt: time.Now(),
		LastSeen:  time.Now(),
	}); err != nil {
		t.Fatal(err)
	}

	cfg := config.Default()
	cfg.DataPath = dataPath
	cfg.PairingTTL = time.Minute
	handler := httpapi.New(httpapi.Deps{Cfg: cfg, Store: st})
	srv := httptest.NewServer(handler)
	defer srv.Close()

	parsed, err := url.Parse(srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	port, err := strconv.Atoi(parsed.Port())
	if err != nil {
		t.Fatal(err)
	}
	cfg.ServerHost = parsed.Hostname()
	cfg.ServerPort = port

	mutateGrant := func(method string) error {
		req, err := http.NewRequest(
			method,
			srv.URL+"/api/v1/admin/devices/device-1/grants/agent4-read",
			nil,
		)
		if err != nil {
			return err
		}
		req.Header.Set("X-Admin-Key", "test-admin-key")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			return &statusError{status: resp.StatusCode}
		}
		return nil
	}

	runTogether := func(grantMethod string) {
		t.Helper()
		var wg sync.WaitGroup
		errs := make(chan error, 2)
		wg.Add(2)
		go func() {
			defer wg.Done()
			errs <- pairCLI(cfg)
		}()
		go func() {
			defer wg.Done()
			errs <- mutateGrant(grantMethod)
		}()
		wg.Wait()
		close(errs)
		for err := range errs {
			if err != nil {
				t.Fatalf("concurrent mutation failed: %v", err)
			}
		}
	}

	runTogether(http.MethodPut)
	reloaded, err := store.Open(dataPath)
	if err != nil {
		t.Fatal(err)
	}
	devices := reloaded.Devices()
	if len(devices) != 1 || !devices[0].HasGrant("agent4:read") {
		t.Fatalf("grant was lost after concurrent pair: %+v", devices)
	}
	if got := persistedPairingCount(t, dataPath); got != 1 {
		t.Fatalf("pairing state lost after concurrent grant: got %d pairings, want 1", got)
	}

	runTogether(http.MethodDelete)
	reloaded, err = store.Open(dataPath)
	if err != nil {
		t.Fatal(err)
	}
	devices = reloaded.Devices()
	if len(devices) != 1 || devices[0].HasGrant("agent4:read") {
		t.Fatalf("revoke was lost after concurrent pair: %+v", devices)
	}
	if got := persistedPairingCount(t, dataPath); got != 2 {
		t.Fatalf("pairing state lost after concurrent revoke: got %d pairings, want 2", got)
	}
}

type statusError struct {
	status int
}

func (e *statusError) Error() string {
	return "unexpected HTTP status " + strconv.Itoa(e.status)
}

func persistedPairingCount(t *testing.T, path string) int {
	t.Helper()
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var state struct {
		Pairings map[string]json.RawMessage `json:"pairings"`
	}
	if err := json.Unmarshal(body, &state); err != nil {
		t.Fatal(err)
	}
	return len(state.Pairings)
}
