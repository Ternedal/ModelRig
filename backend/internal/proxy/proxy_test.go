package proxy

import (
	"bufio"
	"context"
	"fmt"
	"io"
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

// Stop in the Android voice UI must cancel its OkHttp request, and that
// cancellation must travel across the authenticated backend proxy to the
// worker. Test real HTTP sockets: httptest.NewRecorder cannot model a
// disconnected client correctly.
func TestForward_VoiceDisconnectCancelsWorkerRequest(t *testing.T) {
	upstreamCancelled := make(chan struct{})
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		flusher := w.(http.Flusher)
		fmt.Fprintln(w, `{"type":"transcript","text":"hej"}`)
		flusher.Flush()
		<-r.Context().Done()
		close(upstreamCancelled)
	}))
	defer up.Close()

	proxyClient := New(up.URL, 10*time.Second)
	gateway := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		proxyClient.Forward(w, r, "/voice/converse/stream")
	}))
	defer gateway.Close()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		gateway.URL+"/api/v1/voice/converse/stream", strings.NewReader(`{"audio_base64":"dGVzdA=="}`))
	if err != nil {
		t.Fatal(err)
	}
	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	// The transcript proves the upstream stream was already established;
	// cancelling before that point would not exercise the live cleanup path.
	line, err := bufio.NewReader(resp.Body).ReadString('\n')
	if err != nil {
		t.Fatalf("could not read first NDJSON event: %v", err)
	}
	if !strings.Contains(line, `"type":"transcript"`) {
		t.Fatalf("unexpected first voice event: %q", line)
	}
	cancel()
	select {
	case <-upstreamCancelled:
		// Upstream sees cancellation and can clean temporary WAV state.
	case <-time.After(3 * time.Second):
		t.Fatal("backend did not propagate disconnected voice client to worker")
	}
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// History belongs to the spoken conversation; the Go gateway must not
// silently remove it before it reaches the worker. These are real HTTP
// requests but use a local stub upstream, never the production worker.
func TestForward_VoiceHistoryRequestBodyIsPreserved(t *testing.T) {
    payload := `{"audio_base64":"UklGRg==","language":"da","history":[{"role":"user","content":"blå elefant"},{"role":"assistant","content":"Jeg husker det."}]}`
    for _, target := range []string{"/voice/converse/upload", "/voice/converse/stream"} {
        t.Run(target, func(t *testing.T) {
            received := make(chan string, 1)
            up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
                body, err := io.ReadAll(r.Body)
                if err != nil || r.Method != http.MethodPost || r.Header.Get("Content-Type") != "application/json" {
                    received <- "invalid upstream request"
                    w.WriteHeader(http.StatusBadRequest)
                    return
                }
                received <- string(body)
                w.Header().Set("Content-Type", "application/x-ndjson")
                fmt.Fprintln(w, `{"type":"done","reply":"ok"}`)
            }))
            defer up.Close()

            client := New(up.URL, 5*time.Second)
            req := httptest.NewRequest(http.MethodPost, "/api/v1"+target, strings.NewReader(payload))
            req.Header.Set("Content-Type", "application/json")
            rec := httptest.NewRecorder()
            client.Forward(rec, req, target)
            if rec.Code != http.StatusOK {
                t.Fatalf("proxy failed with %d: %s", rec.Code, rec.Body.String())
            }
            select {
            case got := <-received:
                if got != payload {
                    t.Fatalf("voice request body changed in Go proxy: got %q", got)
                }
            case <-time.After(3 * time.Second):
                t.Fatal("worker did not receive the voice request")
            }
        })
    }
}
