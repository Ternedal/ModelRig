package httpapi

import (
    "encoding/json"
    "net/http"
    "net/http/httptest"
    "testing"
)

// The phone must never call the loopback-only worker directly. The backend
// is the single authenticated gateway for ASR/TTS capability booleans.
func TestWorkerCapabilitiesAreAuthenticatedAndProxied(t *testing.T) {
    h, workerHits, ollamaHits := upstreams(t)

    for _, header := range []string{"", "Bearer wrong-token", "Basic abc"} {
        req := httptest.NewRequest(http.MethodGet, "/api/v1/capabilities", nil)
        if header != "" {
            req.Header.Set("Authorization", header)
        }
        rec := httptest.NewRecorder()
        h.ServeHTTP(rec, req)
        if rec.Code != http.StatusUnauthorized {
            t.Fatalf("auth %q: got %d, want 401", header, rec.Code)
        }
    }
    if len(*workerHits) != 0 {
        t.Fatalf("unauthenticated capabilities reached worker: %v", *workerHits)
    }

    req := httptest.NewRequest(http.MethodGet, "/api/v1/capabilities", nil)
    req.Header.Set("Authorization", "Bearer "+testToken)
    rec := httptest.NewRecorder()
    h.ServeHTTP(rec, req)
    if rec.Code != http.StatusOK {
        t.Fatalf("authenticated capabilities: got %d: %s", rec.Code, rec.Body.String())
    }
    var payload map[string]string
    if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
        t.Fatalf("invalid proxy JSON: %v", err)
    }
    if payload["upstream"] != "worker" {
        t.Fatalf("capabilities reached %q, want worker", payload["upstream"])
    }
    if len(*workerHits) != 1 || (*workerHits)[0] != "/capabilities" {
        t.Fatalf("worker paths: %v, want [/capabilities]", *workerHits)
    }
    if len(*ollamaHits) != 0 {
        t.Fatalf("capabilities leaked to Ollama: %v", *ollamaHits)
    }

    rec = httptest.NewRecorder()
    h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/capabilities", nil))
    if rec.Code != http.StatusNotFound {
        t.Fatalf("unprotected /capabilities must not exist: got %d", rec.Code)
    }
}
