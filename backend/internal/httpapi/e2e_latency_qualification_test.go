package httpapi

import (
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

const e2eLatencyTestToken = "e2e-latency-test-token"

func e2eLatencyTestServer(t *testing.T, worker http.Handler) http.Handler {
	t.Helper()
	upstream := httptest.NewServer(worker)
	t.Cleanup(upstream.Close)

	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID: "dev1", Name: "test", TokenHash: auth.Hash(e2eLatencyTestToken),
		CreatedAt: time.Now(), LastSeen: time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	return New(Deps{
		Cfg: config.Config{ClaimMax: 5, RequestTimeout: 5 * time.Second},
		Store: st,
		Worker: proxy.New(upstream.URL, 5*time.Second),
		WorkerSlow: proxy.New(upstream.URL, 30*time.Second),
	})
}

func TestE2ELatencyQualificationRouteIsAbsentByDefault(t *testing.T) {
	h := e2eLatencyTestServer(t, http.NotFoundHandler())
	req := httptest.NewRequest(http.MethodPost, "/api/v1/experimental/e2e-latency/voice", nil)
	req.Header.Set("Authorization", "Bearer "+e2eLatencyTestToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("flag off must mean no route: got %d", rec.Code)
	}
}

func TestE2ELatencyQualificationRouteRequiresExactLiteralOne(t *testing.T) {
	for _, value := range []string{"", "0", "true", "yes", "on", " 1 "} {
		t.Run(value, func(t *testing.T) {
			t.Setenv("KALIV_E2E_LATENCY_QUALIFICATION_ENABLED", value)
			h := e2eLatencyTestServer(t, http.NotFoundHandler())
			req := httptest.NewRequest(http.MethodPost, "/api/v1/experimental/e2e-latency/voice", nil)
			req.Header.Set("Authorization", "Bearer "+e2eLatencyTestToken)
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)
			if rec.Code != http.StatusNotFound {
				t.Fatalf("non-literal opt-in mounted route: got %d", rec.Code)
			}
		})
	}
}

func TestE2ELatencyQualificationRouteForwardsOnlyWhenEnabled(t *testing.T) {
	t.Setenv("KALIV_E2E_LATENCY_QUALIFICATION_ENABLED", "1")
	observed := make(chan string, 1)
	h := e2eLatencyTestServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		observed <- r.URL.Path
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusAccepted)
		_, _ = w.Write([]byte("{\"schema\":\"kaliv-system/end-to-end-latency-voice-turn/v1\",\"production_activation\":false}"))
	}))

	req := httptest.NewRequest(http.MethodPost, "/api/v1/experimental/e2e-latency/voice", nil)
	req.Header.Set("Authorization", "Bearer "+e2eLatencyTestToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusAccepted {
		t.Fatalf("enabled qualification proxy failed: %d: %s", rec.Code, rec.Body.String())
	}
	select {
	case path := <-observed:
		if path != "/experimental/e2e-latency/voice" {
			t.Fatalf("worker path mismatch: %q", path)
		}
	case <-time.After(time.Second):
		t.Fatal("worker did not receive qualification request")
	}
	if got := rec.Header().Get("Content-Type"); got != "application/json" {
		t.Fatalf("content type did not survive proxy: %q", got)
	}
}
