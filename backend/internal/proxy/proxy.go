package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Client forwards HTTP requests to a single upstream base URL and streams the
// response back to the caller (supports NDJSON streaming, e.g. Ollama /api/chat).
type Client struct {
	BaseURL    string
	HealthPath string
	AuthToken  string // if set, sent as "Authorization: Bearer <token>" (e.g. Ollama Cloud)
	http       *http.Client
}

// New builds a Client. HealthPath defaults to /healthz; override with
// WithHealthPath for Ollama (/api/tags).
func New(baseURL string, timeout time.Duration) *Client {
	return &Client{
		BaseURL:    baseURL,
		HealthPath: "/healthz",
		http:       &http.Client{Timeout: timeout},
	}
}

// WithHealthPath sets the path used by Reachable and returns the client.
func (c *Client) WithHealthPath(p string) *Client {
	c.HealthPath = p
	return c
}

// WithTimeout returns a COPY of the client with a different request timeout.
// Needed because the default (120s) is right for chat but far too short for
// slow upstream work: the first voice turn loads Whisper large-v3 into VRAM
// before it even reaches the LLM, and ingesting a large PDF means many
// embedding calls. Verified on Anders' rig 2026-07-09: the 120s server-side
// timeout cut the voice request and surfaced on the phone as "Software caused
// connection abort" -- fixing only the Android client wasn't enough, because
// the shortest timeout in the chain wins.
func (c *Client) WithTimeout(d time.Duration) *Client {
	clone := *c
	clone.http = &http.Client{Timeout: d}
	return &clone
}

// WithAuthToken sets a bearer token forwarded on every upstream request. Empty
// token is a no-op (local Ollama needs none; Ollama Cloud needs its API key).
func (c *Client) WithAuthToken(t string) *Client {
	c.AuthToken = t
	return c
}

// Forward proxies r to c.BaseURL+upstreamPath and streams the response to w.
func (c *Client) Forward(w http.ResponseWriter, r *http.Request, upstreamPath string) {
	c.forward(w, r, upstreamPath, nil, "", "")
}

// ForwardWithHeaders is the narrow escape hatch for gateway-created internal
// claims. Only the explicitly supplied headers are added; arbitrary client
// headers are still not copied upstream. This lets a handler overwrite a
// spoofed inbound claim instead of widening the generic proxy trust boundary.
func (c *Client) ForwardWithHeaders(
	w http.ResponseWriter,
	r *http.Request,
	upstreamPath string,
	headers map[string]string,
) {
	c.forward(w, r, upstreamPath, headers, "", "")
}

// ForwardWithHeadersAndResponseAttestation forwards gateway-created internal
// headers and refuses to expose the upstream body unless the worker identifies
// the exact implementation that served it. It is intentionally header-specific:
// callers cannot turn this into a generic response-header trust mechanism.
func (c *Client) ForwardWithHeadersAndResponseAttestation(
	w http.ResponseWriter,
	r *http.Request,
	upstreamPath string,
	headers map[string]string,
	requiredHeader string,
	requiredValue string,
) {
	c.forward(w, r, upstreamPath, headers, requiredHeader, requiredValue)
}

func (c *Client) forward(
	w http.ResponseWriter,
	r *http.Request,
	upstreamPath string,
	headers map[string]string,
	requiredHeader string,
	requiredValue string,
) {
	target := c.BaseURL + upstreamPath
	if r.URL.RawQuery != "" {
		if strings.Contains(upstreamPath, "?") {
			target += "&" + r.URL.RawQuery
		} else {
			target += "?" + r.URL.RawQuery
		}
	}
	req, err := http.NewRequestWithContext(r.Context(), r.Method, target, r.Body)
	if err != nil {
		http.Error(w, "bad upstream request", http.StatusInternalServerError)
		return
	}
	// Preserve the incoming body length so the upstream request is sent with a
	// Content-Length instead of being forced to chunked transfer encoding. Some
	// upstreams (and simple test servers) don't decode chunked request bodies.
	req.ContentLength = r.ContentLength
	if ct := r.Header.Get("Content-Type"); ct != "" {
		req.Header.Set("Content-Type", ct)
	}
	if acc := r.Header.Get("Accept"); acc != "" {
		req.Header.Set("Accept", acc)
	}
	if rid := r.Header.Get("X-Request-ID"); rid != "" {
		req.Header.Set("X-Request-ID", rid)
	}
	for name, value := range headers {
		name = strings.TrimSpace(name)
		if name == "" || strings.ContainsAny(name, "\r\n") || strings.ContainsAny(value, "\r\n") {
			http.Error(w, "invalid internal upstream header", http.StatusInternalServerError)
			return
		}
		req.Header.Set(name, value)
	}
	if c.AuthToken != "" {
		req.Header.Set("Authorization", "Bearer "+c.AuthToken)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		http.Error(w, "upstream unreachable: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	if requiredHeader != "" {
		if strings.ContainsAny(requiredHeader, "\r\n") || strings.ContainsAny(requiredValue, "\r\n") {
			http.Error(w, "invalid upstream response attestation", http.StatusInternalServerError)
			return
		}
		if resp.Header.Get(requiredHeader) != requiredValue {
			http.Error(w, "upstream response attestation missing", http.StatusBadGateway)
			return
		}
	}
	if ct := resp.Header.Get("Content-Type"); ct != "" {
		w.Header().Set("Content-Type", ct)
	}
	// Integrity attestations for renderer clients (body id, package and
	// member digests) ride on X-BodyRig-* and are meaningless without a way
	// to reach the client. A prefix, not a blanket copy: upstream internals
	// still stop here.
	for name, values := range resp.Header {
		if !strings.HasPrefix(http.CanonicalHeaderKey(name), "X-Bodyrig-") {
			continue
		}
		for _, v := range values {
			w.Header().Add(name, v)
		}
	}
	w.WriteHeader(resp.StatusCode)

	flusher, _ := w.(http.Flusher)
	buf := make([]byte, 4096)
	for {
		n, rerr := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := w.Write(buf[:n]); werr != nil {
				return
			}
			if flusher != nil {
				flusher.Flush()
			}
		}
		if rerr != nil {
			return
		}
	}
}

// Reachable does a short GET against HealthPath to check upstream availability.
// GetJSON reads an upstream endpoint into out. Unlike Forward it does not
// touch the caller's ResponseWriter — the backend needs the DATA when it acts
// on the upstream's behalf (e.g. unloading models) rather than relaying.
func (c *Client) GetJSON(ctx context.Context, upstreamPath string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.BaseURL+upstreamPath, nil)
	if err != nil {
		return err
	}
	if c.AuthToken != "" {
		req.Header.Set("Authorization", "Bearer "+c.AuthToken)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("upstream %s returned %d", upstreamPath, resp.StatusCode)
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

// PostJSON sends body as JSON and discards the response body, returning an
// error for any non-2xx status so callers cannot mistake a refusal for success.
func (c *Client) PostJSON(ctx context.Context, upstreamPath string, body any) error {
	payload, err := json.Marshal(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.BaseURL+upstreamPath, bytes.NewReader(payload))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.AuthToken != "" {
		req.Header.Set("Authorization", "Bearer "+c.AuthToken)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, resp.Body)
	if resp.StatusCode >= 300 {
		return fmt.Errorf("upstream %s returned %d", upstreamPath, resp.StatusCode)
	}
	return nil
}

func (c *Client) Reachable() bool {
	client := &http.Client{Timeout: 3 * time.Second}
	req, err := http.NewRequest(http.MethodGet, c.BaseURL+c.HealthPath, nil)
	if err != nil {
		return false
	}
	if c.AuthToken != "" {
		req.Header.Set("Authorization", "Bearer "+c.AuthToken)
	}
	resp, err := client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode < 500
}
