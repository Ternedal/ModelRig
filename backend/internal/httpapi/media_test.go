package httpapi

import (
    "io"
    "net/http"
    "net/http/httptest"
    "strings"
    "testing"
    "time"

    "modelrig/internal/proxy"
)

func TestMediaGatewayPreservesPartialContent(t *testing.T) {
    upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.URL.Path != "/experimental/media/clip_1" {
            t.Errorf("unexpected upstream path: %s", r.URL.Path)
        }
        if got := r.Header.Get("Range"); got != "bytes=2-5" {
            t.Errorf("range lost: %q", got)
        }
        w.Header().Set("Content-Type", "video/mp4")
        w.Header().Set("Content-Range", "bytes 2-5/10")
        w.Header().Set("Accept-Ranges", "bytes")
        w.Header().Set("Content-Length", "4")
        w.WriteHeader(http.StatusPartialContent)
        _, _ = io.WriteString(w, "2345")
    }))
    defer upstream.Close()
    s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
    request := httptest.NewRequest(http.MethodGet, "/api/v1/media/clip_1", nil)
    request.SetPathValue("id", "clip_1")
    request.Header.Set("Range", "bytes=2-5")
    recorder := httptest.NewRecorder()
    s.handleMediaFile(recorder, request)
    if recorder.Code != http.StatusPartialContent || recorder.Body.String() != "2345" {
        t.Fatalf("bad partial response: %d %q", recorder.Code, recorder.Body.String())
    }
    if got := recorder.Header().Get("Cache-Control"); got != "private, no-store" {
        t.Fatalf("media cache policy missing: %q", got)
    }
    if got := recorder.Header().Get("X-Content-Type-Options"); got != "nosniff" {
        t.Fatalf("media MIME sniff protection missing: %q", got)
    }
    if got := recorder.Header().Get("Content-Range"); got != "bytes 2-5/10" {
        t.Fatalf("content range lost: %q", got)
    }
}

func TestMediaGatewayHeadPreservesMetadataWithoutBody(t *testing.T) {
    upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.Method != http.MethodHead {
            t.Errorf("expected HEAD, got %s", r.Method)
        }
        w.Header().Set("Content-Type", "video/mp4")
        w.Header().Set("Content-Length", "1024")
        w.Header().Set("Accept-Ranges", "bytes")
        w.WriteHeader(http.StatusOK)
    }))
    defer upstream.Close()
    s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
    request := httptest.NewRequest(http.MethodHead, "/api/v1/media/clip_1", nil)
    request.SetPathValue("id", "clip_1")
    recorder := httptest.NewRecorder()
    s.handleMediaFile(recorder, request)
    if recorder.Code != http.StatusOK || recorder.Body.Len() != 0 {
        t.Fatalf("unexpected HEAD response: %d %q", recorder.Code, recorder.Body.String())
    }
    if got := recorder.Header().Get("Content-Length"); got != "1024" {
        t.Fatalf("content length lost: %q", got)
    }
}

func TestMediaGatewayForwards416ContentRange(t *testing.T) {
    upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Content-Range", "bytes */10")
        w.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
    }))
    defer upstream.Close()
    s := &server{Deps: Deps{Worker: proxy.New(upstream.URL, time.Second)}}
    request := httptest.NewRequest(http.MethodGet, "/api/v1/media/clip_1", nil)
    request.SetPathValue("id", "clip_1")
    request.Header.Set("Range", "bytes=999-")
    recorder := httptest.NewRecorder()
    s.handleMediaFile(recorder, request)
    if recorder.Code != http.StatusRequestedRangeNotSatisfiable {
        t.Fatalf("expected 416, got %d", recorder.Code)
    }
    if got := recorder.Header().Get("Content-Range"); got != "bytes */10" {
        t.Fatalf("missing unsatisfiable range metadata: %q", got)
    }
}

func TestMediaGatewayRejectsInvalidIDBeforeForward(t *testing.T) {
    s := &server{Deps: Deps{Worker: proxy.New("http://127.0.0.1:1", time.Second)}}
    request := httptest.NewRequest(http.MethodGet, "/api/v1/media/../secret", nil)
    request.SetPathValue("id", "../secret")
    recorder := httptest.NewRecorder()
    s.handleMediaFile(recorder, request)
    if recorder.Code != http.StatusNotFound {
        t.Fatalf("expected 404, got %d", recorder.Code)
    }
}

func TestMediaGatewayRejectsUnapprovedQuery(t *testing.T) {
    s := &server{Deps: Deps{Worker: proxy.New("http://127.0.0.1:1", time.Second)}}
    request := httptest.NewRequest(http.MethodGet, "/api/v1/media?path=/etc/passwd", nil)
    recorder := httptest.NewRecorder()
    s.handleMediaGallery(recorder, request)
    if recorder.Code != http.StatusBadRequest || !strings.Contains(recorder.Body.String(), "query") {
        t.Fatalf("unexpected response: %d %q", recorder.Code, recorder.Body.String())
    }
}
