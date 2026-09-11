package httpapi

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
	"unicode/utf8"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

const memory4TestToken = "memory4-chat-test-token"

func memory4ReceiptResponse(context, target string, candidateCount, rankedCount int, includedIDs []string) map[string]any {
	sum := sha256.Sum256([]byte(context))
	notRelevant := candidateCount - rankedCount
	contextBudget := rankedCount - len(includedIDs)
	return map[string]any{
		"schema":  memory4ContextServiceSchema,
		"context": context,
		"receipt": map[string]any{
			"schema":           memory4ContextReceiptSchema,
			"target":           target,
			"semantic_enabled": false,
			"candidate_count":  candidateCount,
			"ranked_count":     rankedCount,
			"included_ids":     includedIDs,
			"excluded_count":   notRelevant + contextBudget,
			"exclusion_reasons": map[string]int{
				"not_relevant_or_below_threshold": notRelevant,
				"context_budget":                   contextBudget,
			},
			"character_count": utf8.RuneCountInString(context),
			"byte_count":      len([]byte(context)),
			"context_sha256":  hex.EncodeToString(sum[:]),
			"sent_to_model":   false,
		},
	}
}

func memory4DirectServer(workerURL, ollamaURL string) *server {
	timeout := 2 * time.Second
	worker := proxy.New(workerURL, timeout)
	return &server{Deps: Deps{
		Cfg:        config.Config{RequestTimeout: timeout},
		Ollama:     proxy.New(ollamaURL, timeout),
		Worker:     worker,
		WorkerSlow: worker,
	}}
}

func memory4RouteHandler(t *testing.T, workerURL, ollamaURL string) http.Handler {
	t.Helper()
	st, err := store.Open(filepath.Join(t.TempDir(), "state.json"))
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	if err := st.AddDevice(store.Device{
		ID:        "memory4-device",
		Name:      "phone",
		TokenHash: auth.Hash(memory4TestToken),
		CreatedAt: time.Now(),
		LastSeen:  time.Now(),
	}); err != nil {
		t.Fatalf("AddDevice: %v", err)
	}
	timeout := 2 * time.Second
	worker := proxy.New(workerURL, timeout)
	return New(Deps{
		Cfg:        config.Config{ClaimMax: 5, RequestTimeout: timeout},
		Store:      st,
		Ollama:     proxy.New(ollamaURL, timeout),
		Worker:     worker,
		WorkerSlow: worker,
	})
}

func memory4Request(body string) *http.Request {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	return req
}

func TestMemory4ChatFlagOffPreservesExactBodyAndSkipsWorker(t *testing.T) {
	t.Setenv(memory4ChatFlag, "0")
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
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"done":true}`))
	}))
	defer ollama.Close()

	raw := "{\n  \"model\":\"qwen\", \"messages\":[{\"role\":\"user\",\"content\":\"hello\"}], \"stream\":false, \"options\":{\"temperature\":0.2}\n}"
	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(raw))
	if rec.Code != http.StatusOK {
		t.Fatalf("got %d body=%s", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 0 {
		t.Fatalf("flag-off chat reached memory worker %d time(s)", workerHits.Load())
	}
	if modelBody != raw {
		t.Fatalf("flag-off body changed:\n got: %q\nwant: %q", modelBody, raw)
	}
}

func TestMemory4ChatEmptyContextPreservesExactBody(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		if r.URL.Path != memory4ContextPath {
			t.Errorf("worker path=%q", r.URL.Path)
		}
		var req memory4ContextRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Errorf("decode worker request: %v", err)
		}
		if req.Query != "remember me" || req.Target != "local" || req.MaxResults != memory4DefaultContextMaxResults || req.MaxContextChars != memory4MaxContextCharacters {
			t.Errorf("unexpected worker request: %+v", req)
		}
		writeJSON(w, http.StatusOK, memory4ReceiptResponse("", "local", 0, 0, []string{}))
	}))
	defer worker.Close()

	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		w.WriteHeader(http.StatusOK)
	}))
	defer ollama.Close()

	raw := `{ "model":"qwen", "messages":[{"role":"user","content":" remember me "}], "stream":true }`
	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(raw))
	if rec.Code != http.StatusOK {
		t.Fatalf("got %d body=%s", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 1 {
		t.Fatalf("worker hits=%d, want 1", workerHits.Load())
	}
	if modelBody != raw {
		t.Fatalf("empty-context body changed:\n got: %q\nwant: %q", modelBody, raw)
	}
}

func TestMemory4ChatVerifiedContextStaysInsideFinalUserData(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	context := "----- BEGIN KALIV MEMORY DATA -----\n{\"items\":[{\"value\":\"likes espresso\"}]}\n----- END KALIV MEMORY DATA -----"
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "" {
			t.Errorf("backend leaked client authorization to loopback worker: %q", got)
		}
		writeJSON(w, http.StatusOK, memory4ReceiptResponse(context, "local", 2, 1, []string{"memory-1"}))
	}))
	defer worker.Close()

	var modelBody []byte
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelBody, _ = io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"system","content":"be concise"},{"role":"user","content":"what do I like?"}],"stream":false,"options":{"temperature":0.1}}`
	s := memory4DirectServer(worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(raw))
	if rec.Code != http.StatusOK {
		t.Fatalf("got %d body=%s", rec.Code, rec.Body.String())
	}

	var got struct {
		Model    string `json:"model"`
		Messages []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
		Stream  bool `json:"stream"`
		Options struct {
			Temperature float64 `json:"temperature"`
		} `json:"options"`
	}
	if err := json.Unmarshal(modelBody, &got); err != nil {
		t.Fatalf("model body JSON: %v body=%s", err, string(modelBody))
	}
	if got.Model != "qwen" || got.Stream || got.Options.Temperature != 0.1 {
		t.Fatalf("non-message chat fields changed: %+v", got)
	}
	if len(got.Messages) != 2 {
		t.Fatalf("message count=%d, want 2", len(got.Messages))
	}
	if got.Messages[0].Role != "system" || got.Messages[0].Content != "be concise" {
		t.Fatalf("original system message changed: %+v", got.Messages[0])
	}
	expectedUser := memory4ModelReferencePrefix + context + "\n\n" + memory4CurrentUserBegin + "\nwhat do I like?\n" + memory4CurrentUserEnd
	if got.Messages[1].Role != "user" || got.Messages[1].Content != expectedUser {
		t.Fatalf("memory/current-turn user data mismatch: %+v", got.Messages[1])
	}
	if strings.Contains(got.Messages[0].Content, "KALIV MEMORY DATA") {
		t.Fatal("memory data must never be promoted into the system message")
	}
	bodyText := string(modelBody)
	if strings.Contains(bodyText, "context_sha256") || strings.Contains(bodyText, "sent_to_model") || strings.Contains(bodyText, "included_ids") {
		t.Fatalf("R04 receipt leaked into model payload: %s", bodyText)
	}
}

func TestMemory4ChatRejectsTamperedReceiptBeforeModel(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		resp := memory4ReceiptResponse("trusted context", "local", 1, 1, []string{"memory-1"})
		receipt := resp["receipt"].(map[string]any)
		receipt["context_sha256"] = strings.Repeat("0", 64)
		writeJSON(w, http.StatusOK, resp)
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
	s.handleMemory4Chat(rec, memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"hello"}]}`))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("got %d, want 503; body=%s", rec.Code, rec.Body.String())
	}
	if modelHits.Load() != 0 {
		t.Fatalf("tampered receipt reached model %d time(s)", modelHits.Load())
	}
}

func TestMemory4ChatRefusesNonLoopbackWorkerBeforeMemoryOrModelEgress(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer ollama.Close()

	s := memory4DirectServer("http://192.0.2.20:8099", ollama.URL)
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(`{"model":"qwen","messages":[{"role":"user","content":"hello"}]}`))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("got %d, want 503; body=%s", rec.Code, rec.Body.String())
	}
	if modelHits.Load() != 0 {
		t.Fatalf("non-loopback memory configuration reached model %d time(s)", modelHits.Load())
	}
}

func TestMemory4ChatNonLoopbackModelIsCloudTarget(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	var target string
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req memory4ContextRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Errorf("decode worker request: %v", err)
		}
		target = req.Target
		w.WriteHeader(http.StatusServiceUnavailable) // stop before any model call
	}))
	defer worker.Close()

	s := memory4DirectServer(worker.URL, "https://ollama.example.invalid")
	rec := httptest.NewRecorder()
	s.handleMemory4Chat(rec, memory4Request(`{"model":"cloud-model","messages":[{"role":"user","content":"hello"}]}`))
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("got %d, want 503", rec.Code)
	}
	if target != "cloud" {
		t.Fatalf("worker target=%q, want cloud", target)
	}
}

func TestMemory4ChatUnsupportedTurnPreservesBaselineWithoutWorker(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer worker.Close()
	var modelBodies []string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBodies = append(modelBodies, string(body))
		w.WriteHeader(http.StatusOK)
	}))
	defer ollama.Close()

	cases := []string{
		// Multimodal/non-string content remains Ollama's responsibility in R05.
		`{"model":"qwen","messages":[{"role":"user","content":{"type":"image"}}],"stream":false}`,
		// R05 only treats a final text-user message as the current turn.
		`{"model":"qwen","messages":[{"role":"user","content":"older turn"},{"role":"assistant","content":"continue"}],"stream":false}`,
	}
	s := memory4DirectServer(worker.URL, ollama.URL)
	for _, raw := range cases {
		rec := httptest.NewRecorder()
		s.handleMemory4Chat(rec, memory4Request(raw))
		if rec.Code != http.StatusOK {
			t.Fatalf("got %d body=%s for %s", rec.Code, rec.Body.String(), raw)
		}
	}
	if workerHits.Load() != 0 {
		t.Fatalf("unsupported turn reached memory worker %d time(s)", workerHits.Load())
	}
	if len(modelBodies) != len(cases) {
		t.Fatalf("model bodies=%d, want %d", len(modelBodies), len(cases))
	}
	for i, raw := range cases {
		if modelBodies[i] != raw {
			t.Fatalf("unsupported turn body changed:\n got: %q\nwant: %q", modelBodies[i], raw)
		}
	}
}

func TestMemory4ChatPublicRouteUsesR05BehindExistingBearerAuth(t *testing.T) {
	t.Setenv(memory4ChatFlag, "1")
	context := "----- BEGIN KALIV MEMORY DATA -----\n{\"items\":[{\"value\":\"route proof\"}]}\n----- END KALIV MEMORY DATA -----"
	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		if got := r.Header.Get("Authorization"); got != "" {
			t.Errorf("paired-device Authorization leaked to worker: %q", got)
		}
		writeJSON(w, http.StatusOK, memory4ReceiptResponse(context, "local", 1, 1, []string{"memory-route"}))
	}))
	defer worker.Close()
	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		w.WriteHeader(http.StatusOK)
	}))
	defer ollama.Close()

	h := memory4RouteHandler(t, worker.URL, ollama.URL)
	raw := `{"model":"qwen","messages":[{"role":"user","content":"route test"}],"stream":false}`
	unauth := httptest.NewRecorder()
	h.ServeHTTP(unauth, memory4Request(raw))
	if unauth.Code != http.StatusUnauthorized {
		t.Fatalf("unauth got %d, want 401", unauth.Code)
	}
	if workerHits.Load() != 0 {
		t.Fatalf("unauthenticated chat reached memory worker")
	}

	req := memory4Request(raw)
	req.Header.Set("Authorization", "Bearer "+memory4TestToken)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("auth got %d body=%s", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 1 {
		t.Fatalf("worker hits=%d, want 1", workerHits.Load())
	}
	var got struct {
		Messages []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
	}
	if err := json.Unmarshal([]byte(modelBody), &got); err != nil {
		t.Fatalf("decode public-route model body: %v body=%s", err, modelBody)
	}
	if len(got.Messages) != 1 || got.Messages[0].Role != "user" {
		t.Fatalf("unexpected public-route messages: %+v", got.Messages)
	}
	content := got.Messages[0].Content
	if !strings.Contains(content, "route proof") || !strings.Contains(content, memory4ModelReferencePrefix) || !strings.Contains(content, memory4CurrentUserBegin) {
		t.Fatalf("public route did not inject verified R05 context into user data: %q", content)
	}
}
