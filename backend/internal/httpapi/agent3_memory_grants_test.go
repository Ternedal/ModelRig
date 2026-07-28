package httpapi

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

const agent3MemoryTestSecret = "t033-protected-memory-gateway-test-secret-0123456789"

func protectedMemoryHandler(t *testing.T, worker http.Handler) http.Handler {
	t.Helper()
	workerServer := httptest.NewServer(worker)
	t.Cleanup(workerServer.Close)
	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID:        "paired-device-1",
		Name:      "test",
		TokenHash: auth.Hash(testToken),
		CreatedAt: time.Now(),
		LastSeen:  time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	return New(Deps{
		Cfg:        config.Config{ClaimMax: 5, RequestTimeout: 5 * time.Second},
		Store:      st,
		Worker:     proxy.New(workerServer.URL, 5*time.Second),
		WorkerSlow: proxy.New(workerServer.URL, 5*time.Second),
		Ollama:     proxy.New(workerServer.URL, 5*time.Second),
	})
}

func emptyBodySHA256() string {
	digest := sha256.Sum256(nil)
	return hex.EncodeToString(digest[:])
}

func TestAgent3MemoryGrantActionContract(t *testing.T) {
	tests := []struct {
		method string
		path   string
		want   string
		ok     bool
	}{
		{http.MethodGet, "/experimental/agent3/memory/status", "status", true},
		{http.MethodGet, "/experimental/agent3/memory", "read_metadata", true},
		{http.MethodGet, "/experimental/agent3/memory/search", "read_metadata", true},
		{http.MethodGet, "/experimental/agent3/memory/id-1", "read_metadata", true},
		{http.MethodGet, "/experimental/agent3/memory/id-1/history", "read_metadata", true},
		{http.MethodPost, "/experimental/agent3/memory", "write_private", true},
		{http.MethodPost, "/experimental/agent3/memory/id-1/correct", "write_private", true},
		{http.MethodDelete, "/experimental/agent3/memory/id-1", "write_private", true},
		{http.MethodPost, "/experimental/agent3/memory/context-preview", "", false},
		{http.MethodGet, "/experimental/agent3/memory/context-preview", "", false},
		{http.MethodDelete, "/experimental/agent3/memory/search", "", false},
		{http.MethodPut, "/experimental/agent3/memory/id-1", "", false},
		{http.MethodGet, "/experimental/agent3/other", "", false},
	}
	for _, tc := range tests {
		t.Run(tc.method+" "+tc.path, func(t *testing.T) {
			got, err := agent3MemoryGrantAction(tc.method, tc.path)
			if tc.ok && (err != nil || got != tc.want) {
				t.Fatalf("got action %q err %v, want %q", got, err, tc.want)
			}
			if !tc.ok && err == nil {
				t.Fatalf("unsupported route returned action %q", got)
			}
		})
	}
}

func TestAgent3MemoryProtectedModeMintsExactGrant(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	t.Setenv(agent3MemoryStoreEnv, "protected")
	t.Setenv(agent3MemoryAPISecretEnv, agent3MemoryTestSecret)

	var mu sync.Mutex
	var token, requestID, method, path, rawQuery string
	h := protectedMemoryHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		token = r.Header.Get(agent3MemoryGrantHeader)
		requestID = r.Header.Get("X-Request-ID")
		method = r.Method
		path = r.URL.Path
		rawQuery = r.URL.RawQuery
		mu.Unlock()
		w.Header().Set(agent3MemoryStoreAttestationHeader, agent3MemoryStoreAttestationValue)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))

	req := httptest.NewRequest(
		http.MethodGet,
		"/api/v1/experimental/agent3/memory/search?q=needle",
		nil,
	)
	req.Header.Set("Authorization", "Bearer "+testToken)
	req.Header.Set("X-Request-ID", "req-memory-gateway-001")
	req.Header.Set(agent3MemoryGrantHeader, "client-spoof-must-not-pass")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("protected memory request got %d: %s", rec.Code, rec.Body.String())
	}

	mu.Lock()
	gotToken, gotRID, gotMethod, gotPath, gotQuery := token, requestID, method, path, rawQuery
	mu.Unlock()
	if gotToken == "" || gotToken == "client-spoof-must-not-pass" {
		t.Fatalf("gateway did not overwrite the client-supplied grant: %q", gotToken)
	}
	if gotRID != "req-memory-gateway-001" || gotMethod != http.MethodGet ||
		gotPath != "/experimental/agent3/memory/search" || gotQuery != "q=needle" {
		t.Fatalf("worker binding = %q %q %q ?%s", gotRID, gotMethod, gotPath, gotQuery)
	}
	claims, err := verifyAgent3MemoryGrant(
		gotToken,
		gotRID,
		gotMethod,
		gotPath,
		gotQuery,
		emptyBodySHA256(),
		time.Now(),
	)
	if err != nil {
		t.Fatalf("forwarded grant did not verify: %v", err)
	}
	if claims.DeviceID != "paired-device-1" || claims.Action != "read_metadata" ||
		claims.Schema != agent3MemoryGrantSchema || claims.Query != "q=needle" ||
		claims.BodySHA256 != emptyBodySHA256() {
		t.Fatalf("unexpected claims: %+v", claims)
	}
	if claims.ExpiresAt-claims.IssuedAt != int64(agent3MemoryGrantTTL/time.Second) {
		t.Fatalf("grant TTL = %d seconds", claims.ExpiresAt-claims.IssuedAt)
	}
}

func TestAgent3MemoryGrantRejectsTamperingAndWrongBindings(t *testing.T) {
	t.Setenv(agent3MemoryAPISecretEnv, agent3MemoryTestSecret)
	now := time.Unix(20_000, 0)
	body := `{"subject":"Anders","predicate":"x","value":"private"}`
	req := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/experimental/agent3/memory?mode=exact",
		strings.NewReader(body),
	)
	req.Header.Set("X-Request-ID", "req-write-001")
	req = req.WithContext(context.WithValue(req.Context(), deviceKey, store.Device{ID: "dev-1"}))
	bodySHA, err := bindAgent3MemoryRequestBody(req)
	if err != nil {
		t.Fatalf("bind body: %v", err)
	}
	token, claims, err := issueAgent3MemoryGrant(
		req,
		"/experimental/agent3/memory",
		bodySHA,
		now,
	)
	if err != nil {
		t.Fatalf("issue grant: %v", err)
	}
	if claims.Action != "write_private" || claims.Query != "mode=exact" ||
		claims.BodySHA256 != bodySHA {
		t.Fatalf("claims = %+v", claims)
	}
	if _, err := verifyAgent3MemoryGrant(
		token,
		"req-write-001",
		http.MethodPost,
		"/experimental/agent3/memory",
		"mode=exact",
		bodySHA,
		now,
	); err != nil {
		t.Fatalf("fresh exact grant failed: %v", err)
	}
	parts := strings.Split(token, ".")
	tampered := parts[0] + "." + strings.Repeat("A", len(parts[1]))
	cases := map[string]struct {
		token  string
		rid    string
		method string
		path   string
		query  string
		body   string
		at     time.Time
	}{
		"tampered": {token: tampered, rid: "req-write-001", method: http.MethodPost, path: "/experimental/agent3/memory", query: "mode=exact", body: bodySHA, at: now},
		"request":  {token: token, rid: "different", method: http.MethodPost, path: "/experimental/agent3/memory", query: "mode=exact", body: bodySHA, at: now},
		"method":   {token: token, rid: "req-write-001", method: http.MethodGet, path: "/experimental/agent3/memory", query: "mode=exact", body: bodySHA, at: now},
		"path":     {token: token, rid: "req-write-001", method: http.MethodPost, path: "/experimental/agent3/memory/id/correct", query: "mode=exact", body: bodySHA, at: now},
		"query":    {token: token, rid: "req-write-001", method: http.MethodPost, path: "/experimental/agent3/memory", query: "mode=changed", body: bodySHA, at: now},
		"body":     {token: token, rid: "req-write-001", method: http.MethodPost, path: "/experimental/agent3/memory", query: "mode=exact", body: strings.Repeat("0", 64), at: now},
		"expired":  {token: token, rid: "req-write-001", method: http.MethodPost, path: "/experimental/agent3/memory", query: "mode=exact", body: bodySHA, at: now.Add(time.Minute)},
	}
	for label, candidate := range cases {
		t.Run(label, func(t *testing.T) {
			if _, err := verifyAgent3MemoryGrant(
				candidate.token,
				candidate.rid,
				candidate.method,
				candidate.path,
				candidate.query,
				candidate.body,
				candidate.at,
			); err == nil {
				t.Fatal("invalid grant binding was accepted")
			}
		})
	}
}

func TestAgent3MemoryProtectedModeRequiresWorkerAttestation(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	t.Setenv(agent3MemoryStoreEnv, "protected")
	t.Setenv(agent3MemoryAPISecretEnv, agent3MemoryTestSecret)
	h := protectedMemoryHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"legacy":true}`))
	}))
	req := httptest.NewRequest(http.MethodGet, "/api/v1/experimental/agent3/memory", nil)
	req.Header.Set("Authorization", "Bearer "+testToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadGateway || strings.Contains(rec.Body.String(), "legacy") {
		t.Fatalf("unattested worker response got status=%d body=%q", rec.Code, rec.Body.String())
	}
}

func TestAgent3MemoryProtectedModeFailsClosed(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	t.Setenv(agent3MemoryStoreEnv, "protected")
	t.Setenv(agent3MemoryAPISecretEnv, "short")
	workerHits := 0
	h := protectedMemoryHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits++
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/api/v1/experimental/agent3/memory", nil)
	req.Header.Set("Authorization", "Bearer "+testToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusServiceUnavailable || workerHits != 0 {
		t.Fatalf("missing secret got status=%d worker_hits=%d", rec.Code, workerHits)
	}

	t.Setenv(agent3MemoryAPISecretEnv, agent3MemoryTestSecret)
	req = httptest.NewRequest(http.MethodGet,
		"/api/v1/experimental/agent3/memory/context-preview", nil)
	req.Header.Set("Authorization", "Bearer "+testToken)
	rec = httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound || workerHits != 0 {
		t.Fatalf("unsupported protected route got status=%d worker_hits=%d", rec.Code, workerHits)
	}
}

func TestAgent3MemoryLegacyModeDoesNotForwardSpoofedGrant(t *testing.T) {
	t.Setenv("KALIV_AGENT3_ENABLED", "1")
	t.Setenv(agent3MemoryStoreEnv, "legacy")
	gotGrant := "unset"
	h := protectedMemoryHandler(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotGrant = r.Header.Get(agent3MemoryGrantHeader)
		w.WriteHeader(http.StatusOK)
	}))
	req := httptest.NewRequest(http.MethodGet, "/api/v1/experimental/agent3/memory", nil)
	req.Header.Set("Authorization", "Bearer "+testToken)
	req.Header.Set(agent3MemoryGrantHeader, "client-spoof")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("legacy request got %d", rec.Code)
	}
	if gotGrant != "" {
		t.Fatalf("legacy proxy forwarded client grant %q", gotGrant)
	}
}
