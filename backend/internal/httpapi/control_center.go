package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"modelrig/internal/config"
)

const (
	controlCenterStatusSchema   = "kaliv-control-center-status/v1"
	maxControlCenterStatusBytes = 1 << 20
	controlCenterStatusTimeout  = 5 * time.Second
)

// handleControlCenterStatus is the only remote boundary for the worker's
// loopback-only Control Center status. The backend supplies its own observation
// stamp; client-authored status headers and query parameters are never forwarded.
func (s *server) handleControlCenterStatus(w http.ResponseWriter, r *http.Request) {
	if s.Worker == nil || strings.TrimSpace(s.Worker.BaseURL) == "" {
		writeErr(w, http.StatusBadGateway, "control center status unavailable")
		return
	}

	target := strings.TrimRight(s.Worker.BaseURL, "/") + "/control-center/status"
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, target, nil)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "control center status unavailable")
		return
	}
	now := time.Now()
	req.Header.Set(
		"X-Kaliv-Backend-Observed-At",
		strconv.FormatFloat(float64(now.UnixNano())/1e9, 'f', 6, 64),
	)
	req.Header.Set("X-Kaliv-Backend-Version", config.Version)
	req.Header.Set("X-Kaliv-Backend-Status", "ok")
	if requestID := r.Header.Get("X-Request-ID"); requestID != "" {
		req.Header.Set("X-Request-ID", requestID)
	}

	client := &http.Client{Timeout: controlCenterStatusTimeout}
	resp, err := client.Do(req)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "control center status unavailable")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		writeErr(w, http.StatusBadGateway, "control center status unavailable")
		return
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, maxControlCenterStatusBytes+1))
	if err != nil || len(body) > maxControlCenterStatusBytes {
		writeErr(w, http.StatusBadGateway, "control center status unavailable")
		return
	}
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		writeErr(w, http.StatusBadGateway, "control center status unavailable")
		return
	}
	if payload["schema"] != controlCenterStatusSchema {
		writeErr(w, http.StatusBadGateway, "control center status unavailable")
		return
	}

	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, payload)
}
