package proxy

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// A pull is a long NDJSON stream whose LAST line ({"status":"success"}) is the
// only proof of completion -- the client treats stream end without it as a
// failed download (audit 1.58.36 #7). These tests pin the proxy's side of that
// contract: everything the upstream sends arrives, in order, including the
// final line; and an upstream that dies mid-stream produces a truthful,
// truncated passthrough (no synthesized success, no error page glued on).

func TestForward_StreamsNDJSONToEnd(t *testing.T) {
	lines := []string{
		`{"status":"pulling manifest"}`,
		`{"status":"downloading","completed":1,"total":2}`,
		`{"status":"success"}`,
	}
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		fl := w.(http.Flusher)
		for _, l := range lines {
			fmt.Fprintln(w, l)
			fl.Flush()
			time.Sleep(20 * time.Millisecond) // force separate chunks
		}
	}))
	defer up.Close()

	c := New(up.URL, 5*time.Second)
	req := httptest.NewRequest("POST", "/api/v1/models/pull", strings.NewReader(`{"model":"m"}`))
	rec := httptest.NewRecorder()
	c.Forward(rec, req, "/api/pull")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	body := rec.Body.String()
	for _, l := range lines {
		if !strings.Contains(body, l) {
			t.Errorf("line missing from passthrough: %s", l)
		}
	}
	if !strings.HasSuffix(strings.TrimSpace(body), `{"status":"success"}`) {
		t.Errorf("success must be the last line, got tail: %q", body[max(0, len(body)-60):])
	}
}

func TestForward_PassthroughWhenUpstreamCutsEarly(t *testing.T) {
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fl := w.(http.Flusher)
		fmt.Fprintln(w, `{"status":"downloading","completed":1,"total":9}`)
		fl.Flush()
		// die without a success line -- like a timeout or a crashed upstream
	}))
	defer up.Close()

	c := New(up.URL, 5*time.Second)
	req := httptest.NewRequest("POST", "/api/v1/models/pull", strings.NewReader(`{"model":"m"}`))
	rec := httptest.NewRecorder()
	c.Forward(rec, req, "/api/pull")

	body := rec.Body.String()
	if !strings.Contains(body, `"downloading"`) {
		t.Errorf("progress line should pass through, got: %q", body)
	}
	if strings.Contains(body, `"success"`) {
		t.Errorf("no success may be synthesized on an early cut, got: %q", body)
	}
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
