package httpapi

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	scheduleApprovalTokenPrefix = "kav1"
	scheduleApprovalAudience    = "kaliv-scheduler"
	scheduleApprovalTokenTTL    = 5 * time.Minute
	scheduleApprovalBodyMax     = 64 * 1024
)

// Schedule administration is intentionally split across two trust boundaries:
// the backend authenticates paired devices and is the only process allowed to
// mint approval tokens. The worker owns validation, persistence and execution
// policy, but receives only an Ed25519 public key and therefore cannot mint
// consent for itself. Every worker hop remains loopback-only.
func scheduleWorkerIsLoopback(raw string) bool {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") {
		return false
	}
	host := strings.TrimSuffix(strings.ToLower(u.Hostname()), ".")
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func validScheduleID(id string) bool {
	if len(id) != 12 {
		return false
	}
	for _, r := range id {
		if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f')) {
			return false
		}
	}
	return true
}

func (s *server) forwardSchedule(w http.ResponseWriter, r *http.Request, workerPath string) {
	if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		writeErr(w, http.StatusServiceUnavailable,
			"schedule administration requires a loopback worker upstream")
		return
	}
	s.Worker.Forward(w, r, workerPath)
}

func scheduleIDPath(r *http.Request, suffix string) (string, bool) {
	id := r.PathValue("id")
	if !validScheduleID(id) {
		return "", false
	}
	return "/schedules/" + id + suffix, true
}

func decodeScheduleApprovalPrivateKey(encoded string) (ed25519.PrivateKey, error) {
	encoded = strings.TrimSpace(encoded)
	if encoded == "" {
		return nil, errors.New("approval private key is not configured")
	}
	var raw []byte
	var err error
	for _, enc := range []*base64.Encoding{base64.StdEncoding, base64.RawStdEncoding} {
		raw, err = enc.DecodeString(encoded)
		if err == nil {
			break
		}
	}
	if err != nil || len(raw) != ed25519.SeedSize {
		return nil, errors.New("approval private key must be a base64 Ed25519 seed")
	}
	return ed25519.NewKeyFromSeed(raw), nil
}

type scheduleApprovalClaims struct {
	Version  int    `json:"v"`
	Audience string `json:"aud"`
	Binding  string `json:"binding"`
	Expires  int64  `json:"exp"`
	Nonce    string `json:"nonce"`
}

func issueScheduleApprovalToken(privateKeyText, binding string, now time.Time) (string, int64, error) {
	if len(binding) != 64 {
		return "", 0, errors.New("worker returned an invalid approval binding")
	}
	for _, r := range binding {
		if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f')) {
			return "", 0, errors.New("worker returned an invalid approval binding")
		}
	}
	privateKey, err := decodeScheduleApprovalPrivateKey(privateKeyText)
	if err != nil {
		return "", 0, err
	}
	nonceRaw := make([]byte, 18)
	if _, err := rand.Read(nonceRaw); err != nil {
		return "", 0, errors.New("could not generate approval nonce")
	}
	expires := now.Add(scheduleApprovalTokenTTL).Unix()
	claims := scheduleApprovalClaims{
		Version:  1,
		Audience: scheduleApprovalAudience,
		Binding:  binding,
		Expires:  expires,
		Nonce:    base64.RawURLEncoding.EncodeToString(nonceRaw),
	}
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", 0, err
	}
	signature := ed25519.Sign(privateKey, payload)
	return scheduleApprovalTokenPrefix + "." +
		base64.RawURLEncoding.EncodeToString(payload) + "." +
		base64.RawURLEncoding.EncodeToString(signature), expires, nil
}

// approveSchedule asks the worker to re-preview the exact grant after bearer
// authentication, then signs only the binding returned by that loopback worker.
// The ordinary preview endpoint never mints a token: issuance happens only on
// the explicit UI confirmation call.
func (s *server) approveSchedule(w http.ResponseWriter, r *http.Request, workerPath string) {
	if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		writeErr(w, http.StatusServiceUnavailable,
			"schedule approval requires a loopback worker upstream")
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, scheduleApprovalBodyMax+1))
	if err != nil {
		writeErr(w, http.StatusBadRequest, "could not read schedule approval request")
		return
	}
	if len(body) > scheduleApprovalBodyMax {
		writeErr(w, http.StatusRequestEntityTooLarge, "schedule approval request is too large")
		return
	}
	target := strings.TrimRight(s.Worker.BaseURL, "/") + workerPath
	if r.URL.RawQuery != "" {
		target += "?" + r.URL.RawQuery
	}
	upstream, err := http.NewRequestWithContext(r.Context(), http.MethodPost, target, strings.NewReader(string(body)))
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "bad schedule approval request")
		return
	}
	upstream.ContentLength = int64(len(body))
	upstream.Header.Set("Content-Type", "application/json")
	upstream.Header.Set("Accept", "application/json")
	if rid := r.Header.Get("X-Request-ID"); rid != "" {
		upstream.Header.Set("X-Request-ID", rid)
	}
	client := &http.Client{Timeout: s.Cfg.RequestTimeout}
	resp, err := client.Do(upstream)
	if err != nil {
		writeErr(w, http.StatusBadGateway, "schedule worker unreachable: "+err.Error())
		return
	}
	defer resp.Body.Close()
	responseBody, err := io.ReadAll(io.LimitReader(resp.Body, scheduleApprovalBodyMax+1))
	if err != nil || len(responseBody) > scheduleApprovalBodyMax {
		writeErr(w, http.StatusBadGateway, "schedule worker returned an invalid response")
		return
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		if ct := resp.Header.Get("Content-Type"); ct != "" {
			w.Header().Set("Content-Type", ct)
		}
		w.WriteHeader(resp.StatusCode)
		_, _ = w.Write(responseBody)
		return
	}
	var document map[string]any
	if err := json.Unmarshal(responseBody, &document); err != nil {
		writeErr(w, http.StatusBadGateway, "schedule worker returned invalid JSON")
		return
	}
	preview, ok := document["preview"].(map[string]any)
	if !ok || preview["requires_approval"] != true {
		writeErr(w, http.StatusUnprocessableEntity,
			"only scheduled writes require an approval token")
		return
	}
	binding, _ := preview["approval_binding"].(string)
	token, expires, err := issueScheduleApprovalToken(
		s.Cfg.SchedulerApprovalPrivateKey, binding, time.Now().UTC(),
	)
	if err != nil {
		writeErr(w, http.StatusServiceUnavailable,
			"schedule approval signing is not configured safely")
		return
	}
	preview["approval_token"] = token
	preview["approval_token_expires_at"] = expires
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	_ = json.NewEncoder(w).Encode(document)
}

func (s *server) handleSchedulesStatus(w http.ResponseWriter, r *http.Request) {
	s.forwardSchedule(w, r, "/schedules/status")
}

func (s *server) handleSchedulesPreview(w http.ResponseWriter, r *http.Request) {
	s.forwardSchedule(w, r, "/schedules/preview")
}

func (s *server) handleSchedulesApprove(w http.ResponseWriter, r *http.Request) {
	s.approveSchedule(w, r, "/schedules/preview")
}

func (s *server) handleSchedulesCollection(w http.ResponseWriter, r *http.Request) {
	s.forwardSchedule(w, r, "/schedules")
}

func (s *server) handleScheduleGet(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	s.forwardSchedule(w, r, path)
}

func (s *server) handleScheduleEnabled(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "/enabled")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	s.forwardSchedule(w, r, path)
}

func (s *server) handleScheduleRenewPreview(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "/renew/preview")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	s.forwardSchedule(w, r, path)
}

func (s *server) handleScheduleRenewApprove(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "/renew/preview")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	s.approveSchedule(w, r, path)
}

func (s *server) handleScheduleRenew(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "/renew")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	s.forwardSchedule(w, r, path)
}
