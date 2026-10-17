package llmprovider

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestOpenAICompatibleModelsUsesOllamaShape(t *testing.T) {
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/models" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": []map[string]any{{"id": "jan-model"}}})
	}))
	defer up.Close()

	p := NewOpenAICompatible("jan", up.URL+"/v1", "", time.Second)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/models", nil)
	rec := httptest.NewRecorder()
	p.Models(rec, req)

	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"name":"jan-model"`) {
		t.Fatalf("unexpected response: %d %s", rec.Code, rec.Body.String())
	}
}

func TestOpenAICompatibleBufferedChatTranslatesResponse(t *testing.T) {
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/chat/completions" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"choices": []map[string]any{{"message": map[string]any{"role": "assistant", "content": "hej"}}},
		})
	}))
	defer up.Close()

	p := NewOpenAICompatible("jan", up.URL+"/v1", "", time.Second)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat", strings.NewReader(`{"model":"m","stream":false,"messages":[{"role":"user","content":"hej"}]}`))
	rec := httptest.NewRecorder()
	p.Chat(rec, req)

	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"content":"hej"`) || !strings.Contains(rec.Body.String(), `"done":true`) {
		t.Fatalf("unexpected response: %d %s", rec.Code, rec.Body.String())
	}
}

func TestOpenAICompatibleStreamingChatTranslatesSSEToNDJSON(t *testing.T) {
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprintln(w, `data: {"choices":[{"delta":{"role":"assistant","content":"he"},"finish_reason":null}]}`)
		fmt.Fprintln(w)
		fmt.Fprintln(w, `data: {"choices":[{"delta":{"content":"j"},"finish_reason":null}]}`)
		fmt.Fprintln(w)
		fmt.Fprintln(w, "data: [DONE]")
	}))
	defer up.Close()

	p := NewOpenAICompatible("jan", up.URL, "", time.Second)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat", strings.NewReader(`{"model":"m","stream":true,"messages":[{"role":"user","content":"hej"}]}`))
	rec := httptest.NewRecorder()
	p.Chat(rec, req)

	scanner := bufio.NewScanner(strings.NewReader(rec.Body.String()))
	lines := []string{}
	for scanner.Scan() {
		if strings.TrimSpace(scanner.Text()) != "" {
			lines = append(lines, scanner.Text())
		}
	}
	if len(lines) != 3 {
		t.Fatalf("lines = %d: %q", len(lines), rec.Body.String())
	}
	if !strings.Contains(lines[0], `"content":"he"`) || !strings.Contains(lines[1], `"content":"j"`) || !strings.Contains(lines[2], `"done":true`) {
		t.Fatalf("unexpected stream: %q", rec.Body.String())
	}
}
