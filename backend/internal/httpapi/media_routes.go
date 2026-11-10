package httpapi

import (
    "errors"
    "encoding/json"
    "fmt"
    "io"
    "net/http"
    "strconv"
    "strings"
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
    w.Header().Set("Content-Type", "application/json")
    _ = json.NewEncoder(w).Encode(map[string]any{
        "schema": "kaliv-media-gallery/v1", "items": items, "next_cursor": next,
    })
}

func (s *server) handleMediaAsset(w http.ResponseWriter, r *http.Request) {
    if s.Media == nil { http.Error(w, "media unavailable", http.StatusServiceUnavailable); return }
    id := r.PathValue("id")
    if !validMediaID(id) { http.NotFound(w, r); return }
    asset, mime, size, err := s.Media.OpenMedia(mediaInstallationOwner, id)
    if errors.Is(err, ErrMediaNotFound) { http.NotFound(w, r); return }
    if err != nil { http.Error(w, "media unavailable", http.StatusServiceUnavailable); return }
    defer asset.Close()
    if size < 0 || (mime != "video/mp4" && mime != "image/png" && mime != "image/jpeg" && mime != "image/webp") {
        http.Error(w, "invalid verified media", http.StatusServiceUnavailable); return
    }
    start, end, partial, err := mediaByteRange(r.Header.Get("Range"), size)
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
    w.Header().Set("Content-Type", mime)
    w.Header().Set("Accept-Ranges", "bytes")
    w.Header().Set("Content-Length", strconv.FormatInt(length, 10))
    w.Header().Set("X-Content-Type-Options", "nosniff")
    if partial { w.Header().Set("Content-Range", contentRange) }
    if r.Method == http.MethodHead { w.WriteHeader(status); return }
    if _, err := asset.Seek(start, io.SeekStart); err != nil {
        http.Error(w, "media unavailable", http.StatusServiceUnavailable); return
    }
    w.WriteHeader(status)
    if _, err := io.CopyN(w, asset, length); err != nil {
        // Response already started. Do not reopen by path or append an error body.
        _ = fmt.Sprintf("%v", err)
    }
}

// RegisterMediaRoutes is called from routes, always behind paired-device auth.
// It is intentionally not a public, unpaired or worker-forwarded endpoint.
func (s *server) registerMediaRoutes() {
    s.mux.Handle("GET /api/v1/media", s.authMW(http.HandlerFunc(s.handleMediaList)))
    for _, method := range []string{http.MethodGet, http.MethodHead} {
        s.mux.Handle(method+" /api/v1/media/{id}", s.authMW(http.HandlerFunc(s.handleMediaAsset)))
    }
}

var _ = strings.TrimSpace
