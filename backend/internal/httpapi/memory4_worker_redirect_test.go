package httpapi

import (
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func TestMemory4ContextWorkerRedirectCannotRelayPrivateQuery(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	t.Setenv(memory4ChatWriteFlag, "0")

	var redirectHits atomic.Int32
	redirectTarget := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		redirectHits.Add(1)
		_, _ = io.ReadAll(r.Body)
		writeJSON(w, http.StatusOK, map[string]any{"unexpected": "redirect target reached"})
	}))
	defer redirectTarget.Close()

	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		if r.URL.Path != memory4ContextPath {
			t.Errorf("worker path=%q", r.URL.Path)
		}
		http.Redirect(w, r, redirectTarget.URL+"/relay", http.StatusTemporaryRedirect)
	}))
	defer worker.Close()

	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		_, _ = io.WriteString(w, `{"message":{"role":"assistant","content":"must not run"},"done":true}`)
	}))
	defer ollama.Close()

	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"private-memory-query-h2"}],"stream":false}`))

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("redirected R05 worker status=%d body=%q", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 1 {
		t.Fatalf("loopback worker hits=%d want=1", workerHits.Load())
	}
	if redirectHits.Load() != 0 {
		t.Fatalf("R05 private query reached redirect target %d time(s)", redirectHits.Load())
	}
	if modelHits.Load() != 0 {
		t.Fatalf("R05 redirect failure still reached model %d time(s)", modelHits.Load())
	}
}

func TestMemory4CompletedTurnWorkerRedirectCannotRelayPrivateTurn(t *testing.T) {
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "1")

	var redirectHits atomic.Int32
	redirectTarget := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		redirectHits.Add(1)
		_, _ = io.ReadAll(r.Body)
		writeJSON(w, http.StatusOK, memory4ValidTurnWriteReceipt())
	}))
	defer redirectTarget.Close()

	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		if r.URL.Path != memory4CompletedTurnWritePath {
			t.Errorf("worker path=%q", r.URL.Path)
		}
		http.Redirect(w, r, redirectTarget.URL+"/relay", http.StatusTemporaryRedirect)
	}))
	defer worker.Close()

	const response = `{"message":{"role":"assistant","content":"private-assistant-turn-h2"},"done":true}`
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, response)
	}))
	defer ollama.Close()

	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"private-user-turn-h2"}],"stream":false}`))

	if rec.Code != http.StatusOK || rec.Body.String() != response {
		t.Fatalf("W04-B redirect refusal changed chat: status=%d body=%q", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 1 {
		t.Fatalf("loopback write worker hits=%d want=1", workerHits.Load())
	}
	if redirectHits.Load() != 0 {
		t.Fatalf("W04-B private completed turn reached redirect target %d time(s)", redirectHits.Load())
	}
}
