package httpapi

import (
	"bytes"
	"errors"
	"io"
	"mime"
	"net/http"
	"os"
	"strings"
)

// Media generation jobs (#2275 6764090458, backlog item 4): the device-facing half of
// worker/app/media_job_api.py. Two boundaries, as for the GitHub connector pilot:
//
//	paired device --Bearer (authMW)--> these routes --loopback + internal secret--> worker
//
// The owner is never taken from the request. The worker always files the job under
// "installation", the same owner the gallery routes list (#2365), and the device id stays an
// audit fact. The secret is configured on both sides and never sent to a device.
//
// Default off: without KALIV_MEDIA_JOBS_API=1 the routes are not registered (404).

const (
	mediaJobsSecretHeader = "X-Internal-Media-Secret"
	mediaJobsMinSecret    = 32
	mediaJobsMaxBody      = 16 << 10 // the worker caps a prompt at 4000 characters
)

func mediaJobsAPIEnabled() bool {
	// The literal comparison keeps the switch visible to scripts/activation_readiness.py.
	return os.Getenv("KALIV_MEDIA_JOBS_API") == "1"
}

func mediaJobsSecret() (string, bool) {
	secret := os.Getenv("KALIV_MEDIA_INTERNAL_SECRET")
	if len(secret) < mediaJobsMinSecret || strings.ContainsAny(secret, "\r\n") {
		return "", false
	}
	return secret, true
}

func validMediaJobID(id string) bool {
	if len(id) != 32 {
		return false
	}
	for _, c := range id {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			return false
		}
	}
	return true
}

// mediaJobsNoStore marks every answer private before anything else runs, including authMW's 401:
// job states and ids are the device owner's data.
func mediaJobsNoStore(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "private, no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		next.ServeHTTP(w, r)
	})
}

func (s *server) forwardMediaJobs(w http.ResponseWriter, r *http.Request, upstream string) {
	secret, ok := mediaJobsSecret()
	if !ok || s.Worker == nil || !githubConnectorWorkerIsLoopback(s.Worker.BaseURL) {
		writeErr(w, http.StatusServiceUnavailable, "media jobs unavailable")
		return
	}
	r.URL.RawQuery = "" // these routes take no query; nothing extra reaches the worker
	s.Worker.ForwardWithHeaders(&mediaJobsResponseWriter{ResponseWriter: w}, r, upstream, map[string]string{mediaJobsSecretHeader: secret})
}

// mediaJobsResponseWriter keeps worker-internal authentication failures on the
// internal trust boundary. A paired device's Bearer token was already checked
// by authMW; an upstream 401/403 must not masquerade as a device pairing error.
// Do not expose the upstream error body (which may contain internal details).
type mediaJobsResponseWriter struct {
	http.ResponseWriter
	blocked bool
}

func (w *mediaJobsResponseWriter) WriteHeader(status int) {
	if status == http.StatusUnauthorized || status == http.StatusForbidden {
		w.blocked = true
		w.Header().Del("X-Bodyrig-Implementation")
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.ResponseWriter.WriteHeader(http.StatusServiceUnavailable)
		_, _ = io.WriteString(w.ResponseWriter, "media jobs unavailable\\n")
		return
	}
	w.ResponseWriter.WriteHeader(status)
}

func (w *mediaJobsResponseWriter) Write(body []byte) (int, error) {
	if w.blocked {
		return len(body), nil
	}
	return w.ResponseWriter.Write(body)
}

// mediaJobsJSON accepts exactly application/json, with an optional utf-8 charset (ChatGPT
// 6764300677: a prefix check let "application/jsonp" through).
func mediaJobsJSON(contentType string) bool {
	mediaType, params, err := mime.ParseMediaType(contentType)
	if err != nil || mediaType != "application/json" {
		return false
	}
	for name, value := range params {
		if name != "charset" || !strings.EqualFold(value, "utf-8") {
			return false
		}
	}
	return true
}

func (s *server) handleMediaJobSubmit(w http.ResponseWriter, r *http.Request) {
	if !mediaJobsJSON(r.Header.Get("Content-Type")) {
		writeErr(w, http.StatusUnsupportedMediaType, "media job request must be JSON")
		return
	}
	// The whole body is read here, bounded, before anything is forwarded: a chunked or
	// unknown-length body over the cap is a 413 and never reaches the worker in part.
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, mediaJobsMaxBody))
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			writeErr(w, http.StatusRequestEntityTooLarge, "media job request too large")
		} else {
			writeErr(w, http.StatusBadRequest, "media job request could not be read")
		}
		return
	}
	r.Body = io.NopCloser(bytes.NewReader(body))
	r.ContentLength = int64(len(body))
	s.forwardMediaJobs(w, r, "/internal/media/jobs")
}

func (s *server) handleMediaJobProfiles(w http.ResponseWriter, r *http.Request) {
	s.forwardMediaJobs(w, r, "/internal/media/jobs/profiles")
}

func (s *server) handleMediaJobStatus(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if !validMediaJobID(id) {
		writeErr(w, http.StatusNotFound, "media job not found")
		return
	}
	s.forwardMediaJobs(w, r, "/internal/media/jobs/"+id)
}

func (s *server) handleMediaJobCancel(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if !validMediaJobID(id) {
		writeErr(w, http.StatusNotFound, "media job not found")
		return
	}
	s.forwardMediaJobs(w, r, "/internal/media/jobs/"+id+"/cancel")
}

func (s *server) registerMediaJobRoutes() {
	if !mediaJobsAPIEnabled() {
		return
	}
	s.mux.Handle("POST /api/v1/media/jobs", mediaJobsNoStore(s.authMW(http.HandlerFunc(s.handleMediaJobSubmit))))
	s.mux.Handle("GET /api/v1/media/jobs/profiles", mediaJobsNoStore(s.authMW(http.HandlerFunc(s.handleMediaJobProfiles))))
	s.mux.Handle("GET /api/v1/media/jobs/{id}", mediaJobsNoStore(s.authMW(http.HandlerFunc(s.handleMediaJobStatus))))
	s.mux.Handle("POST /api/v1/media/jobs/{id}/cancel", mediaJobsNoStore(s.authMW(http.HandlerFunc(s.handleMediaJobCancel))))
}
