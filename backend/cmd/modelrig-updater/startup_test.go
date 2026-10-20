package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestVerifyWaitsPastOldFifteenAttemptLimit(t *testing.T) {
	var attempts atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if attempts.Add(1) <= 20 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		fmt.Fprint(w, `{"version":"2.0.18"}`)
	}))
	defer srv.Close()
	if !verifyWithin(srv.URL, "2.0.18", 3*time.Second, time.Millisecond) {
		t.Fatalf("late healthy service rejected after %d attempts", attempts.Load())
	}
}

func TestVerifyNeverAcceptsBadStatusOrWrongVersion(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status int
		body   string
	}{
		{"error with expected version", 503, `{"version":"2.0.18"}`},
		{"old version", 200, `{"version":"2.0.16"}`},
		{"invalid JSON", 200, `not json`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.status)
				fmt.Fprint(w, tc.body)
			}))
			defer srv.Close()
			if verifyWithin(srv.URL, "2.0.18", 60*time.Millisecond, time.Millisecond) {
				t.Fatal("unhealthy service was accepted")
			}
		})
	}
}

func TestVerifyDeadlineCancelsAStuckHealthRequest(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
		<-r.Context().Done()
	}))
	defer srv.Close()
	started := time.Now()
	if verifyWithin(srv.URL, "2.0.18", 100*time.Millisecond, time.Millisecond) {
		t.Fatal("stuck health request was accepted")
	}
	if elapsed := time.Since(started); elapsed > 2*time.Second {
		t.Fatalf("request escaped the readiness deadline: %s", elapsed)
	}
}
