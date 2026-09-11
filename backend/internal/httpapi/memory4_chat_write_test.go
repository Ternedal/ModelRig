package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func memory4ValidTurnWriteReceipt() map[string]any {
	return map[string]any{
		"schema":            memory4TurnWriteReceiptSchema,
		"candidate_count":   1,
		"considered_count":  1,
		"created_count":     1,
		"superseded_count":  0,
		"deduped_count":     0,
		"skipped_count":     0,
		"created_ids":       []string{"memory-w04b-1"},
		"superseded_ids":    []string{},
		"superseding_ids":   []string{},
		"deduped_ids":       []string{},
		"replayed":          false,
		"sent_to_store":     true,
	}
}

type memory4FlushRecorder struct {
	header  http.Header
	status  int
	body    bytes.Buffer
	flushes int
}

func newMemory4FlushRecorder() *memory4FlushRecorder {
	return &memory4FlushRecorder{header: make(http.Header)}
}

func (w *memory4FlushRecorder) Header() http.Header { return w.header }

func (w *memory4FlushRecorder) WriteHeader(status int) {
	if w.status == 0 {
		w.status = status
	}
}

func (w *memory4FlushRecorder) Write(p []byte) (int, error) {
	if w.status == 0 {
		w.status = http.StatusOK
	}
	return w.body.Write(p)
}

func (w *memory4FlushRecorder) Flush() { w.flushes++ }

func TestMemory4ChatBothFlagsOffKeepsDirectProxyContract(t *testing.T) {
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")
	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer worker.Close()

	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		_, _ = w.Write([]byte(`{"message":{"role":"assistant","content":"ok"},"done":true}`))
	}))
	defer ollama.Close()

	raw := "{\n \"model\":\"qwen\", \"messages\":[{\"role\":\"user\",\"content\":\"hello\"}], \"stream\":true\n}"
	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(raw))
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 0 {
		t.Fatalf("disabled Memory 4 write/read reached worker %d time(s)", workerHits.Load())
	}
	if modelBody != raw {
		t.Fatalf("disabled flags changed model body: got=%q want=%q", modelBody, raw)
	}
}

func TestMemory4ChatWriteOnlyStreamsExactBytesFlushesAndPostsOriginalTurn(t *testing.T) {
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "1")

	var terminalSent atomic.Bool
	var writeHits atomic.Int32
	var posted memory4CompletedTurnWriteRequest
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != memory4CompletedTurnWritePath {
			t.Errorf("worker path=%q", r.URL.Path)
		}
		if !terminalSent.Load() {
			t.Error("W04-B write arrived before Ollama terminal frame")
		}
		writeHits.Add(1)
		if err := json.NewDecoder(r.Body).Decode(&posted); err != nil {
			t.Errorf("decode completed turn: %v", err)
		}
		writeJSON(w, http.StatusOK, memory4ValidTurnWriteReceipt())
	}))
	defer worker.Close()

	const response = "{\"message\":{\"role\":\"assistant\",\"content\":\"Hello \"},\"done\":false}\n" +
		"{\"message\":{\"role\":\"assistant\",\"content\":\"world\"},\"done\":true}\n"
	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		parts := strings.Split(response, "\n")
		for index, part := range parts {
			if part == "" {
				continue
			}
			_, _ = io.WriteString(w, part+"\n")
			if index == 1 {
				terminalSent.Store(true)
			}
			if flusher, ok := w.(http.Flusher); ok {
				flusher.Flush()
			}
		}
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"user","content":" remember this "}],"stream":true}`
	req := memory4Request(raw)
	req.Header.Set("X-Request-ID", "client-controlled-provenance")
	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := newMemory4FlushRecorder()
	s.handleMemory4Chat(rec, req)

	if rec.status != http.StatusOK || rec.body.String() != response {
		t.Fatalf("stream changed: status=%d body=%q", rec.status, rec.body.String())
	}
	if rec.flushes == 0 {
		t.Fatal("W04-B observer did not preserve downstream Flush calls")
	}
	if modelBody != raw {
		t.Fatalf("write-only mode changed model body: got=%q want=%q", modelBody, raw)
	}
	if writeHits.Load() != 1 {
		t.Fatalf("write hits=%d want=1", writeHits.Load())
	}
	if posted.UserText != "remember this" || posted.AssistantText != "Hello world" {
		t.Fatalf("posted turn mismatch: %+v", posted)
	}
	if !strings.HasPrefix(posted.SourceRef, "chat:") || posted.SourceRef == "client-controlled-provenance" {
		t.Fatalf("source_ref is not server-owned: %q", posted.SourceRef)
	}
}

func TestMemory4ChatReadAndWritePersistsOriginalUserNotInjectedContext(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	t.Setenv(memory4ChatWriteFlag, "1")
	context := "----- BEGIN KALIV MEMORY DATA -----\n{\"items\":[{\"value\":\"espresso\"}]}\n----- END KALIV MEMORY DATA -----"
	var contextHits, writeHits atomic.Int32
	var posted memory4CompletedTurnWriteRequest
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case memory4ContextPath:
			contextHits.Add(1)
			writeJSON(w, http.StatusOK, memory4ReceiptResponse(context, "local", 1, 1, []string{"memory-ctx"}))
		case memory4CompletedTurnWritePath:
			writeHits.Add(1)
			if err := json.NewDecoder(r.Body).Decode(&posted); err != nil {
				t.Errorf("decode completed turn: %v", err)
			}
			writeJSON(w, http.StatusOK, memory4ValidTurnWriteReceipt())
		default:
			t.Errorf("unexpected worker path %q", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		_, _ = io.WriteString(w, `{"message":{"role":"assistant","content":"You like espresso."},"done":true}`)
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"user","content":"what do I like?"}],"stream":false}`
	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(raw))
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if contextHits.Load() != 1 || writeHits.Load() != 1 {
		t.Fatalf("worker calls context=%d write=%d", contextHits.Load(), writeHits.Load())
	}
	if !strings.Contains(modelBody, context) || !strings.Contains(modelBody, memory4CurrentUserBegin) {
		t.Fatalf("R05 model body did not receive verified context: %s", modelBody)
	}
	if posted.UserText != "what do I like?" || strings.Contains(posted.UserText, "KALIV MEMORY DATA") || strings.Contains(posted.UserText, "espresso") {
		t.Fatalf("W04-B persisted injected context instead of original user text: %+v", posted)
	}
	if posted.AssistantText != "You like espresso." {
		t.Fatalf("assistant text=%q", posted.AssistantText)
	}
}

func TestMemory4ChatWriteSuppressionNeverChangesClientStream(t *testing.T) {
	cases := []struct {
		name     string
		response string
	}{
		{name: "malformed", response: "not-json\n"},
		{name: "truncated", response: `{"message":{"role":"assistant","content":"partial"},"done":false}` + "\n"},
		{name: "oversized", response: `{"message":{"role":"assistant","content":"` + strings.Repeat("x", memory4MaxCompletedTurnCharacters+1) + `"},"done":true}` + "\n"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv(memory4ChatFlag, "0")
			t.Setenv(memory4ChatWriteFlag, "1")
			var writeHits atomic.Int32
			worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				writeHits.Add(1)
				writeJSON(w, http.StatusOK, memory4ValidTurnWriteReceipt())
			}))
			defer worker.Close()
			ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/x-ndjson")
				_, _ = io.WriteString(w, tc.response)
			}))
			defer ollama.Close()

			s := memory4DirectServer(worker.URL, ollama.URL)
			rec := httptest.NewRecorder()
			s.handleMemory4Chat(rec, memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"hello"}],"stream":true}`))
			if rec.Code != http.StatusOK || rec.Body.String() != tc.response {
				t.Fatalf("client stream changed status=%d body-size=%d", rec.Code, rec.Body.Len())
			}
			if writeHits.Load() != 0 {
				t.Fatalf("invalid stream produced %d durable write call(s)", writeHits.Load())
			}
		})
	}
}

func TestMemory4ChatWorkerRefusalAfterTerminalIsNonFatal(t *testing.T) {
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "1")
	var writeHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeHits.Add(1)
		writeErr(w, http.StatusServiceUnavailable, "injected refusal")
	}))
	defer worker.Close()
	const response = `{"message":{"role":"assistant","content":"still succeeds"},"done":true}`
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, response)
	}))
	defer ollama.Close()

	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"hello"}],"stream":false}`))
	if rec.Code != http.StatusOK || rec.Body.String() != response {
		t.Fatalf("memory refusal changed chat: status=%d body=%q", rec.Code, rec.Body.String())
	}
	if writeHits.Load() != 1 {
		t.Fatalf("write hits=%d want=1", writeHits.Load())
	}
}

func TestMemory4ChatWriteRequiresLoopbackWorkerWithoutBreakingChat(t *testing.T) {
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "1")
	const response = `{"message":{"role":"assistant","content":"local chat"},"done":true}`
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, response)
	}))
	defer ollama.Close()

	s := memory4DirectServer("http://192.0.2.20:8099", ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"hello"}],"stream":false}`))
	if rec.Code != http.StatusOK || rec.Body.String() != response {
		t.Fatalf("non-loopback write config changed chat: status=%d body=%q", rec.Code, rec.Body.String())
	}
}

func TestMemory4CompletedTurnWriteReceiptIsStrict(t *testing.T) {
	t.Setenv(memory4ChatWriteFlag, "1")
	invalid := memory4ValidTurnWriteReceipt()
	invalid["candidate_value"] = "must-not-be-accepted"
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, invalid)
	}))
	defer worker.Close()

	s := memory4DirectServer(worker.URL, "http://127.0.0.1:11434")
	req := memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"hello"}]}`)
	err := s.requestMemory4CompletedTurnWrite(req, memory4CompletedTurnWriteRequest{
		UserText:      "hello",
		AssistantText: "hi",
		SourceRef:     "chat:00000000000000000000000000000000",
	})
	if err == nil {
		t.Fatal("write receipt with unknown private-looking field was accepted")
	}
}
