package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
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
	controlCenterVisionControlSchema   = "kaliv-control-center-vision-control/v1"
	visionRigControlAPIFlag            = "KALIV_VISIONRIG_CONTROL_API"
	maxControlCenterStatusBytes        = 1 << 20
	maxControlCenterControlBytes       = 4 << 10
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
	if vision, ok := payload["vision"].(map[string]any); ok {
		vision["operator_control_available"] = visionRigControlAPIEnabled()
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


type controlCenterVisionEnabledRequest struct {
	Enabled               *bool  `json:"enabled"`
	ExpectedStateRevision *int64 `json:"expected_state_revision"`
}

func visionRigControlAPIEnabled() bool {
	return os.Getenv(visionRigControlAPIFlag) == "1"
}

func decodeControlCenterVisionEnabled(body io.Reader) (bool, int64, error) {
	raw, err := io.ReadAll(io.LimitReader(body, maxControlCenterControlBytes+1))
	if err != nil || len(raw) > maxControlCenterControlBytes {
		return false, 0, io.ErrUnexpectedEOF
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var request controlCenterVisionEnabledRequest
	if err := decoder.Decode(&request); err != nil {
		return false, 0, err
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return false, 0, io.ErrUnexpectedEOF
	}
	if request.Enabled == nil || request.ExpectedStateRevision == nil {
		return false, 0, io.ErrUnexpectedEOF
	}
	if *request.ExpectedStateRevision < 0 {
		return false, 0, io.ErrUnexpectedEOF
	}
	return *request.Enabled, *request.ExpectedStateRevision, nil
}

func (s *server) handleControlCenterVisionEnabled(w http.ResponseWriter, r *http.Request) {
	if s.Worker == nil || strings.TrimSpace(s.Worker.BaseURL) == "" {
		writeErr(w, http.StatusBadGateway, "VisionRig sensor control unavailable")
		return
	}
	sourceID := strings.TrimSpace(r.PathValue("source_id"))
	if sourceID == "" || len(sourceID) > 128 {
		writeErr(w, http.StatusUnprocessableEntity, "invalid VisionRig source id")
		return
	}
	enabled, expectedRevision, err := decodeControlCenterVisionEnabled(r.Body)
	if err != nil {
		writeErr(w, http.StatusBadRequest, "invalid VisionRig sensor control request")
		return
	}
	upstreamBody, _ := json.Marshal(map[string]any{
		"enabled":                 enabled,
		"expected_state_revision": expectedRevision,
	})
	target := strings.TrimRight(s.Worker.BaseURL, "/") +
		"/control-center/vision/" + url.PathEscape(sourceID) + "/enabled"
	req, err := http.NewRequestWithContext(
		r.Context(),
		http.MethodPost,
		target,
		bytes.NewReader(upstreamBody),
	)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "VisionRig sensor control unavailable")
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if requestID := r.Header.Get("X-Request-ID"); requestID != "" {
		req.Header.Set("X-Request-ID", requestID)
	}

	client := &http.Client{Timeout: controlCenterStatusTimeout}
	resp, err := client.Do(req)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "VisionRig sensor control unavailable")
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		switch resp.StatusCode {
		case http.StatusNotFound, http.StatusConflict, http.StatusUnprocessableEntity:
			writeErr(w, resp.StatusCode, "VisionRig sensor control rejected")
		default:
			writeErr(w, http.StatusBadGateway, "VisionRig sensor control unavailable")
		}
		return
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, maxControlCenterControlBytes+1))
	if err != nil || len(body) > maxControlCenterControlBytes {
		writeErr(w, http.StatusBadGateway, "VisionRig sensor control unavailable")
		return
	}
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		writeErr(w, http.StatusBadGateway, "VisionRig sensor control unavailable")
		return
	}
	if payload["schema"] != controlCenterVisionControlSchema ||
		payload["source_id"] != sourceID ||
		payload["enabled"] != enabled ||
		payload["production_activation"] != false {
		writeErr(w, http.StatusBadGateway, "VisionRig sensor control unavailable")
		return
	}

	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, payload)
}
