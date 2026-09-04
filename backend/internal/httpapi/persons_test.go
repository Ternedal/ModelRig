package httpapi

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

const testPersonID = "person-0123456789abcdef0123456789abcdef"

// The person registry boundary reuses the schedule test scaffolding: a paired
// device with a known token, a loopback worker stub, and the same server
// construction.

func TestPersonRoutesRequireBearerBeforeWorker(t *testing.T) {
	hits := 0
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)

	routes := []struct{ method, path string }{
		{http.MethodGet, "/api/v1/persons"},
		{http.MethodPost, "/api/v1/persons"},
		{http.MethodGet, "/api/v1/persons/active"},
		{http.MethodPost, "/api/v1/persons/select"},
		{http.MethodGet, "/api/v1/persons/" + testPersonID},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/activate"},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/person-revisions"},
	}
	for _, route := range routes {
		for _, token := range []string{"", "wrong"} {
			rec := doScheduleRequest(h, route.method, route.path, token, `{}`)
			if rec.Code != http.StatusUnauthorized {
				t.Fatalf("%s %s token=%q: got %d, want 401", route.method, route.path, token, rec.Code)
			}
		}
	}
	if hits != 0 {
		t.Fatalf("unauthenticated requests reached worker %d time(s)", hits)
	}
}

func TestPersonRoutesForwardToWorkerPaths(t *testing.T) {
	var seen []string
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, r.Method+" "+r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)

	cases := []struct{ method, path, want string }{
		{http.MethodGet, "/api/v1/persons", "GET /persons"},
		{http.MethodPost, "/api/v1/persons", "POST /persons"},
		{http.MethodGet, "/api/v1/persons/active", "GET /persons/active"},
		{http.MethodPost, "/api/v1/persons/select", "POST /persons/select"},
		{http.MethodGet, "/api/v1/persons/" + testPersonID, "GET /persons/" + testPersonID},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/body-revisions", "POST /persons/" + testPersonID + "/body-revisions"},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/voice-revisions", "POST /persons/" + testPersonID + "/voice-revisions"},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/personality-revisions", "POST /persons/" + testPersonID + "/personality-revisions"},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/person-revisions", "POST /persons/" + testPersonID + "/person-revisions"},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/activate", "POST /persons/" + testPersonID + "/activate"},
	}
	for i, c := range cases {
		rec := doScheduleRequest(h, c.method, c.path, scheduleToken, `{}`)
		if rec.Code != http.StatusOK {
			t.Fatalf("%s %s: got %d body=%s", c.method, c.path, rec.Code, rec.Body.String())
		}
		if seen[i] != c.want {
			t.Fatalf("%s %s forwarded as %q, want %q", c.method, c.path, seen[i], c.want)
		}
	}
}

func TestPersonRoutesRejectBadIDsAndUnknownActionsBeforeWorker(t *testing.T) {
	hits := 0
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits++
	}))
	defer worker.Close()
	h := scheduleHandler(t, worker.URL, 2*time.Second)

	bad := []struct{ method, path string }{
		{http.MethodGet, "/api/v1/persons/person-short"},
		{http.MethodGet, "/api/v1/persons/PERSON-0123456789ABCDEF0123456789ABCDEF"},
		{http.MethodGet, "/api/v1/persons/bodyid-0123456789abcdef0123456789abcdef"},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/delete"},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/activate-voice"},
		// The invariant, spelled out at the boundary: no per-component activation.
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/body-revisions/activate"},
		{http.MethodPost, "/api/v1/persons/" + testPersonID + "/voice-revisions/body-r0001/activate"},
	}
	for _, c := range bad {
		rec := doScheduleRequest(h, c.method, c.path, scheduleToken, `{}`)
		if rec.Code != http.StatusNotFound {
			t.Fatalf("%s %s: got %d, want 404", c.method, c.path, rec.Code)
		}
	}
	if hits != 0 {
		t.Fatalf("rejected requests reached worker %d time(s)", hits)
	}
}

func TestPersonRoutesRefuseNonLoopbackWorker(t *testing.T) {
	h := scheduleHandler(t, "http://192.168.1.50:8099", 2*time.Second)
	rec := doScheduleRequest(h, http.MethodGet, "/api/v1/persons", scheduleToken, "")
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("got %d, want 503", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "loopback") {
		t.Fatalf("body should name the loopback requirement: %s", rec.Body.String())
	}
}
