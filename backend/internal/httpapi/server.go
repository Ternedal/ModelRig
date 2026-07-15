package httpapi

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
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
	// WorkerSlow is the same worker upstream with a long timeout, for
	// requests that legitimately take minutes: voice turns (Whisper loads
	// into VRAM first) and large document ingest (many embedding calls).
	WorkerSlow *proxy.Client
}

type server struct {
	Deps
	mux          *http.ServeMux
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
	s.mux.Handle("GET /api/v1/health/deep", s.authMW(http.HandlerFunc(s.handleHealthDeep)))
	s.mux.Handle("GET /api/v1/health/full", s.authMW(http.HandlerFunc(s.handleHealthFull)))
	s.mux.Handle("GET /api/v1/devices", s.authMW(http.HandlerFunc(s.handleDevicesList)))
	s.mux.Handle("DELETE /api/v1/devices/{id}", s.authMW(http.HandlerFunc(s.handleDeviceRevoke)))
	s.mux.Handle("POST /api/v1/token/rotate", s.authMW(http.HandlerFunc(s.handleTokenRotate)))
	s.mux.Handle("GET /api/v1/models", s.authMW(http.HandlerFunc(s.handleModels)))
	s.mux.Handle("GET /api/v1/models/running", s.authMW(http.HandlerFunc(s.handleModelsRunning)))
	s.mux.Handle("POST /api/v1/models/pull", s.authMW(http.HandlerFunc(s.handleModelsPull)))
	s.mux.Handle("DELETE /api/v1/models/delete", s.authMW(http.HandlerFunc(s.handleModelsDelete)))
	s.mux.Handle("POST /api/v1/chat", s.authMW(http.HandlerFunc(s.handleChat)))
	s.mux.Handle("POST /api/v1/rag/query", s.authMW(http.HandlerFunc(s.handleRagQuery)))
	s.mux.Handle("POST /api/v1/rag/ingest", s.authMW(http.HandlerFunc(s.handleRagIngest)))
	s.mux.Handle("POST /api/v1/rag/ingest/pdf", s.authMW(http.HandlerFunc(s.handleRagIngestPdf)))
	s.mux.Handle("POST /api/v1/rag/ingest/image", s.authMW(http.HandlerFunc(s.handleRagIngestImage)))
	s.mux.Handle("POST /api/v1/rag/ingest/docx", s.authMW(http.HandlerFunc(s.handleRagIngestDocx)))
	s.mux.Handle("GET /api/v1/tools", s.authMW(http.HandlerFunc(s.handleToolsList)))
	s.mux.Handle("POST /api/v1/tools/chat", s.authMW(http.HandlerFunc(s.handleToolsChat)))
	s.mux.Handle("POST /api/v1/tools/confirm", s.authMW(http.HandlerFunc(s.handleToolsConfirm)))
	s.mux.Handle("GET /api/v1/tools/audit", s.authMW(http.HandlerFunc(s.handleToolsAudit)))
	s.mux.Handle("POST /api/v1/tools/enabled", s.authMW(http.HandlerFunc(s.handleToolsEnabled)))
	s.mux.Handle("POST /api/v1/rag/ingest/pptx", s.authMW(http.HandlerFunc(s.handleRagIngestPptx)))
	s.mux.Handle("POST /api/v1/rag/ingest/html", s.authMW(http.HandlerFunc(s.handleRagIngestHtml)))
	s.mux.Handle("POST /api/v1/rag/chat", s.authMW(http.HandlerFunc(s.handleRagChat)))
	s.mux.Handle("GET /api/v1/rag/sources", s.authMW(http.HandlerFunc(s.handleRagSources)))
	s.mux.Handle("GET /api/v1/rag/stats", s.authMW(http.HandlerFunc(s.handleRagStats)))
	s.mux.Handle("DELETE /api/v1/rag/source", s.authMW(http.HandlerFunc(s.handleRagSourceDelete)))
	s.mux.Handle("GET /api/v1/voice/status", s.authMW(http.HandlerFunc(s.handleVoiceStatus)))
	s.mux.Handle("POST /api/v1/voice/converse", s.authMW(http.HandlerFunc(s.handleVoiceConverse)))
	s.mux.Handle("POST /api/v1/voice/converse/stream", s.authMW(http.HandlerFunc(s.handleVoiceConverseStream)))

	// Agent 3.0 is deliberately absent from the normal API surface unless the
	// operator opts into the experimental worker and backend together. Even when
	// enabled, every route remains behind the same Bearer-token middleware.
	if os.Getenv("KALIV_AGENT3_ENABLED") == "1" {
		s.mux.Handle("GET /api/v1/experimental/agent3/status", s.authMW(http.HandlerFunc(s.handleAgent3Status)))
		s.mux.Handle("POST /api/v1/experimental/agent3/plan", s.authMW(http.HandlerFunc(s.handleAgent3Plan)))
		s.mux.Handle("POST /api/v1/experimental/agent3/plans/{id}/start", s.authMW(http.HandlerFunc(s.handleAgent3PlanStart)))
		s.mux.Handle("GET /api/v1/experimental/agent3/runs", s.authMW(http.HandlerFunc(s.handleAgent3RunsList)))
		s.mux.Handle("POST /api/v1/experimental/agent3/runs", s.authMW(http.HandlerFunc(s.handleAgent3RunsStart)))
		s.mux.Handle("GET /api/v1/experimental/agent3/runs/{id}", s.authMW(http.HandlerFunc(s.handleAgent3RunGet)))
		s.mux.Handle("GET /api/v1/experimental/agent3/runs/{id}/events", s.authMW(http.HandlerFunc(s.handleAgent3RunEvents)))
		s.mux.Handle("POST /api/v1/experimental/agent3/runs/{id}/confirm", s.authMW(http.HandlerFunc(s.handleAgent3RunConfirm)))
		s.mux.Handle("POST /api/v1/experimental/agent3/runs/{id}/resume", s.authMW(http.HandlerFunc(s.handleAgent3RunResume)))
		s.mux.Handle("POST /api/v1/experimental/agent3/runs/{id}/cancel", s.authMW(http.HandlerFunc(s.handleAgent3RunCancel)))
	}
}

// ---- middleware ----

type ctxKey string

const deviceKey ctxKey = "device"
const requestIDKey ctxKey = "request_id"

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

// logging assigns (or accepts) a request ID, propagates it downstream and back to
// the client via X-Request-ID, and emits one structured key=value line per
// request. The same ID is forwarded to upstreams by the proxy, so a single
// request can be traced across backend + worker logs.
func logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		id := r.Header.Get("X-Request-ID")
		if id == "" {
			if v, err := auth.NewID(); err == nil {
				id = v
			} else {
				id = "req-" + strconv.FormatInt(time.Now().UnixNano(), 16)
			}
		}
		r.Header.Set("X-Request-ID", id) // so handlers + proxy can read/forward it
		w.Header().Set("X-Request-ID", id)
		ctx := context.WithValue(r.Context(), requestIDKey, id)
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r.WithContext(ctx))
		log.Printf("level=info req=%s ip=%s method=%s path=%s status=%d dur_ms=%d",
			id, clientIP(r), r.Method, r.URL.Path, rec.status, time.Since(start).Milliseconds())
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
