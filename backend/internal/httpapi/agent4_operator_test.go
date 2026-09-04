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

// ADR-A4-007 contract tests, backend side: the proxy is the single door
// (contract 4: fixed-body grant refusal; contract 6: byte-identical
// pass-through of the canonical payloads; flag off means no route at all).

const a4TestToken = "a4-test-token"

func a4TestServer(t *testing.T, grants []string, workerBody string) (http.Handler, *httptest.Server) {
	t.Helper()
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Kaliv-Canonical-Cursor", "cursor-bytes-untouched")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(workerBody))
	}))
	t.Cleanup(worker.Close)
	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID: "dev1", Name: "test", TokenHash: auth.Hash(a4TestToken),
		CreatedAt: time.Now(), LastSeen: time.Now(), Grants: grants,
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	h := New(Deps{
		Cfg:        config.Config{ClaimMax: 5, RequestTimeout: 5 * time.Second},
		Store:      st,
		Worker:     proxy.New(worker.URL, 5*time.Second),
		WorkerSlow: proxy.New(worker.URL, 30*time.Second),
	})
	return h, worker
}

func TestAgent4OperatorFlagOffMeansNoRoute(t *testing.T) {
	// Deliberately NOT setting KALIV_AGENT4_OPERATOR_API.
	h, _ := a4TestServer(t, []string{agent4ReadGrant}, "{}")
	req := httptest.NewRequest(http.MethodGet, "/api/v1/experimental/agent4/operator/campaigns", nil)
	req.Header.Set("Authorization", "Bearer "+a4TestToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusNotFound {
		t.Fatalf("flag off must mean no route: got %d", rec.Code)
	}
}

func TestAgent4OperatorRequiresExplicitGrant(t *testing.T) {
	t.Setenv("KALIV_AGENT4_OPERATOR_API", "1")
	// Paired device WITHOUT the grant — including devices paired before the
	// field existed (nil grants).
	h, _ := a4TestServer(t, nil, "{}")
	req := httptest.NewRequest(http.MethodGet, "/api/v1/experimental/agent4/operator/campaigns", nil)
	req.Header.Set("Authorization", "Bearer "+a4TestToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("paired-without-grant must be 403: got %d: %s", rec.Code, rec.Body.String())
	}
	if got, want := rec.Body.String(), `{"error":"agent4 read grant required"}`+"\n"; got != want {
		t.Fatalf("fixed error body drifted: got %q want %q", got, want)
	}
}

func TestAgent4OperatorForwardsByteIdentical(t *testing.T) {
	t.Setenv("KALIV_AGENT4_OPERATOR_API", "1")
	const canonical = `{"items":[],"cursor":"HASH-BOUND-BYTES"}`
	h, worker := a4TestServer(t, []string{agent4ReadGrant}, canonical)
	_ = worker
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/experimental/agent4/operator/campaigns/c1/timeline?cursor=abc", nil)
	req.Header.Set("Authorization", "Bearer "+a4TestToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("granted read failed: %d: %s", rec.Code, rec.Body.String())
	}
	if rec.Body.String() != canonical {
		t.Fatalf("body was re-serialised: %q", rec.Body.String())
	}
	// Contract 6 binds the PAYLOAD bytes: the hash-bound cursors live in the
	// JSON body, which Forward streams untouched. Response headers are
	// deliberately whitelisted by the house forwarder, so a custom header is
	// NOT expected to survive — asserting Content-Type is the honest check.
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("content type did not survive the proxy: %q", ct)
	}
}

func TestAgent4OperatorPreservesSnapshotQueryStatusBodyAndMediaType(t *testing.T) {
	t.Setenv("KALIV_AGENT4_OPERATOR_API", "1")
	const rawQuery = "snapshot_id=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&after=%7B%22schema%22%3A%22bound%22%7D"
	const workerBody = `{"detail":"agent4 operator snapshot unavailable"}`
	type observedRequest struct {
		path     string
		rawQuery string
	}
	observed := make(chan observedRequest, 1)
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		observed <- observedRequest{path: r.URL.Path, rawQuery: r.URL.RawQuery}
		w.Header().Set("Content-Type", "application/vnd.modelrig.agent4.operator+json")
		w.WriteHeader(http.StatusGone)
		_, _ = w.Write([]byte(workerBody))
	}))
	t.Cleanup(worker.Close)

	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID: "dev1", Name: "test", TokenHash: auth.Hash(a4TestToken),
		CreatedAt: time.Now(), LastSeen: time.Now(), Grants: []string{agent4ReadGrant},
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	h := New(Deps{
		Cfg:        config.Config{ClaimMax: 5, RequestTimeout: 5 * time.Second},
		Store:      st,
		Worker:     proxy.New(worker.URL, 5*time.Second),
		WorkerSlow: proxy.New(worker.URL, 30*time.Second),
	})

	req := httptest.NewRequest(
		http.MethodGet,
		"/api/v1/experimental/agent4/operator/campaigns?"+rawQuery,
		nil,
	)
	req.Header.Set("Authorization", "Bearer "+a4TestToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	select {
	case got := <-observed:
		if got.path != "/experimental/agent4/operator/campaigns" {
			t.Fatalf("worker path was rewritten unexpectedly: %q", got.path)
		}
		if got.rawQuery != rawQuery {
			t.Fatalf("snapshot query was rewritten: got %q want %q", got.rawQuery, rawQuery)
		}
	case <-time.After(time.Second):
		t.Fatal("worker did not receive snapshot-bound request")
	}
	if rec.Code != http.StatusGone {
		t.Fatalf("worker status was rewritten: got %d", rec.Code)
	}
	if rec.Body.String() != workerBody {
		t.Fatalf("worker body was rewritten: got %q", rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/vnd.modelrig.agent4.operator+json" {
		t.Fatalf("worker media type was rewritten: %q", ct)
	}
}

func TestDeviceHasGrantDefaultDeny(t *testing.T) {
	if (store.Device{}).HasGrant(agent4ReadGrant) {
		t.Fatal("empty device must have no grants")
	}
	if !(store.Device{Grants: []string{agent4ReadGrant}}).HasGrant(agent4ReadGrant) {
		t.Fatal("explicit grant must be honoured")
	}
}
