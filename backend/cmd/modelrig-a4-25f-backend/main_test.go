package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRequirePrivateIPv4(t *testing.T) {
	for _, value := range []string{"10.12.0.4", "172.16.10.20", "192.168.50.2"} {
		got, err := requirePrivateIPv4(value)
		if err != nil {
			t.Fatalf("private address %q rejected: %v", value, err)
		}
		if got != value {
			t.Fatalf("private address changed: got %q want %q", got, value)
		}
	}
	for _, value := range []string{"", "127.0.0.1", "0.0.0.0", "8.8.8.8", "::1", "localhost"} {
		if _, err := requirePrivateIPv4(value); err == nil {
			t.Fatalf("unsafe/non-private address %q was accepted", value)
		}
	}
}

func TestRequireLoopbackWorkerURL(t *testing.T) {
	for _, value := range []string{"http://127.0.0.1:18099", "http://[::1]:18099"} {
		if err := requireLoopbackWorkerURL(value); err != nil {
			t.Fatalf("loopback worker %q rejected: %v", value, err)
		}
	}
	for _, value := range []string{
		"https://127.0.0.1:18099",
		"http://192.168.1.5:18099",
		"http://127.0.0.1:80",
		"http://127.0.0.1:18099/path",
		"http://user@127.0.0.1:18099",
	} {
		if err := requireLoopbackWorkerURL(value); err == nil {
			t.Fatalf("unsafe worker URL %q was accepted", value)
		}
	}
}

func TestLanOnlyHandlerHidesAdminAndPairMinting(t *testing.T) {
	called := 0
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called++
		w.WriteHeader(http.StatusNoContent)
	})
	handler := lanOnlyHandler(inner)

	for _, path := range []string{
		"/api/v1/pair/start",
		"/api/v1/admin/devices/device-1/grants/agent4-read",
	} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusNotFound {
			t.Fatalf("%s must be hidden on LAN: got %d", path, rec.Code)
		}
	}
	if called != 0 {
		t.Fatalf("hidden LAN routes reached shared handler %d times", called)
	}

	for _, path := range []string{
		"/healthz",
		"/api/v1/pair/claim",
		"/api/v1/experimental/agent4/operator/campaigns",
	} {
		req := httptest.NewRequest(http.MethodGet, path, nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != http.StatusNoContent {
			t.Fatalf("allowed LAN route %s was blocked: %d", path, rec.Code)
		}
	}
	if called != 3 {
		t.Fatalf("allowed LAN routes reached handler %d times, want 3", called)
	}
}

func TestAgent4EvidenceTraceRedactsRequestAndRecordsActualOutcome(t *testing.T) {
	tracePath := filepath.Join(t.TempDir(), "a4-25f-trace.jsonl")
	trace := &agent4EvidenceTrace{path: tracePath}
	const token = "physical-bearer-must-never-appear"
	const rawCursor = "%7B%22schema%22%3A%22secret-cursor%22%7D"
	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+token {
			t.Fatal("test request lost bearer before inner handler")
		}
		w.Header().Set("Content-Type", "application/vnd.modelrig.agent4.operator+json; charset=utf-8")
		w.WriteHeader(http.StatusGone)
		_, _ = w.Write([]byte(`{"detail":"gone"}`))
	})
	handler := trace.wrap(inner)
	url := "/api/v1/experimental/agent4/operator/campaigns/c1/timeline" +
		"?snapshot_id=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&after=" + rawCursor
	req := httptest.NewRequest(http.MethodGet, url, nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusGone {
		t.Fatalf("wrapped status changed: %d", rec.Code)
	}

	raw, err := os.ReadFile(tracePath)
	if err != nil {
		t.Fatalf("read trace: %v", err)
	}
	text := string(raw)
	if strings.Contains(text, token) || strings.Contains(text, "secret-cursor") || strings.Contains(text, rawCursor) {
		t.Fatalf("trace leaked credential/cursor material: %s", text)
	}
	var entry evidenceTraceEntry
	if err := json.Unmarshal(raw, &entry); err != nil {
		t.Fatalf("decode trace: %v", err)
	}
	if entry.Schema != evidenceTraceSchema || entry.Method != http.MethodGet || entry.RouteKind != "timeline-list" {
		t.Fatalf("unexpected trace identity: %+v", entry)
	}
	if entry.HTTPStatus != http.StatusGone {
		t.Fatalf("trace status = %d, want 410", entry.HTTPStatus)
	}
	if entry.ResponseMediaType != "application/vnd.modelrig.agent4.operator+json" {
		t.Fatalf("trace media type = %q", entry.ResponseMediaType)
	}
	if entry.RawQuerySHA256 != sha256String(req.URL.RawQuery) {
		t.Fatalf("trace query digest drifted")
	}
	if entry.ResponseBodySHA256 != sha256String(`{"detail":"gone"}`) || entry.ResponseBodySize != int64(len(`{"detail":"gone"}`)) {
		t.Fatalf("trace body evidence drifted: %+v", entry)
	}
	if len(entry.QueryKeys) != 2 || entry.QueryKeys[0] != "after" || entry.QueryKeys[1] != "snapshot_id" {
		t.Fatalf("trace query keys = %v", entry.QueryKeys)
	}
	if entry.CredentialInReceipt || entry.RawCursorInReceipt || entry.PublicNetwork || entry.ProductionActivation {
		t.Fatalf("trace safety flags drifted: %+v", entry)
	}
}

func TestAgent4RouteKindIsRedactedAndStable(t *testing.T) {
	cases := map[string]string{
		"/api/v1/experimental/agent4/operator/campaigns":                              "campaign-list",
		"/api/v1/experimental/agent4/operator/campaigns/c1":                           "campaign-detail",
		"/api/v1/experimental/agent4/operator/campaigns/c1/timeline":                  "timeline-list",
		"/api/v1/experimental/agent4/operator/campaigns/c1/evidence":                  "evidence-list",
		"/api/v1/experimental/agent4/operator/campaigns/c1/evidence/verification":     "evidence-verification",
		"/api/v1/experimental/agent4/operator/campaigns/c1/evidence/evidence-private": "evidence-detail",
		"/api/v1/status": "",
	}
	for path, want := range cases {
		if got := agent4RouteKind(path); got != want {
			t.Fatalf("route kind for %q = %q, want %q", path, got, want)
		}
	}
}
