package httpapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"modelrig/internal/proxy"
)

func TestControlCenterSchedulesRejectsNonLoopbackWorker(t *testing.T) {
	s := &server{Deps: Deps{Worker: proxy.New("http://192.0.2.10:65535", time.Second)}}
	rec := httptest.NewRecorder()
	s.handleControlCenterSchedules(rec, httptest.NewRequest(http.MethodGet, "/", nil))

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", rec.Code)
	}
	if got := rec.Body.String(); !strings.Contains(got, "control center schedule history unavailable") {
		t.Fatalf("generic error missing: %s", got)
	}
}

func TestControlCenterSchedulesDoesNotFollowWorkerRedirect(t *testing.T) {
	var calls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Path == "/control-center/schedules" {
			http.Redirect(w, r, "/redirect-target", http.StatusFound)
			return
		}
		_, _ = w.Write([]byte(validControlCenterSchedulePayload()))
	}))
	defer upstream.Close()

	s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
	rec := httptest.NewRecorder()
	s.handleControlCenterSchedules(rec, httptest.NewRequest(http.MethodGet, "/", nil))

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502; body=%s", rec.Code, rec.Body.String())
	}
	if calls.Load() != 1 {
		t.Fatalf("redirect followed: worker calls = %d, want 1", calls.Load())
	}
}
