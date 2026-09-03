package httpapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestBodyRoutesRequireBearerBeforeWorker(t *testing.T) {
	hits := 0
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hits++ }))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)
	for _, path := range []string{
		"/api/v1/body/active",
		"/api/v1/body/active/avatar.vrm",
		"/api/v1/body/active/thumbnail.png",
		"/api/v1/body/active/motions/idle.vrma",
	} {
		for _, token := range []string{"", "wrong"} {
			if rec := doScheduleRequest(h, http.MethodGet, path, token, ""); rec.Code != http.StatusUnauthorized {
				t.Fatalf("GET %s token=%q: got %d, want 401", path, token, rec.Code)
			}
		}
	}
	if hits != 0 {
		t.Fatalf("unauthenticated requests reached worker %d time(s)", hits)
	}
}

func TestBodyRoutesForwardBytesAndHeadersUntouched(t *testing.T) {
	var seen []string
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, r.Method+" "+r.URL.Path)
		w.Header().Set("Content-Type", "model/gltf-binary")
		w.Header().Set("X-BodyRig-Body-ID", "bodyid-000000000000000000000abc")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("glTF\x02\x00\x00\x00"))
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)

	cases := []struct{ path, want string }{
		{"/api/v1/body/active", "GET /body/active"},
		{"/api/v1/body/active/avatar.vrm", "GET /body/active/avatar.vrm"},
		{"/api/v1/body/active/thumbnail.png", "GET /body/active/thumbnail.png"},
		{"/api/v1/body/active/motions/talk.vrma", "GET /body/active/motions/talk.vrma"},
	}
	for i, c := range cases {
		rec := doScheduleRequest(h, http.MethodGet, c.path, scheduleToken, "")
		if rec.Code != http.StatusOK {
			t.Fatalf("GET %s: got %d body=%s", c.path, rec.Code, rec.Body.String())
		}
		if seen[i] != c.want {
			t.Fatalf("GET %s forwarded as %q, want %q", c.path, seen[i], c.want)
		}
		if rec.Header().Get("X-BodyRig-Body-ID") == "" {
			t.Fatalf("GET %s: BodyRig headers must pass through", c.path)
		}
		if rec.Body.String() != "glTF\x02\x00\x00\x00" {
			t.Fatalf("GET %s: binary body altered: %q", c.path, rec.Body.String())
		}
	}
}

func TestBodyRoutesRejectBadMotionNamesAndWritesBeforeWorker(t *testing.T) {
	hits := 0
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hits++ }))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)
	for _, path := range []string{
		"/api/v1/body/active/motions/Idle.vrma",
		"/api/v1/body/active/motions/idle%2F..%2Fmanifest.vrma",
		"/api/v1/body/active/motions/.vrma",
	} {
		if rec := doScheduleRequest(h, http.MethodGet, path, scheduleToken, ""); rec.Code != http.StatusNotFound {
			t.Fatalf("GET %s: got %d, want 404", path, rec.Code)
		}
	}
	for _, path := range []string{"/api/v1/body/active", "/api/v1/body/active/avatar.vrm"} {
		if rec := doScheduleRequest(h, http.MethodPost, path, scheduleToken, `{}`); rec.Code == http.StatusOK {
			t.Fatalf("POST %s must not be routable", path)
		}
	}
	if hits != 0 {
		t.Fatalf("rejected requests reached worker %d time(s)", hits)
	}
}

func TestBodyRoutesRefuseNonLoopbackWorker(t *testing.T) {
	h := scheduleHandler(t, "http://192.168.1.50:8099", 2*time.Second)
	if rec := doScheduleRequest(h, http.MethodGet, "/api/v1/body/active", scheduleToken, ""); rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("got %d, want 503", rec.Code)
	}
}

func TestBodySessionRoutesForwardAndValidate(t *testing.T) {
	var seen []string
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, r.Method+" "+r.URL.Path+"?"+r.URL.RawQuery)
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("data: {\"state\":\"idle\"}\n\n"))
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)

	if rec := doScheduleRequest(h, http.MethodGet, "/api/v1/body/frames?limit=1", scheduleToken, ""); rec.Code != http.StatusOK {
		t.Fatalf("frames: got %d", rec.Code)
	} else if !strings.HasPrefix(rec.Body.String(), "data: ") {
		t.Fatalf("frames: SSE body not passed through: %q", rec.Body.String())
	}
	if seen[0] != "GET /body/frames?limit=1" {
		t.Fatalf("frames forwarded as %q (query must survive)", seen[0])
	}
	if rec := doScheduleRequest(h, http.MethodGet, "/api/v1/body/state", scheduleToken, ""); rec.Code != http.StatusOK {
		t.Fatalf("state: got %d", rec.Code)
	}
	if rec := doScheduleRequest(h, http.MethodPost, "/api/v1/body/interrupt", scheduleToken, ""); rec.Code != http.StatusOK {
		t.Fatalf("interrupt: got %d", rec.Code)
	}
	if rec := doScheduleRequest(h, http.MethodPost, "/api/v1/body/state/listening", scheduleToken, ""); rec.Code != http.StatusOK {
		t.Fatalf("set state: got %d", rec.Code)
	}
	hits := len(seen)
	if rec := doScheduleRequest(h, http.MethodPost, "/api/v1/body/state/Listening", scheduleToken, ""); rec.Code != http.StatusNotFound {
		t.Fatalf("bad state name: got %d, want 404", rec.Code)
	}
	if len(seen) != hits {
		t.Fatalf("bad state name reached the worker")
	}
	for _, c := range []struct{ method, path string }{
		{http.MethodGet, "/api/v1/body/frames"},
		{http.MethodGet, "/api/v1/body/state"},
		{http.MethodPost, "/api/v1/body/interrupt"},
		{http.MethodPost, "/api/v1/body/state/listening"},
	} {
		if rec := doScheduleRequest(h, c.method, c.path, "", ""); rec.Code != http.StatusUnauthorized {
			t.Fatalf("%s %s without token: got %d, want 401", c.method, c.path, rec.Code)
		}
	}
}
