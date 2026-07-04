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

// handleModelsRunning proxies Ollama's list of currently loaded models
// (GET /api/ps) -- shows VRAM usage and expiry, for a "what's actually
// running right now" view distinct from "what's installed" (handleModels).
func (s *server) handleModelsRunning(w http.ResponseWriter, r *http.Request) {
	s.Ollama.Forward(w, r, "/api/ps")
}

// handleModelsPull proxies a model download (POST /api/pull, body
// {"model":"<name>"}). Ollama streams NDJSON download progress
// ({"status","digest","total","completed"} lines); Forward() already
// flushes as bytes arrive, so progress reaches the client live, same as
// streaming chat.
func (s *server) handleModelsPull(w http.ResponseWriter, r *http.Request) {
	s.Ollama.Forward(w, r, "/api/pull")
}

// handleModelsDelete proxies model removal (DELETE /api/delete, body
// {"model":"<name>"}). Irreversible on the Ollama side -- the client is
// expected to confirm with the user before calling this.
func (s *server) handleModelsDelete(w http.ResponseWriter, r *http.Request) {
	s.Ollama.Forward(w, r, "/api/delete")
}

// handleHealthDeep actively round-trips both upstreams: it lists Ollama models
// and asks the worker to embed a token (which itself calls Ollama). This proves
// the models actually respond, not just that the ports are open. Always HTTP 200;
// the `ok` field carries the verdict so scripts can branch on the body.
func (s *server) handleHealthDeep(w http.ResponseWriter, r *http.Request) {
	client := &http.Client{Timeout: 10 * time.Second}
	overall := true

	ollama := map[string]any{}
	{
		start := time.Now()
		ok := false
		req, _ := http.NewRequest(http.MethodGet, s.Ollama.BaseURL+"/api/tags", nil)
		if s.Ollama.AuthToken != "" {
			req.Header.Set("Authorization", "Bearer "+s.Ollama.AuthToken)
		}
		if resp, err := client.Do(req); err == nil {
			defer resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				var body struct {
					Models []struct {
						Name string `json:"name"`
					} `json:"models"`
				}
				if json.NewDecoder(resp.Body).Decode(&body) == nil {
					ok = true
					ollama["models"] = len(body.Models)
				}
			} else {
				ollama["status"] = resp.StatusCode
			}
		} else {
			ollama["error"] = err.Error()
		}
		ollama["ok"] = ok
		ollama["latency_ms"] = time.Since(start).Milliseconds()
		overall = overall && ok
	}

	worker := map[string]any{}
	{
		start := time.Now()
		ok := false
		if resp, err := client.Get(s.Worker.BaseURL + "/health/deep"); err == nil {
			defer resp.Body.Close()
			var body map[string]any
			if json.NewDecoder(resp.Body).Decode(&body) == nil {
				if b, _ := body["ok"].(bool); b {
					ok = true
					if d, has := body["embed_dims"]; has {
						worker["embed_dims"] = d
					}
				} else if e, has := body["error"]; has {
					worker["error"] = e
				}
			}
		} else {
			worker["error"] = err.Error()
		}
		worker["ok"] = ok
		worker["latency_ms"] = time.Since(start).Milliseconds()
		overall = overall && ok
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"ok":     overall,
		"checks": map[string]any{"ollama": ollama, "worker": worker},
	})
}

// handleTokenRotate re-issues the calling device's own token without re-pairing.
// The old token stops validating immediately (its hash is overwritten).
func (s *server) handleTokenRotate(w http.ResponseWriter, r *http.Request) {
	dv, _ := r.Context().Value(deviceKey).(store.Device)
	token, hash, err := auth.NewToken()
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "token generation failed")
		return
	}
	updated, ok := s.Store.RotateToken(dv.ID, hash)
	if !ok {
		writeErr(w, http.StatusNotFound, "device not found")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"device_id":   updated.ID,
		"device_name": updated.Name,
		"token":       token,
	})
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

// handleRagChat proxies the worker's streaming RAG answer (retrieve + stream).
func (s *server) handleRagChat(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, "/rag/chat")
}

func (s *server) handleRagSources(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, "/rag/sources")
}

func (s *server) handleRagStats(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, "/rag/stats")
}

func (s *server) handleRagSourceDelete(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, "/rag/source")
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
