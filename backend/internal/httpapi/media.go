package httpapi

import (
    "io"
    "context"
    "errors"
    "net/http"
    "regexp"
    "net/url"
    "net"
    "strconv"
    "strings"
    "time"
)

// Media forwarding intentionally does NOT use proxy.Client.Forward:
// that generic proxy strips Range, Content-Range, Accept-Ranges and Content-Length.
var mediaIDPattern = regexp.MustCompile("^[A-Za-z0-9_-]{1,128}$")

func (s *server) forwardMedia(w http.ResponseWriter, r *http.Request, id string) {
    if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
        writeErr(w, http.StatusServiceUnavailable, "media requires loopback worker")
        return
    }
    if id != "" && !mediaIDPattern.MatchString(id) {
        writeErr(w, http.StatusNotFound, "unknown media")
        return
    }
    path := "/experimental/media"
    if id != "" {
        path += "/" + id
    }
    upstream, err := url.Parse(s.Worker.BaseURL)
    if err != nil || upstream.User != nil || upstream.RawQuery != "" || upstream.ForceQuery || upstream.Fragment != "" || upstream.Path != "" || upstream.RawPath != "" {
        writeErr(w, http.StatusServiceUnavailable, "invalid media worker origin")
        return
    }
    target := strings.TrimRight(s.Worker.BaseURL, "/") + path
    if id == "" {
        q := r.URL.Query()
        for key := range q {
            if key != "limit" && key != "offset" {
                writeErr(w, http.StatusBadRequest, "unknown media query")
                return
            }
            for _, value := range q[key] {
                if _, err := strconv.Atoi(value); err != nil {
                    writeErr(w, http.StatusBadRequest, "invalid pagination")
                    return
                }
            }
        }
        target += "?" + q.Encode()
    }
    req, err := http.NewRequestWithContext(r.Context(), r.Method, target, nil)
    if err != nil {
        writeErr(w, http.StatusInternalServerError, "invalid media request")
        return
    }
    if value := r.Header.Get("Range"); value != "" {
        req.Header.Set("Range", value)
    }
    // Dial the loopback address directly; never resolve a hostname through DNS.
    dialer := &net.Dialer{Timeout: 5 * time.Second}
    transport := &http.Transport{
        Proxy: nil,
        DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
            host, port, err := net.SplitHostPort(address)
            if err != nil { return nil, err }
            if host == "localhost" { host = "127.0.0.1" }
            ip := net.ParseIP(host)
            if ip == nil || !ip.IsLoopback() { return nil, errors.New("non-loopback media upstream") }
            return dialer.DialContext(ctx, network, net.JoinHostPort(host, port))
        },
    }
    client := &http.Client{
        Transport: transport,
        Timeout: 10 * time.Minute,
        CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
    }
    response, err := client.Do(req)
    if err != nil {
        writeErr(w, http.StatusBadGateway, "media worker unavailable")
        return
    }
    defer response.Body.Close()
    for _, key := range []string{
        "Content-Type", "Content-Length", "Content-Range", "Accept-Ranges",
        "Cache-Control", "X-Content-Type-Options",
    } {
        if value := response.Header.Get(key); value != "" {
            w.Header().Set(key, value)
        }
    }
    // Keep private generated media out of browser and intermediary caches.
    w.Header().Set("Cache-Control", "private, no-store")
    w.Header().Set("X-Content-Type-Options", "nosniff")
    w.Header().Set("X-Frame-Options", "DENY")
    w.WriteHeader(response.StatusCode)
    if r.Method != http.MethodHead {
        _, _ = io.Copy(w, response.Body)
    }
}

func (s *server) handleMediaGallery(w http.ResponseWriter, r *http.Request) {
    s.forwardMedia(w, r, "")
}

func (s *server) handleMediaFile(w http.ResponseWriter, r *http.Request) {
    s.forwardMedia(w, r, r.PathValue("id"))
}
