package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

// The Go server is a proxy and nothing more: the confirmation gate, the tool
// whitelist and the audit log all live in the worker. These tests exist to
// keep it that way. They assert the two properties the backend actually
// promises about the tool layer:
//
//  1. every /api/v1/tools/* route is behind a bearer token, and
//  2. every one of them lands on the WORKER, never on Ollama and never on a
//     cloud upstream.
//
// Property 2 matters more than it looks. If a future refactor ever gave a
// tools route a cloud fallback "for convenience", tool calls would be decided
// by a model outside the house with no gate in front of it. A test is cheaper
// than remembering.

const testToken = "test-token-abcdef"

// upstreams spins up fake Ollama and worker servers that record what reached
// them, and wires a real httpapi handler in front.
func upstreams(t *testing.T) (h http.Handler, workerHits, ollamaHits *[]string) {
	t.Helper()

	wHits := []string{}
	oHits := []string{}

	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		wHits = append(wHits, r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"upstream":"worker"}`))
	}))
	t.Cleanup(worker.Close)

	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		oHits = append(oHits, r.URL.Path)
		_, _ = w.Write([]byte(`{"upstream":"ollama"}`))
	}))
	t.Cleanup(ollama.Close)

	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID: "dev1", Name: "test", TokenHash: auth.Hash(testToken),
		CreatedAt: time.Now(), LastSeen: time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}

	d := Deps{
		Cfg:        config.Config{ClaimMax: 5, RequestTimeout: 5 * time.Second},
		Store:      st,
		Ollama:     proxy.New(ollama.URL, 5*time.Second),
		Worker:     proxy.New(worker.URL, 5*time.Second),
		WorkerSlow: proxy.New(worker.URL, 30*time.Second),
	}
	return New(d), &wHits, &oHits
}

// toolRoutes is the full surface of the tool layer as exposed by the backend.
// Adding a route without adding it here should feel wrong.
var toolRoutes = []struct {
	method string
	path   string
}{
	{http.MethodGet, "/api/v1/tools"},
	{http.MethodPost, "/api/v1/tools/chat"},
	{http.MethodPost, "/api/v1/tools/confirm"},
	{http.MethodGet, "/api/v1/tools/audit"},
	{http.MethodPost, "/api/v1/tools/enabled"},
}

func TestToolRoutesRequireBearerToken(t *testing.T) {
	h, workerHits, _ := upstreams(t)

	for _, rt := range toolRoutes {
		t.Run(rt.method+" "+rt.path, func(t *testing.T) {
			for _, hdr := range []string{"", "Bearer", "Basic abc", "Bearer wrong-token"} {
				req := httptest.NewRequest(rt.method, rt.path, strings.NewReader(`{}`))
				if hdr != "" {
					req.Header.Set("Authorization", hdr)
				}
				rec := httptest.NewRecorder()
				h.ServeHTTP(rec, req)

				if rec.Code != http.StatusUnauthorized {
					t.Fatalf("auth %q: got %d, want 401", hdr, rec.Code)
				}
			}
		})
	}

	// Nothing unauthenticated may reach the worker. If it did, the gate would
	// be the only thing between an anonymous caller and a tool.
	if len(*workerHits) != 0 {
		t.Fatalf("unauthenticated requests reached the worker: %v", *workerHits)
	}
}

func TestToolRoutesProxyToWorkerOnly(t *testing.T) {
	h, workerHits, ollamaHits := upstreams(t)

	for _, rt := range toolRoutes {
		req := httptest.NewRequest(rt.method, rt.path, strings.NewReader(`{}`))
		req.Header.Set("Authorization", "Bearer "+testToken)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)

		if rec.Code != http.StatusOK {
			t.Fatalf("%s %s: got %d, want 200", rt.method, rt.path, rec.Code)
		}
		var body map[string]string
		if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
			t.Fatalf("%s: bad json: %v", rt.path, err)
		}
		if body["upstream"] != "worker" {
			t.Fatalf("%s went to %q, want worker", rt.path, body["upstream"])
		}
	}

	if len(*workerHits) != len(toolRoutes) {
		t.Fatalf("worker saw %d requests, want %d: %v", len(*workerHits), len(toolRoutes), *workerHits)
	}
	// The load-bearing assertion: no tools route may ever fall back to Ollama,
	// local or cloud. Tools are decided by the gate in the worker.
	if len(*ollamaHits) != 0 {
		t.Fatalf("a tools route reached Ollama: %v", *ollamaHits)
	}
}

// The worker's paths are what it actually serves. A typo here is a 404 the app
// only discovers at runtime, on a phone, with the layer switched on.
func TestToolRoutesForwardToTheWorkerPathsThatExist(t *testing.T) {
	h, workerHits, _ := upstreams(t)

	want := map[string]string{
		"/api/v1/tools":         "/tools",
		"/api/v1/tools/chat":    "/tools/chat",
		"/api/v1/tools/confirm": "/tools/confirm/chat", // approve + phrase the answer
		"/api/v1/tools/audit":   "/tools/audit",
		"/api/v1/tools/enabled": "/tools/enabled",
	}

	for _, rt := range toolRoutes {
		req := httptest.NewRequest(rt.method, rt.path, strings.NewReader(`{}`))
		req.Header.Set("Authorization", "Bearer "+testToken)
		h.ServeHTTP(httptest.NewRecorder(), req)
	}

	if len(*workerHits) != len(toolRoutes) {
		t.Fatalf("worker hits: %v", *workerHits)
	}
	for i, rt := range toolRoutes {
		if got := (*workerHits)[i]; got != want[rt.path] {
			t.Errorf("%s forwarded to %q, want %q", rt.path, got, want[rt.path])
		}
	}
}

// Health is public by design; everything else under /api/v1 is not. This is a
// canary: if a future route lands outside authMW, this catches it.
func TestHealthIsPublicButApiIsNot(t *testing.T) {
	h, _, _ := upstreams(t)

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	if rec.Code != http.StatusOK {
		t.Fatalf("/healthz: got %d, want 200", rec.Code)
	}

	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/tools/audit", nil))
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("/api/v1/tools/audit without token: got %d, want 401", rec.Code)
	}
}
