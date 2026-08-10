package main

import (
	"net/http"
	"net/http/httptest"
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
