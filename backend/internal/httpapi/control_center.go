package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"modelrig/internal/config"
)

const (
	controlCenterStatusSchema          = "kaliv-control-center-status/v1"
	controlCenterScheduleHistorySchema = "kaliv-control-center-schedule-history/v1"
	controlCenterVisionSchema          = "kaliv-control-center-vision/v1"
	visionRigSensorMetadataSchema      = "visionrig/sensor-metadata/v1"
	maxControlCenterStatusBytes        = 1 << 20
	controlCenterStatusTimeout         = 5 * time.Second
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

// handleControlCenterScheduleHistory is the remote read-only boundary for the
// worker's side-effect-free occurrence/job projection. It intentionally does
// not depend on KALIV_SCHEDULER_API: that flag controls the stronger schedule
// administration surface, while this route only observes existing durable facts.
// Client query parameters and backend-status stamps are never forwarded.
func (s *server) handleControlCenterScheduleHistory(w http.ResponseWriter, r *http.Request) {
	if s.Worker == nil || strings.TrimSpace(s.Worker.BaseURL) == "" {
		writeErr(w, http.StatusBadGateway, "control center schedule history unavailable")
		return
	}

	target := strings.TrimRight(s.Worker.BaseURL, "/") + "/control-center/schedules"
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, target, nil)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "control center schedule history unavailable")
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
		writeErr(w, http.StatusBadGateway, "control center schedule history unavailable")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		writeErr(w, http.StatusBadGateway, "control center schedule history unavailable")
		return
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, maxControlCenterStatusBytes+1))
	if err != nil || len(body) > maxControlCenterStatusBytes {
		writeErr(w, http.StatusBadGateway, "control center schedule history unavailable")
		return
	}
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		writeErr(w, http.StatusBadGateway, "control center schedule history unavailable")
		return
	}
	if payload["schema"] != controlCenterScheduleHistorySchema {
		writeErr(w, http.StatusBadGateway, "control center schedule history unavailable")
		return
	}

	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, payload)
}


func (s *server) handleControlCenterVision(w http.ResponseWriter, r *http.Request) {
	if s.Worker == nil || strings.TrimSpace(s.Worker.BaseURL) == "" {
		writeErr(w, http.StatusBadGateway, "control center vision unavailable")
		return
	}

	target := strings.TrimRight(s.Worker.BaseURL, "/") + "/control-center/vision"
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, target, nil)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "control center vision unavailable")
		return
	}
	if requestID := r.Header.Get("X-Request-ID"); requestID != "" {
		req.Header.Set("X-Request-ID", requestID)
	}

	client := &http.Client{Timeout: controlCenterStatusTimeout}
	resp, err := client.Do(req)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "control center vision unavailable")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		writeErr(w, http.StatusBadGateway, "control center vision unavailable")
		return
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, maxControlCenterStatusBytes+1))
	if err != nil || len(body) > maxControlCenterStatusBytes {
		writeErr(w, http.StatusBadGateway, "control center vision unavailable")
		return
	}
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil || payload["schema"] != controlCenterVisionSchema {
		writeErr(w, http.StatusBadGateway, "control center vision unavailable")
		return
	}

	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, payload)
}

type visionRigEnabledRequest struct {
	Enabled *bool `json:"enabled"`
}

func visionRigLoopbackBaseURL() (string, bool) {
	raw := strings.TrimSpace(os.Getenv("KALIV_VISIONRIG_URL"))
	if raw == "" {
		raw = "http://127.0.0.1:8110"
	}
	parsed, err := url.Parse(raw)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") ||
		parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" ||
		parsed.Hostname() == "" {
		return "", false
	}
	host := parsed.Hostname()
	if !strings.EqualFold(host, "localhost") {
		ip := net.ParseIP(host)
		if ip == nil || !ip.IsLoopback() {
			return "", false
		}
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/")
	return strings.TrimRight(parsed.String(), "/"), true
}

func (s *server) handleControlCenterVisionSensorEnabled(w http.ResponseWriter, r *http.Request) {
	sourceID := strings.TrimSpace(r.PathValue("sourceID"))
	if sourceID == "" || len(sourceID) > 128 {
		writeErr(w, http.StatusBadRequest, "invalid VisionRig source id")
		return
	}
	base, ok := visionRigLoopbackBaseURL()
	if !ok {
		writeErr(w, http.StatusBadGateway, "VisionRig control unavailable")
		return
	}

	body, err := io.ReadAll(io.LimitReader(r.Body, 1025))
	if err != nil || len(body) > 1024 {
		writeErr(w, http.StatusBadRequest, "invalid VisionRig control request")
		return
	}
	var input visionRigEnabledRequest
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&input); err != nil || input.Enabled == nil {
		writeErr(w, http.StatusBadRequest, "invalid VisionRig control request")
		return
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		writeErr(w, http.StatusBadRequest, "invalid VisionRig control request")
		return
	}

	payload, _ := json.Marshal(map[string]bool{"enabled": *input.Enabled})
	target := base + "/api/v1/sensors/" + url.PathEscape(sourceID) + "/metadata"
	req, err := http.NewRequestWithContext(
		r.Context(),
		http.MethodPatch,
		target,
		bytes.NewReader(payload),
	)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "VisionRig control unavailable")
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	if requestID := r.Header.Get("X-Request-ID"); requestID != "" {
		req.Header.Set("X-Request-ID", requestID)
	}

	client := &http.Client{Timeout: controlCenterStatusTimeout}
	resp, err := client.Do(req)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "VisionRig control unavailable")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		writeErr(w, http.StatusBadGateway, "VisionRig control unavailable")
		return
	}
	responseBody, err := io.ReadAll(io.LimitReader(resp.Body, maxControlCenterStatusBytes+1))
	if err != nil || len(responseBody) > maxControlCenterStatusBytes {
		writeErr(w, http.StatusBadGateway, "VisionRig control unavailable")
		return
	}
	var result map[string]any
	if err := json.Unmarshal(responseBody, &result); err != nil ||
		result["schema"] != visionRigSensorMetadataSchema {
		writeErr(w, http.StatusBadGateway, "VisionRig control unavailable")
		return
	}
	metadata, ok := result["metadata"].(map[string]any)
	if !ok || metadata["source_id"] != sourceID || metadata["enabled"] != *input.Enabled {
		writeErr(w, http.StatusBadGateway, "VisionRig control unavailable")
		return
	}

	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]any{
		"schema": "kaliv-control-center-vision-enabled/v1",
		"source_id": sourceID,
		"enabled": *input.Enabled,
	})
}
