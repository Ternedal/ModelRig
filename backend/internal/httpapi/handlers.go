package httpapi

import (
	"encoding/json"
	"net"
	"net/http"
	"os"
	"strings"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/pairing"
	"modelrig/internal/store"
)

func (s *server) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"service": "modelrig-server",
		"version": config.Version,
	})
}

// handlePairStart creates a single-use pairing code.
//
// Operator-side endpoint. If MODELRIG_ADMIN_KEY is set it must be supplied via
// the X-Admin-Key header. If unset, the endpoint is open (dev mode) and the
// server logs a warning at startup. The `modelrig-server -pair` CLI flag is the
// recommended way to mint a code without exposing this endpoint at all.
func (s *server) handlePairStart(w http.ResponseWriter, r *http.Request) {
	if key := os.Getenv("MODELRIG_ADMIN_KEY"); key != "" {
		if r.Header.Get("X-Admin-Key") != key {
			writeErr(w, http.StatusUnauthorized, "admin key required")
			return
		}
	}
	code, err := pairing.Code()
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "code generation failed")
		return
	}
	exp := time.Now().Add(s.Cfg.PairingTTL)
	if err := s.Store.PutPairing(store.Pairing{Code: code, ExpiresAt: exp}); err != nil {
		writeErr(w, http.StatusInternalServerError, "persist failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"code":               code,
		"expires_at":         exp.Format(time.RFC3339),
		"expires_in_seconds": int(s.Cfg.PairingTTL.Seconds()),
	})
}

type claimReq struct {
	DeviceName string `json:"device_name"`
	Code       string `json:"code"`
}

// handlePairClaim exchanges a valid pairing code for a device token.
// The token is returned exactly once; the client is responsible for storing it.
func (s *server) handlePairClaim(w http.ResponseWriter, r *http.Request) {
	if !s.claimLimiter.allow(clientIP(r)) {
		writeErr(w, http.StatusTooManyRequests, "too many pairing attempts, slow down")
		return
	}
	var req claimReq
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid json body")
		return
	}
	code := pairing.Normalize(req.Code)
	if len(code) != 9 { // XXXX-XXXX
		writeErr(w, http.StatusBadRequest, "invalid code format")
		return
	}
	p, ok := s.Store.TakePairing(code)
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unknown or already-used code")
		return
	}
	if time.Now().After(p.ExpiresAt) {
		writeErr(w, http.StatusUnauthorized, "code expired")
		return
	}

	name := strings.TrimSpace(req.DeviceName)
	if name == "" {
		name = "unnamed-device"
	}
	token, hash, err := auth.NewToken()
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "token generation failed")
		return
	}
	id, err := auth.NewID()
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "id generation failed")
		return
	}
	dv := store.Device{
		ID:        id,
		Name:      name,
		TokenHash: hash,
		CreatedAt: time.Now(),
		LastSeen:  time.Now(),
	}
	if err := s.Store.AddDevice(dv); err != nil {
		writeErr(w, http.StatusInternalServerError, "persist failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"device_id":   id,
		"device_name": name,
		"token":       token,
	})
}

// handleDevicesList returns paired devices without exposing token hashes.
func (s *server) handleDevicesList(w http.ResponseWriter, r *http.Request) {
	devs := s.Store.Devices()
	out := make([]map[string]any, 0, len(devs))
	for _, d := range devs {
		out = append(out, map[string]any{
			"id":         d.ID,
			"name":       d.Name,
			"created_at": d.CreatedAt,
			"last_seen":  d.LastSeen,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"devices": out})
}

// handleDeviceRevoke removes a device by ID. A revoked device's token stops
// working immediately (auth looks up live store on every request).
func (s *server) handleDeviceRevoke(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeErr(w, http.StatusBadRequest, "missing device id")
		return
	}
	if !s.Store.DeleteDevice(id) {
		writeErr(w, http.StatusNotFound, "device not found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"revoked": id})
}

func (s *server) handleStatus(w http.ResponseWriter, r *http.Request) {
	dv, _ := r.Context().Value(deviceKey).(store.Device)
	writeJSON(w, http.StatusOK, map[string]any{
		"version": config.Version,
		"device": map[string]any{
			"id":        dv.ID,
			"name":      dv.Name,
			"last_seen": dv.LastSeen,
		},
		"upstream": map[string]any{
			"ollama": s.Ollama.Reachable(),
			"worker": s.Worker.Reachable(),
		},
	})
}

// handleModels proxies Ollama's model list (GET /api/tags).
func (s *server) handleModels(w http.ResponseWriter, r *http.Request) {
	s.Ollama.Forward(w, r, "/api/tags")
}

// handleChat proxies Ollama chat (POST /api/chat), streaming NDJSON through.
func (s *server) handleChat(w http.ResponseWriter, r *http.Request) {
	s.Ollama.Forward(w, r, "/api/chat")
}

func (s *server) handleRagQuery(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, "/rag/query")
}

func (s *server) handleRagIngest(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, "/rag/ingest")
}

// clientIP extracts the remote host for rate-limiting. Behind a trusted reverse
// proxy you'd honor X-Forwarded-For; for a direct LAN server RemoteAddr is right.
func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
