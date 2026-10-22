package httpapi

import (
    "net/http"
    "os"
    "regexp"
    "strings"

    "modelrig/internal/store"
)

// Both the worker router and gateway remain disabled by default.
// The secret is configured independently on both services; it is never sent to clients.
func imageMediaPilotEnabled() bool {
    return os.Getenv("KALIV_IMAGE_MEDIA_PILOT") == "1"
}

var imageMediaID = regexp.MustCompile(`^[0-9a-f]{32}$`)

func (s *server) handleImageMedia(w http.ResponseWriter, r *http.Request) {
    secret := os.Getenv("KALIV_IMAGE_INTERNAL_SECRET")
    if len(secret) < 32 || strings.ContainsAny(secret, "\r\n") ||
        s.Worker == nil || !githubConnectorWorkerIsLoopback(s.Worker.BaseURL) {
        writeErr(w, http.StatusServiceUnavailable, "image media service unavailable")
        return
    }

    device, ok := r.Context().Value(deviceKey).(store.Device)
    if !ok || device.ID == "" || strings.ContainsAny(device.ID, "\r\n") {
        writeErr(w, http.StatusUnauthorized, "verified device required")
        return
    }

    upstream := "/internal/media/images"
    switch {
    case r.Method == http.MethodPost && r.URL.Path == "/api/v1/media/images/jobs":
        upstream += "/jobs"
    case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/api/v1/media/images/jobs/"):
        id := r.PathValue("id")
        if !imageMediaID.MatchString(id) {
            writeErr(w, http.StatusBadRequest, "invalid image job id")
            return
        }
        upstream += "/jobs/" + id
    case r.Method == http.MethodPost && strings.HasSuffix(r.URL.Path, "/cancel"):
        id := r.PathValue("id")
        if !imageMediaID.MatchString(id) {
            writeErr(w, http.StatusBadRequest, "invalid image job id")
            return
        }
        upstream += "/jobs/" + id + "/cancel"
    case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/api/v1/media/images/assets/"):
        id := r.PathValue("id")
        if !imageMediaID.MatchString(id) {
            writeErr(w, http.StatusBadRequest, "invalid image asset id")
            return
        }
        upstream += "/assets/" + id
    default:
        writeErr(w, http.StatusNotFound, "unknown image media route")
        return
    }

    // Images and job metadata belong to the paired device. The generic
    // proxy intentionally does not forward arbitrary upstream cache headers.
    w.Header().Set("Cache-Control", "private, no-store")
    w.Header().Set("X-Content-Type-Options", "nosniff")
    s.Worker.ForwardWithHeaders(w, r, upstream, map[string]string{
        "X-Verified-Owner": device.ID,
        "X-Internal-Media-Secret": secret,
    })
}
