package httpapi

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestBodySessionMetadataHeadersPassThroughNarrowly(t *testing.T) {
	const bodyID = "bodyid-000000000000000000000abc"
	const sessionID = "body-0123456789ab"
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-BodyRig-Body-ID", bodyID)
		w.Header().Set("X-BodyRig-Session-ID", sessionID)
		w.Header().Set("X-Worker-Session-Secret", "must-not-cross-proxy")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"type":"bodyrig.render_frame","version":"0.1"}`))
	}))
	defer worker.Close()

	h := scheduleHandler(t, worker.URL, 2*time.Second)
	for _, path := range []string{
		"/api/v1/body/state",
		"/api/v1/body/frames?limit=1",
	} {
		rec := doScheduleRequest(h, http.MethodGet, path, scheduleToken, "")
		if rec.Code != http.StatusOK {
			t.Fatalf("GET %s: got %d body=%s", path, rec.Code, rec.Body.String())
		}
		if got := rec.Header().Get("X-BodyRig-Body-ID"); got != bodyID {
			t.Fatalf("GET %s: body identity header=%q, want %q", path, got, bodyID)
		}
		if got := rec.Header().Get("X-BodyRig-Session-ID"); got != sessionID {
			t.Fatalf("GET %s: session identity header=%q, want %q", path, got, sessionID)
		}
		if got := rec.Header().Get("X-Worker-Session-Secret"); got != "" {
			t.Fatalf("GET %s: non-BodyRig worker header crossed proxy: %q", path, got)
		}
	}
}
