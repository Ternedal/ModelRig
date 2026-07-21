package httpapi

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"reflect"
	"strings"
	"time"

	"modelrig/internal/store"
)

const (
	scheduleApprovalSecretEnv = "KALIV_SCHEDULER_APPROVAL_SECRET"
	scheduleApprovalTTL       = 2 * time.Minute
	maxScheduleBodyBytes      = 64 << 10
)

var errScheduleApprovalUnavailable = errors.New("schedule approval secret is unavailable")

type scheduleCreateTerms struct {
	Tool    string         `json:"tool"`
	Args    map[string]any `json:"args"`
	Cadence string         `json:"cadence"`
	TTLDays int            `json:"ttl_days"`
	MaxRuns int            `json:"max_runs"`
}

type scheduleCreateApprovalRequest struct {
	Tool               string         `json:"tool"`
	Args               map[string]any `json:"args"`
	Cadence            string         `json:"cadence"`
	TTLDays            int            `json:"ttl_days"`
	MaxRuns            int            `json:"max_runs"`
	PreviewFingerprint string         `json:"preview_fingerprint"`
}

type scheduleCreateCommitRequest struct {
	Tool          string         `json:"tool"`
	Args          map[string]any `json:"args"`
	Cadence       string         `json:"cadence"`
	TTLDays       int            `json:"ttl_days"`
	MaxRuns       int            `json:"max_runs"`
	ApprovalToken string         `json:"approval_token,omitempty"`
}

type scheduleRenewTerms struct {
	TTLDays int   `json:"ttl_days"`
	MaxRuns int   `json:"max_runs"`
	Enable  *bool `json:"enable,omitempty"`
}

type scheduleRenewApprovalRequest struct {
	TTLDays            int    `json:"ttl_days"`
	MaxRuns            int    `json:"max_runs"`
	Enable             *bool  `json:"enable,omitempty"`
	PreviewFingerprint string `json:"preview_fingerprint"`
}

type scheduleRenewCommitRequest struct {
	TTLDays       int    `json:"ttl_days"`
	MaxRuns       int    `json:"max_runs"`
	Enable        *bool  `json:"enable,omitempty"`
	ApprovalToken string `json:"approval_token,omitempty"`
}

type schedulePreviewEnvelope struct {
	Preview scheduleApprovalPreview `json:"preview"`
}

type scheduleApprovalPreview struct {
	Operation           string         `json:"operation"`
	ScheduleID          *string        `json:"schedule_id"`
	Tool                string         `json:"tool"`
	Args                map[string]any `json:"args"`
	Cadence             string         `json:"cadence"`
	Timezone            string         `json:"timezone"`
	MisfirePolicy       string         `json:"misfire_policy"`
	RequiresApproval    bool           `json:"requires_approval"`
	ActionFingerprint   string         `json:"action_fingerprint"`
	ApprovalFingerprint *string        `json:"approval_fingerprint"`
	TTLDays             int            `json:"ttl_days"`
	MaxRuns             int            `json:"max_runs"`
	Enable              *bool          `json:"enable"`
}

type scheduleApprovalClaims struct {
	Version             int            `json:"v"`
	Nonce               string         `json:"nonce"`
	DeviceID            string         `json:"device_id"`
	Operation           string         `json:"operation"`
	ScheduleID          *string        `json:"schedule_id"`
	Tool                string         `json:"tool"`
	Args                map[string]any `json:"args"`
	Cadence             string         `json:"cadence"`
	Timezone            string         `json:"timezone"`
	MisfirePolicy       string         `json:"misfire_policy"`
	TTLDays             int            `json:"ttl_days"`
	MaxRuns             int            `json:"max_runs"`
	Enable              *bool          `json:"enable"`
	ActionFingerprint   string         `json:"action_fingerprint"`
	ApprovalFingerprint string         `json:"approval_fingerprint"`
	IssuedAt            int64          `json:"issued_at"`
	ExpiresAt           int64          `json:"expires_at"`
}

func scheduleApprovalSecret() ([]byte, error) {
	secret := []byte(os.Getenv(scheduleApprovalSecretEnv))
	if len(secret) < 32 {
		return nil, errScheduleApprovalUnavailable
	}
	return secret, nil
}

func scheduleDeviceID(r *http.Request) (string, bool) {
	dv, ok := r.Context().Value(deviceKey).(store.Device)
	return dv.ID, ok && strings.TrimSpace(dv.ID) != ""
}

func issueScheduleApprovalToken(
	preview scheduleApprovalPreview,
	deviceID string,
	now time.Time,
) (string, scheduleApprovalClaims, error) {
	secret, err := scheduleApprovalSecret()
	if err != nil {
		return "", scheduleApprovalClaims{}, err
	}
	if !preview.RequiresApproval || preview.ApprovalFingerprint == nil || *preview.ApprovalFingerprint == "" {
		return "", scheduleApprovalClaims{}, errors.New("worker preview does not require a write approval")
	}
	if preview.Operation != "create" && preview.Operation != "renew" {
		return "", scheduleApprovalClaims{}, errors.New("worker preview has an invalid operation")
	}
	if preview.ActionFingerprint == "" {
		return "", scheduleApprovalClaims{}, errors.New("worker preview has no action fingerprint")
	}
	if strings.TrimSpace(preview.Timezone) == "" || strings.TrimSpace(preview.MisfirePolicy) == "" {
		return "", scheduleApprovalClaims{}, errors.New("worker preview has incomplete time terms")
	}
	if (preview.Operation == "create" && preview.ScheduleID != nil) ||
		(preview.Operation == "renew" && (preview.ScheduleID == nil || *preview.ScheduleID == "")) {
		return "", scheduleApprovalClaims{}, errors.New("worker preview has an invalid schedule binding")
	}
	if strings.TrimSpace(deviceID) == "" {
		return "", scheduleApprovalClaims{}, errors.New("approval is not bound to an authenticated device")
	}

	nonceBytes := make([]byte, 32)
	if _, err := rand.Read(nonceBytes); err != nil {
		return "", scheduleApprovalClaims{}, fmt.Errorf("approval nonce: %w", err)
	}
	claims := scheduleApprovalClaims{
		Version:             2,
		Nonce:               base64.RawURLEncoding.EncodeToString(nonceBytes),
		DeviceID:            deviceID,
		Operation:           preview.Operation,
		ScheduleID:          preview.ScheduleID,
		Tool:                preview.Tool,
		Args:                preview.Args,
		Cadence:             preview.Cadence,
		Timezone:            preview.Timezone,
		MisfirePolicy:       preview.MisfirePolicy,
		TTLDays:             preview.TTLDays,
		MaxRuns:             preview.MaxRuns,
		Enable:              preview.Enable,
		ActionFingerprint:   preview.ActionFingerprint,
		ApprovalFingerprint: *preview.ApprovalFingerprint,
		IssuedAt:            now.Unix(),
		ExpiresAt:           now.Add(scheduleApprovalTTL).Unix(),
	}
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", scheduleApprovalClaims{}, fmt.Errorf("approval payload: %w", err)
	}
	payloadPart := base64.RawURLEncoding.EncodeToString(payload)
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(payloadPart))
	signaturePart := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	return payloadPart + "." + signaturePart, claims, nil
}

func verifyScheduleApprovalToken(token, deviceID string, now time.Time) (scheduleApprovalClaims, error) {
	secret, err := scheduleApprovalSecret()
	if err != nil {
		return scheduleApprovalClaims{}, err
	}
	parts := strings.Split(token, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return scheduleApprovalClaims{}, errors.New("schedule approval token is malformed")
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return scheduleApprovalClaims{}, errors.New("schedule approval token is malformed")
	}
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(parts[0]))
	if !hmac.Equal(mac.Sum(nil), signature) {
		return scheduleApprovalClaims{}, errors.New("schedule approval token signature is invalid")
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return scheduleApprovalClaims{}, errors.New("schedule approval token is malformed")
	}
	var claims scheduleApprovalClaims
	if err := json.Unmarshal(payload, &claims); err != nil {
		return scheduleApprovalClaims{}, errors.New("schedule approval token payload is invalid")
	}
	if claims.Version != 2 || claims.Nonce == "" || claims.DeviceID == "" ||
		strings.TrimSpace(claims.Timezone) == "" || strings.TrimSpace(claims.MisfirePolicy) == "" {
		return scheduleApprovalClaims{}, errors.New("schedule approval token claims are invalid")
	}
	if claims.DeviceID != deviceID {
		return scheduleApprovalClaims{}, errors.New("schedule approval token belongs to another paired device")
	}
	if claims.IssuedAt > now.Add(30*time.Second).Unix() {
		return scheduleApprovalClaims{}, errors.New("schedule approval token is not valid yet")
	}
	if claims.ExpiresAt <= now.Unix() {
		return scheduleApprovalClaims{}, errors.New("schedule approval token has expired; confirm the preview again")
	}
	if claims.ExpiresAt <= claims.IssuedAt || time.Duration(claims.ExpiresAt-claims.IssuedAt)*time.Second > 3*time.Minute {
		return scheduleApprovalClaims{}, errors.New("schedule approval token lifetime is invalid")
	}
	return claims, nil
}

func readScheduleBody(r *http.Request) ([]byte, error) {
	defer r.Body.Close()
	body, err := io.ReadAll(io.LimitReader(r.Body, maxScheduleBodyBytes+1))
	if err != nil {
		return nil, err
	}
	if len(body) > maxScheduleBodyBytes {
		return nil, errors.New("schedule request is too large")
	}
	return body, nil
}

func decodeScheduleJSON(body []byte, dst any) error {
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		return err
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		return errors.New("schedule request contains trailing JSON")
	}
	return nil
}

func (s *server) callScheduleWorker(
	ctx context.Context,
	requestID string,
	method string,
	workerPath string,
	rawQuery string,
	body []byte,
) (int, string, []byte, error) {
	if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		return 0, "", nil, errors.New("schedule administration requires a loopback worker upstream")
	}
	target := s.Worker.BaseURL + workerPath
	if rawQuery != "" {
		target += "?" + rawQuery
	}
	req, err := http.NewRequestWithContext(ctx, method, target, bytes.NewReader(body))
	if err != nil {
		return 0, "", nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if requestID != "" {
		req.Header.Set("X-Request-ID", requestID)
	}
	client := &http.Client{Timeout: s.Cfg.RequestTimeout}
	resp, err := client.Do(req)
	if err != nil {
		return 0, "", nil, err
	}
	defer resp.Body.Close()
	responseBody, err := io.ReadAll(io.LimitReader(resp.Body, maxScheduleBodyBytes+1))
	if err != nil {
		return 0, "", nil, err
	}
	if len(responseBody) > maxScheduleBodyBytes {
		return 0, "", nil, errors.New("schedule worker response is too large")
	}
	return resp.StatusCode, resp.Header.Get("Content-Type"), responseBody, nil
}

func writeScheduleWorkerResponse(w http.ResponseWriter, status int, contentType string, body []byte) {
	if contentType != "" {
		w.Header().Set("Content-Type", contentType)
	}
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

func (s *server) previewForApproval(
	w http.ResponseWriter,
	r *http.Request,
	workerPath string,
	previewBody []byte,
) (scheduleApprovalPreview, bool) {
	status, contentType, responseBody, err := s.callScheduleWorker(
		r.Context(), r.Header.Get("X-Request-ID"), http.MethodPost, workerPath, r.URL.RawQuery, previewBody,
	)
	if err != nil {
		writeErr(w, http.StatusServiceUnavailable, err.Error())
		return scheduleApprovalPreview{}, false
	}
	if status != http.StatusOK {
		writeScheduleWorkerResponse(w, status, contentType, responseBody)
		return scheduleApprovalPreview{}, false
	}
	var envelope schedulePreviewEnvelope
	if err := json.Unmarshal(responseBody, &envelope); err != nil {
		writeErr(w, http.StatusBadGateway, "schedule worker returned an invalid preview")
		return scheduleApprovalPreview{}, false
	}
	return envelope.Preview, true
}

func (s *server) handleScheduleApproval(w http.ResponseWriter, r *http.Request) {
	body, err := readScheduleBody(r)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}
	var approval scheduleCreateApprovalRequest
	if err := decodeScheduleJSON(body, &approval); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid schedule approval request: "+err.Error())
		return
	}
	if strings.TrimSpace(approval.Tool) == "" || strings.TrimSpace(approval.Cadence) == "" ||
		strings.TrimSpace(approval.PreviewFingerprint) == "" {
		writeErr(w, http.StatusBadRequest, "schedule approval requires tool, cadence and preview_fingerprint")
		return
	}
	previewBody, _ := json.Marshal(scheduleCreateTerms{
		Tool: approval.Tool, Args: approval.Args, Cadence: approval.Cadence,
		TTLDays: approval.TTLDays, MaxRuns: approval.MaxRuns,
	})
	preview, ok := s.previewForApproval(w, r, "/schedules/preview", previewBody)
	if !ok {
		return
	}
	if preview.Operation != "create" || preview.ScheduleID != nil ||
		preview.Tool != approval.Tool || !reflect.DeepEqual(preview.Args, approval.Args) ||
		preview.Cadence != approval.Cadence || preview.TTLDays != approval.TTLDays ||
		preview.MaxRuns != approval.MaxRuns || preview.Enable == nil || !*preview.Enable {
		writeErr(w, http.StatusBadGateway, "schedule worker returned a preview for different create terms")
		return
	}
	if preview.ApprovalFingerprint == nil || approval.PreviewFingerprint != *preview.ApprovalFingerprint {
		writeErr(w, http.StatusConflict, "schedule preview changed; preview and confirm it again")
		return
	}
	deviceID, ok := scheduleDeviceID(r)
	if !ok {
		writeErr(w, http.StatusUnauthorized, "authenticated device context is missing")
		return
	}
	token, claims, err := issueScheduleApprovalToken(preview, deviceID, time.Now())
	if errors.Is(err, errScheduleApprovalUnavailable) {
		writeErr(w, http.StatusServiceUnavailable, scheduleApprovalSecretEnv+" is not configured in backend and worker")
		return
	}
	if err != nil {
		writeErr(w, http.StatusConflict, err.Error())
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]any{
		"approval_token": token,
		"expires_at":     claims.ExpiresAt,
	})
}

func (s *server) handleScheduleRenewApproval(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "/renew/preview")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	body, err := readScheduleBody(r)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}
	var approval scheduleRenewApprovalRequest
	if err := decodeScheduleJSON(body, &approval); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid schedule renewal approval request: "+err.Error())
		return
	}
	if strings.TrimSpace(approval.PreviewFingerprint) == "" {
		writeErr(w, http.StatusBadRequest, "schedule renewal approval requires preview_fingerprint")
		return
	}
	previewBody, _ := json.Marshal(scheduleRenewTerms{
		TTLDays: approval.TTLDays, MaxRuns: approval.MaxRuns, Enable: approval.Enable,
	})
	preview, ok := s.previewForApproval(w, r, path, previewBody)
	if !ok {
		return
	}
	if preview.Operation != "renew" || preview.ScheduleID == nil || *preview.ScheduleID != r.PathValue("id") ||
		preview.TTLDays != approval.TTLDays || preview.MaxRuns != approval.MaxRuns ||
		!reflect.DeepEqual(preview.Enable, approval.Enable) {
		writeErr(w, http.StatusBadGateway, "schedule worker returned a preview for different renewal terms")
		return
	}
	if preview.ApprovalFingerprint == nil || approval.PreviewFingerprint != *preview.ApprovalFingerprint {
		writeErr(w, http.StatusConflict, "schedule renewal preview changed; preview and confirm it again")
		return
	}
	deviceID, ok := scheduleDeviceID(r)
	if !ok {
		writeErr(w, http.StatusUnauthorized, "authenticated device context is missing")
		return
	}
	token, claims, err := issueScheduleApprovalToken(preview, deviceID, time.Now())
	if errors.Is(err, errScheduleApprovalUnavailable) {
		writeErr(w, http.StatusServiceUnavailable, scheduleApprovalSecretEnv+" is not configured in backend and worker")
		return
	}
	if err != nil {
		writeErr(w, http.StatusConflict, err.Error())
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]any{
		"approval_token": token,
		"expires_at":     claims.ExpiresAt,
	})
}

func claimsMatchCreate(claims scheduleApprovalClaims, req scheduleCreateCommitRequest) bool {
	return claims.Operation == "create" && claims.ScheduleID == nil &&
		claims.Tool == req.Tool && reflect.DeepEqual(claims.Args, req.Args) &&
		claims.Cadence == req.Cadence && claims.TTLDays == req.TTLDays &&
		claims.MaxRuns == req.MaxRuns && claims.Enable != nil && *claims.Enable
}

func claimsMatchRenew(claims scheduleApprovalClaims, scheduleID string, req scheduleRenewCommitRequest) bool {
	return claims.Operation == "renew" && claims.ScheduleID != nil && *claims.ScheduleID == scheduleID &&
		claims.TTLDays == req.TTLDays && claims.MaxRuns == req.MaxRuns &&
		reflect.DeepEqual(claims.Enable, req.Enable)
}

func (s *server) handleScheduleCreate(w http.ResponseWriter, r *http.Request) {
	body, err := readScheduleBody(r)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}
	var req scheduleCreateCommitRequest
	if err := json.Unmarshal(body, &req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid schedule create request")
		return
	}
	if req.ApprovalToken != "" {
		if err := decodeScheduleJSON(body, &req); err != nil {
			writeErr(w, http.StatusBadRequest, "invalid schedule create request: "+err.Error())
			return
		}
		deviceID, ok := scheduleDeviceID(r)
		if !ok {
			writeErr(w, http.StatusUnauthorized, "authenticated device context is missing")
			return
		}
		claims, err := verifyScheduleApprovalToken(req.ApprovalToken, deviceID, time.Now())
		if errors.Is(err, errScheduleApprovalUnavailable) {
			writeErr(w, http.StatusServiceUnavailable, scheduleApprovalSecretEnv+" is not configured in backend and worker")
			return
		}
		if err != nil || !claimsMatchCreate(claims, req) {
			if err == nil {
				err = errors.New("schedule approval does not match the create request")
			}
			writeErr(w, http.StatusConflict, err.Error())
			return
		}
		body, _ = json.Marshal(req)
	}
	s.forwardScheduleBytes(w, r, "/schedules", body)
}

func (s *server) handleScheduleRenewCommit(w http.ResponseWriter, r *http.Request, path string) {
	body, err := readScheduleBody(r)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}
	var req scheduleRenewCommitRequest
	if err := json.Unmarshal(body, &req); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid schedule renewal request")
		return
	}
	if req.ApprovalToken != "" {
		if err := decodeScheduleJSON(body, &req); err != nil {
			writeErr(w, http.StatusBadRequest, "invalid schedule renewal request: "+err.Error())
			return
		}
		deviceID, ok := scheduleDeviceID(r)
		if !ok {
			writeErr(w, http.StatusUnauthorized, "authenticated device context is missing")
			return
		}
		claims, err := verifyScheduleApprovalToken(req.ApprovalToken, deviceID, time.Now())
		if errors.Is(err, errScheduleApprovalUnavailable) {
			writeErr(w, http.StatusServiceUnavailable, scheduleApprovalSecretEnv+" is not configured in backend and worker")
			return
		}
		if err != nil || !claimsMatchRenew(claims, r.PathValue("id"), req) {
			if err == nil {
				err = errors.New("schedule approval does not match the renewal request")
			}
			writeErr(w, http.StatusConflict, err.Error())
			return
		}
		body, _ = json.Marshal(req)
	}
	s.forwardScheduleBytes(w, r, path, body)
}

func (s *server) forwardScheduleBytes(w http.ResponseWriter, r *http.Request, workerPath string, body []byte) {
	status, contentType, responseBody, err := s.callScheduleWorker(
		r.Context(), r.Header.Get("X-Request-ID"), r.Method, workerPath, r.URL.RawQuery, body,
	)
	if err != nil {
		writeErr(w, http.StatusServiceUnavailable, err.Error())
		return
	}
	writeScheduleWorkerResponse(w, status, contentType, responseBody)
}
