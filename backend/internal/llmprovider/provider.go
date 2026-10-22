package llmprovider

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"modelrig/internal/proxy"
)

// Provider preserves ModelRig's existing Ollama-shaped gateway contract while
// allowing the model runtime behind it to vary.
type Provider interface {
	Name() string
	Reachable() bool
	Models(http.ResponseWriter, *http.Request)
	Chat(http.ResponseWriter, *http.Request)
}

type Ollama struct {
	Client *proxy.Client
}

func NewOllama(c *proxy.Client) *Ollama { return &Ollama{Client: c} }
func (p *Ollama) Name() string          { return "ollama" }
func (p *Ollama) Reachable() bool       { return p.Client != nil && p.Client.Reachable() }
func (p *Ollama) Models(w http.ResponseWriter, r *http.Request) {
	p.Client.Forward(w, r, "/api/tags")
}
func (p *Ollama) Chat(w http.ResponseWriter, r *http.Request) {
	p.Client.Forward(w, r, "/api/chat")
}

// OpenAICompatible adapts OpenAI-compatible /v1 endpoints (Jan, llama.cpp,
// vLLM, LM Studio, LocalAI, etc.) to ModelRig's existing Ollama-shaped public
// API so desktop/Android/VR clients do not need a runtime-specific branch.
type OpenAICompatible struct {
	BaseURL   string
	AuthToken string
	Kind      string
	http      *http.Client
}

func NewOpenAICompatible(kind, baseURL, token string, timeout time.Duration) *OpenAICompatible {
	if timeout <= 0 {
		timeout = 120 * time.Second
	}
	return &OpenAICompatible{
		BaseURL:   strings.TrimRight(baseURL, "/"),
		AuthToken: token,
		Kind:      kind,
		http:      &http.Client{Timeout: timeout},
	}
}

func (p *OpenAICompatible) Name() string {
	if strings.TrimSpace(p.Kind) == "" {
		return "openai-compatible"
	}
	return p.Kind
}

func (p *OpenAICompatible) Reachable() bool {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, p.BaseURL+"/models", nil)
	if err != nil {
		return false
	}
	p.auth(req)
	resp, err := p.http.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode < 500
}

func (p *OpenAICompatible) Models(w http.ResponseWriter, r *http.Request) {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, p.BaseURL+"/models", nil)
	if err != nil {
		http.Error(w, "bad model upstream request", http.StatusInternalServerError)
		return
	}
	p.auth(req)
	resp, err := p.http.Do(req)
	if err != nil {
		http.Error(w, "model upstream unreachable: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		copyUpstreamError(w, resp)
		return
	}

	var body struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		http.Error(w, "invalid model upstream response", http.StatusBadGateway)
		return
	}
	models := make([]map[string]any, 0, len(body.Data))
	for _, m := range body.Data {
		if strings.TrimSpace(m.ID) == "" {
			continue
		}
		models = append(models, map[string]any{"name": m.ID, "model": m.ID})
	}
	writeJSON(w, http.StatusOK, map[string]any{"models": models})
}

type ollamaChatRequest struct {
	Model    string            `json:"model"`
	Messages []json.RawMessage `json:"messages"`
	Stream   *bool             `json:"stream,omitempty"`
	Think    any               `json:"think,omitempty"`
	Options  map[string]any    `json:"options,omitempty"`
}

func (p *OpenAICompatible) Chat(w http.ResponseWriter, r *http.Request) {
	var in ollamaChatRequest
	dec := json.NewDecoder(io.LimitReader(r.Body, 8<<20))
	if err := dec.Decode(&in); err != nil {
		http.Error(w, "invalid chat request", http.StatusBadRequest)
		return
	}
	if strings.TrimSpace(in.Model) == "" || len(in.Messages) == 0 {
		http.Error(w, "model and messages are required", http.StatusBadRequest)
		return
	}
	stream := true
	if in.Stream != nil {
		stream = *in.Stream
	}
	out := map[string]any{
		"model":    in.Model,
		"messages": in.Messages,
		"stream":   stream,
	}
	// Keep the first adapter deliberately conservative. Only options with a
	// direct OpenAI-compatible meaning are forwarded.
	if v, ok := in.Options["temperature"]; ok {
		out["temperature"] = v
	}
	if v, ok := in.Options["top_p"]; ok {
		out["top_p"] = v
	}
	if v, ok := in.Options["num_predict"]; ok {
		out["max_tokens"] = v
	}

	payload, err := json.Marshal(out)
	if err != nil {
		http.Error(w, "chat request encode failed", http.StatusInternalServerError)
		return
	}
	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost, p.BaseURL+"/chat/completions", bytes.NewReader(payload))
	if err != nil {
		http.Error(w, "bad chat upstream request", http.StatusInternalServerError)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream, application/json")
	if rid := r.Header.Get("X-Request-ID"); rid != "" {
		req.Header.Set("X-Request-ID", rid)
	}
	p.auth(req)

	resp, err := p.http.Do(req)
	if err != nil {
		http.Error(w, "chat upstream unreachable: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		copyUpstreamError(w, resp)
		return
	}
	if stream {
		p.streamChat(w, resp, in.Model)
		return
	}
	p.bufferedChat(w, resp, in.Model)
}

func (p *OpenAICompatible) bufferedChat(w http.ResponseWriter, resp *http.Response, model string) {
	var body struct {
		Choices []struct {
			Message struct {
				Role    string `json:"role"`
				Content string `json:"content"`
			} `json:"message"`
			FinishReason any `json:"finish_reason"`
		} `json:"choices"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil || len(body.Choices) == 0 {
		http.Error(w, "invalid chat upstream response", http.StatusBadGateway)
		return
	}
	role := body.Choices[0].Message.Role
	if role == "" {
		role = "assistant"
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"model":   model,
		"message": map[string]any{"role": role, "content": body.Choices[0].Message.Content},
		"done":    true,
	})
}

func (p *OpenAICompatible) streamChat(w http.ResponseWriter, resp *http.Response, model string) {
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.WriteHeader(http.StatusOK)
	flusher, _ := w.(http.Flusher)
	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 64*1024), 4<<20)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, ":") {
			continue
		}
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if data == "[DONE]" {
			_ = json.NewEncoder(w).Encode(map[string]any{"model": model, "message": map[string]any{"role": "assistant", "content": ""}, "done": true})
			if flusher != nil {
				flusher.Flush()
			}
			return
		}
		var chunk struct {
			Choices []struct {
				Delta struct {
					Role    string `json:"role"`
					Content string `json:"content"`
				} `json:"delta"`
				FinishReason any `json:"finish_reason"`
			} `json:"choices"`
		}
		if json.Unmarshal([]byte(data), &chunk) != nil || len(chunk.Choices) == 0 {
			continue
		}
		role := chunk.Choices[0].Delta.Role
		if role == "" {
			role = "assistant"
		}
		if chunk.Choices[0].Delta.Content != "" {
			_ = json.NewEncoder(w).Encode(map[string]any{
				"model": model,
				"message": map[string]any{"role": role, "content": chunk.Choices[0].Delta.Content},
				"done": false,
			})
			if flusher != nil {
				flusher.Flush()
			}
		}
		if chunk.Choices[0].FinishReason != nil {
			_ = json.NewEncoder(w).Encode(map[string]any{"model": model, "message": map[string]any{"role": "assistant", "content": ""}, "done": true})
			if flusher != nil {
				flusher.Flush()
			}
			return
		}
	}
}

func (p *OpenAICompatible) auth(req *http.Request) {
	if p.AuthToken != "" {
		req.Header.Set("Authorization", "Bearer "+p.AuthToken)
	}
}

func copyUpstreamError(w http.ResponseWriter, resp *http.Response) {
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64<<10))
	if ct := resp.Header.Get("Content-Type"); ct != "" {
		w.Header().Set("Content-Type", ct)
	}
	w.WriteHeader(resp.StatusCode)
	if len(body) > 0 {
		_, _ = w.Write(body)
		return
	}
	_, _ = fmt.Fprintf(w, "upstream returned %d", resp.StatusCode)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
