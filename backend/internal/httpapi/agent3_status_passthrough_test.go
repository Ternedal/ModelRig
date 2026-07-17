package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

// The evidence collector reads code_sha256 from the BACKEND's
// /api/v1/experimental/agent3/status -- not from the worker directly (F-508).
// If this proxy reshapes the body, the field vanishes, the collector raises
// EvidenceError, and the physical validation run dies on a field I added: on
// Anders' machine, at the one moment the entire activation gate is waiting for.
//
// In 1.58.80 I wrote "/health/full and the agent3 status publish it". I had
// checked /health/full and read the line that says Forward. Reading a line is
// not a result, and the half I did not check is the half that runs on the rig.
func TestAgent3StatusPassesCodeIdentityThroughTheProxy(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")

	const digest = "abc123def456abc123def456abc123def456abc123def456abc123def456abcd"
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/experimental/agent3/status" {
			t.Errorf("backend asked the worker for %q", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"enabled":true,"experimental":true,` +
			`"production_activation":false,"worker_version":"1.58.85",` +
			`"code_sha256":"` + digest + `"}`))
	}))
	defer worker.Close()

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
	h := New(Deps{
		Cfg:        config.Config{ClaimMax: 5, RequestTimeout: 5 * time.Second},
		Store:      st,
		Worker:     proxy.New(worker.URL, 5*time.Second),
		WorkerSlow: proxy.New(worker.URL, 30*time.Second),
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/experimental/agent3/status", nil)
	req.Header.Set("Authorization", "Bearer "+testToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status: got %d, want 200: %s", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("backend returned unparseable JSON: %v", err)
	}
	got, _ := body["code_sha256"].(string)
	if got != digest {
		t.Fatalf("code_sha256 did not survive the proxy (got %q) -- the physical "+
			"validation run would fail on the rig with EvidenceError", got)
	}
	// The version binding travels the same road; if one survives and the other
	// does not, the collector fails on the other field instead.
	if v, _ := body["worker_version"].(string); v != "1.58.85" {
		t.Fatalf("worker_version did not survive the proxy: %q", v)
	}
}
