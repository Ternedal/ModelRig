package httpapi

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func TestMemory4ContextRedirectNeverReplaysPrivateQuery(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	t.Setenv(memory4ChatWriteFlag, "0")

	var redirectHits atomic.Int32
	var redirectedBody string
	redirectTarget := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		redirectHits.Add(1)
		body, _ := io.ReadAll(r.Body)
		redirectedBody = string(body)
		w.WriteHeader(http.StatusOK)
	}))
	defer redirectTarget.Close()

	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		if r.URL.Path != memory4ContextPath {
			t.Errorf("worker path=%q want=%q", r.URL.Path, memory4ContextPath)
		}
		w.Header().Set("Location", redirectTarget.URL+"/leak-target")
		w.WriteHeader(http.StatusTemporaryRedirect)
	}))
	defer worker.Close()

	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer ollama.Close()

	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	privateQuery := "R05 private redirect sentinel 6bdf3f"
	s.handleMemory4Chat(
		rec,
		memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"`+privateQuery+`"}],"stream":false}`),
	)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status=%d body=%s, want 503", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 1 {
		t.Fatalf("loopback worker hits=%d want=1", workerHits.Load())
	}
	if redirectHits.Load() != 0 {
		t.Fatalf("redirect target received %d request(s), body=%q", redirectHits.Load(), redirectedBody)
	}
	if strings.Contains(redirectedBody, privateQuery) {
		t.Fatalf("private R05 query was replayed to redirect target: %q", redirectedBody)
	}
	if modelHits.Load() != 0 {
		t.Fatalf("R05 redirect failure reached model %d time(s)", modelHits.Load())
	}
}

func TestMemory4CompletedTurnRedirectNeverReplaysPrivateTurnAndChatStaysSuccessful(t *testing.T) {
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "1")

	var redirectHits atomic.Int32
	var redirectedBody string
	redirectTarget := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		redirectHits.Add(1)
		body, _ := io.ReadAll(r.Body)
		redirectedBody = string(body)
		w.WriteHeader(http.StatusOK)
	}))
	defer redirectTarget.Close()

	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		if r.URL.Path != memory4CompletedTurnWritePath {
			t.Errorf("worker path=%q want=%q", r.URL.Path, memory4CompletedTurnWritePath)
		}
		w.Header().Set("Location", redirectTarget.URL+"/leak-target")
		w.WriteHeader(http.StatusTemporaryRedirect)
	}))
	defer worker.Close()

	const assistantText = "private assistant redirect sentinel c720ac"
	const modelResponse = `{"message":{"role":"assistant","content":"` + assistantText + `"},"done":true}`
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = io.WriteString(w, modelResponse)
	}))
	defer ollama.Close()

	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	privateUser := "private user redirect sentinel 2f88c0"
	s.handleMemory4Chat(
		rec,
		memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"`+privateUser+`"}],"stream":true}`),
	)

	if rec.Code != http.StatusOK || rec.Body.String() != modelResponse {
		t.Fatalf("post-turn redirect changed successful chat: status=%d body=%q", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 1 {
		t.Fatalf("loopback write worker hits=%d want=1", workerHits.Load())
	}
	if redirectHits.Load() != 0 {
		t.Fatalf("redirect target received %d request(s), body=%q", redirectHits.Load(), redirectedBody)
	}
	for _, privateValue := range []string{privateUser, assistantText, "chat:"} {
		if strings.Contains(redirectedBody, privateValue) {
			t.Fatalf("private completed-turn material %q was replayed to redirect target: %q", privateValue, redirectedBody)
		}
	}
}
