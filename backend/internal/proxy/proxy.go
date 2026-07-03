package proxy

import (
	"net/http"
	"strings"
	"time"
)

// Client forwards HTTP requests to a single upstream base URL and streams the
// response back to the caller (supports NDJSON streaming, e.g. Ollama /api/chat).
type Client struct {
	BaseURL    string
	HealthPath string
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

// Forward proxies r to c.BaseURL+upstreamPath and streams the response to w.
func (c *Client) Forward(w http.ResponseWriter, r *http.Request, upstreamPath string) {
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

	resp, err := c.http.Do(req)
	if err != nil {
		http.Error(w, "upstream unreachable: "+err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	if ct := resp.Header.Get("Content-Type"); ct != "" {
		w.Header().Set("Content-Type", ct)
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
func (c *Client) Reachable() bool {
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(c.BaseURL + c.HealthPath)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode < 500
}
