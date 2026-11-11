package httpapi

import (
    "errors"
    "encoding/json"
    "io"
    "net/http"
    "strconv"
)

// MediaCatalog is a trusted, installation-scoped adapter. Implementations MUST
// verify the external volume, completed-asset owner and descriptor identity
// before returning an opened asset. The HTTP layer never accepts an owner.
type MediaCatalog interface {
    ListMedia(owner string, limit int, cursor string) (items []map[string]any, nextCursor *string, err error)
    OpenMedia(owner string, id string) (io.ReadSeekCloser, string, int64, error)
}

var ErrMediaNotFound = errors.New("media asset not found")
var ErrMediaUnavailable = errors.New("media catalog unavailable")

func (s *server) handleMediaList(w http.ResponseWriter, r *http.Request) {
    // Include errors and empty responses: authenticated media metadata must never be cached.
    w.Header().Set("Cache-Control", "private, no-store")
    if s.Media == nil { http.Error(w, "media unavailable", http.StatusServiceUnavailable); return }
    query := r.URL.Query()
    if len(query["limit"]) > 1 || len(query["cursor"]) > 1 {
        http.Error(w, "duplicate query parameter", http.StatusBadRequest); return
    }
    limit, err := parseMediaLimit(query.Get("limit"))
    if err != nil || validateMediaCursor(query.Get("cursor")) != nil {
        http.Error(w, "invalid gallery query", http.StatusBadRequest); return
    }
    items, next, err := s.Media.ListMedia(mediaInstallationOwner, limit, query.Get("cursor"))
    if err != nil { http.Error(w, "media unavailable", http.StatusServiceUnavailable); return }
    if items == nil { items = []map[string]any{} }
    w.Header().Set("Cache-Control", "private, no-store")
    w.Header().Set("Content-Type", "application/json")
    _ = json.NewEncoder(w).Encode(map[string]any{
        "schema": "kaliv-media-gallery/v1", "items": items, "next_cursor": next,
    })
}

func (s *server) handleMediaAsset(w http.ResponseWriter, r *http.Request) {
    // Cover 404, 416 and 503 as well as successful private asset responses.
    w.Header().Set("Cache-Control", "private, no-store")
    if s.Media == nil { http.Error(w, "media unavailable", http.StatusServiceUnavailable); return }
    id := r.PathValue("id")
    if !validMediaID(id) { http.NotFound(w, r); return }
    asset, mime, size, err := s.Media.OpenMedia(mediaInstallationOwner, id)
    if err != nil {
        // A catalog may return a partially opened descriptor alongside an error.
        // Always release it before returning; never expose the failed asset.
        if asset != nil { _ = asset.Close() }
        if errors.Is(err, ErrMediaNotFound) { http.NotFound(w, r); return }
        http.Error(w, "media unavailable", http.StatusServiceUnavailable)
        return
    }
    if asset == nil { http.Error(w, "invalid verified media", http.StatusServiceUnavailable); return }
    defer asset.Close()
    if size < 0 || (mime != "video/mp4" && mime != "image/png" && mime != "image/jpeg" && mime != "image/webp") {
        http.Error(w, "invalid verified media", http.StatusServiceUnavailable); return
    }
    rangeHeader := r.Header.Get("Range")
    // No ETag or Last-Modified validator is issued by this endpoint.
    // Any If-Range therefore cannot match and requires a full response.
    if r.Header.Get("If-Range") != "" { rangeHeader = "" }
    start, end, partial, err := mediaByteRange(rangeHeader, size)
    if errors.Is(err, errRangeIgnore) {
        start, end, partial, err = mediaByteRange("", size)
    }
    if errors.Is(err, errRangeUnsatisfiable) {
        value, _ := mediaUnsatisfiedContentRange(size)
        w.Header().Set("Content-Range", value)
        w.Header().Set("Accept-Ranges", "bytes")
        w.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
        return
    }
    if err != nil { http.Error(w, "invalid verified media", http.StatusServiceUnavailable); return }
    status, contentRange, length, err := mediaRangeHeaders(start, end, size, partial)
    if err != nil { http.Error(w, "invalid verified media", http.StatusServiceUnavailable); return }
    w.Header().Set("Cache-Control", "private, no-store")
    w.Header().Set("Content-Type", mime)
    w.Header().Set("Accept-Ranges", "bytes")
    w.Header().Set("X-Content-Type-Options", "nosniff")
    // Verify seekability before committing response headers, including HEAD.
    // A broken descriptor must never be advertised as a valid downloadable asset.
    if _, err := asset.Seek(start, io.SeekStart); err != nil {
        http.Error(w, "media unavailable", http.StatusServiceUnavailable); return
    }
    w.Header().Set("Content-Length", strconv.FormatInt(length, 10))
    if partial { w.Header().Set("Content-Range", contentRange) }
    w.WriteHeader(status)
    if r.Method == http.MethodHead { return }
    _, _ = io.CopyN(w, asset, length) // response already started; never reopen by path
}

// RegisterMediaRoutes is called from routes, always behind paired-device auth.
// It is intentionally not a public, unpaired or worker-forwarded endpoint.
func (s *server) registerMediaRoutes() {
    s.mux.Handle("GET /api/v1/media", mediaPrivateNoStore(s.authMW(http.HandlerFunc(s.handleMediaList))))
    for _, method := range []string{http.MethodGet, http.MethodHead} {
        s.mux.Handle(method+" /api/v1/media/{id}", mediaPrivateNoStore(s.authMW(http.HandlerFunc(s.handleMediaAsset))))
    }
}

// mediaPrivateNoStore ensures private gallery responses, including auth failures,
// are never stored by intermediate caches or clients.
func mediaPrivateNoStore(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Cache-Control", "private, no-store")
        next.ServeHTTP(w, r)
    })
}
