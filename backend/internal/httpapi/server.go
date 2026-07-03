package httpapi

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"strings"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

// Deps are the collaborators the HTTP layer needs.
type Deps struct {
	Cfg    config.Config
	Store  *store.Store
	Ollama *proxy.Client
	Worker *proxy.Client
}

type server struct {
	Deps
	mux         *http.ServeMux
	claimLimiter *rateLimiter
}

// New wires routes and returns the top-level handler (logging wraps everything).
func New(d Deps) http.Handler {
	s := &server{
		Deps:         d,
		mux:          http.NewServeMux(),
		claimLimiter: newRateLimiter(d.Cfg.ClaimMax, 5*time.Minute), // per-IP claim throttle
	}
	s.routes()
	go func() {
		t := time.NewTicker(5 * time.Minute)
		defer t.Stop()
		for range t.C {
			s.claimLimiter.sweep()
		}
	}()
	return logging(s.mux)
}

func (s *server) routes() {
	// Public
	s.mux.HandleFunc("GET /healthz", s.handleHealth)
	s.mux.HandleFunc("POST /api/v1/pair/start", s.handlePairStart)
	s.mux.HandleFunc("POST /api/v1/pair/claim", s.handlePairClaim)

	// Protected (Bearer token required)
	s.mux.Handle("GET /api/v1/status", s.authMW(http.HandlerFunc(s.handleStatus)))
	s.mux.Handle("GET /api/v1/devices", s.authMW(http.HandlerFunc(s.handleDevicesList)))
	s.mux.Handle("DELETE /api/v1/devices/{id}", s.authMW(http.HandlerFunc(s.handleDeviceRevoke)))
	s.mux.Handle("GET /api/v1/models", s.authMW(http.HandlerFunc(s.handleModels)))
	s.mux.Handle("POST /api/v1/chat", s.authMW(http.HandlerFunc(s.handleChat)))
	s.mux.Handle("POST /api/v1/rag/query", s.authMW(http.HandlerFunc(s.handleRagQuery)))
	s.mux.Handle("POST /api/v1/rag/ingest", s.authMW(http.HandlerFunc(s.handleRagIngest)))
	s.mux.Handle("GET /api/v1/rag/sources", s.authMW(http.HandlerFunc(s.handleRagSources)))
	s.mux.Handle("GET /api/v1/rag/stats", s.authMW(http.HandlerFunc(s.handleRagStats)))
	s.mux.Handle("DELETE /api/v1/rag/source", s.authMW(http.HandlerFunc(s.handleRagSourceDelete)))
}

// ---- middleware ----

type ctxKey string

const deviceKey ctxKey = "device"

// statusRecorder captures the status code and forwards Flush for streaming.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(c int) {
	r.status = c
	r.ResponseWriter.WriteHeader(c)
}

func (r *statusRecorder) Flush() {
	if f, ok := r.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		log.Printf("%s %s -> %d (%s)", r.Method, r.URL.Path, rec.status, time.Since(start).Round(time.Millisecond))
	})
}

// authMW enforces a valid Bearer token on every request.
//
// Loopback-free by design: there is NO localhost/loopback bypass. A request
// from 127.0.0.1 must present a valid token exactly like a LAN client. This
// prevents other local processes (or a mis-scoped reverse proxy) from calling
// protected endpoints unauthenticated.
func (s *server) authMW(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		const prefix = "Bearer "
		h := r.Header.Get("Authorization")
		if len(h) <= len(prefix) || !strings.EqualFold(h[:len(prefix)], prefix) {
			writeErr(w, http.StatusUnauthorized, "missing bearer token")
			return
		}
		token := strings.TrimSpace(h[len(prefix):])
		dv, ok := s.Store.TouchByTokenHash(auth.Hash(token), time.Now())
		if !ok {
			writeErr(w, http.StatusUnauthorized, "invalid token")
			return
		}
		ctx := context.WithValue(r.Context(), deviceKey, dv)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// ---- helpers ----

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}
