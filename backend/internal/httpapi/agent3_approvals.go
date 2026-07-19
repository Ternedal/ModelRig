package httpapi

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

const (
	agent3ApprovalSecretEnv   = "KALIV_AGENT3_APPROVAL_SECRET"
	agent3ApprovalRequiredEnv = "KALIV_AGENT3_APPROVAL_REQUIRED"
	agent3ApprovalTTL         = 2 * time.Minute
	maxAgent3ApprovalBody     = 32 << 10
	maxAgent3WorkerBody       = 128 << 10
)

var errAgent3ApprovalUnavailable = errors.New("Agent 3 approval secret is unavailable")

type agent3ConfirmRequest struct {
	StepID   string `json:"step_id"`
	Decision string `json:"decision"`
	Digest   string `json:"digest"`
}

type agent3WorkerConfirmRequest struct {
	StepID        string `json:"step_id"`
	Decision      string `json:"decision"`
	Digest        string `json:"digest"`
	ApprovalToken string `json:"approval_token,omitempty"`
}

type agent3RunEnvelope struct {
	Run agent3ApprovalRun `json:"run"`
}

type agent3ApprovalRun struct {
	ID          string               `json:"id"`
	State       string               `json:"state"`
	CurrentStep int                  `json:"current_step"`
	Steps       []agent3ApprovalStep `json:"steps"`
}

type agent3ApprovalStep struct {
	ID                    string         `json:"id"`
	Tool                  string         `json:"tool"`
	Args                  map[string]any `json:"args"`
	Risk                  string         `json:"risk"`
	ConfirmationDigest    *string        `json:"confirmation_digest"`
	ConfirmationExpiresAt *float64       `json:"confirmation_expires_at"`
}

type agent3ReplanState struct {
	Revision int `json:"revision"`
}

type agent3ApprovalClaims struct {
	Version            int    `json:"v"`
	Nonce              string `json:"nonce"`
	DeviceID           string `json:"device_id"`
	RunID              string `json:"run_id"`
	StepID             string `json:"step_id"`
	Tool               string `json:"tool"`
	ArgsSHA256         string `json:"args_sha256"`
	ConfirmationDigest string `json:"confirmation_digest"`
	PlanRevision       int    `json:"plan_revision"`
	IssuedAt           int64  `json:"issued_at"`
	ExpiresAt          int64  `json:"expires_at"`
}

func agent3ApprovalRequired() bool {
	return os.Getenv(agent3ApprovalRequiredEnv) == "1"
}

func agent3ApprovalSecret() ([]byte, error) {
	secret := []byte(os.Getenv(agent3ApprovalSecretEnv))
	if len(secret) < 32 {
		return nil, errAgent3ApprovalUnavailable
	}
	return secret, nil
}

func readAgent3ApprovalBody(r *http.Request) ([]byte, error) {
	defer r.Body.Close()
	body, err := io.ReadAll(io.LimitReader(r.Body, maxAgent3ApprovalBody+1))
	if err != nil {
		return nil, err
	}
	if len(body) > maxAgent3ApprovalBody {
		return nil, errors.New("Agent 3 confirmation request is too large")
	}
	return body, nil
}

func decodeAgent3Confirm(body []byte) (agent3ConfirmRequest, error) {
	var req agent3ConfirmRequest
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		return req, err
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		return req, errors.New("Agent 3 confirmation contains trailing JSON")
	}
	if strings.TrimSpace(req.StepID) == "" || strings.TrimSpace(req.Digest) == "" {
		return req, errors.New("Agent 3 confirmation requires step_id and digest")
	}
	if req.Decision != "approve" && req.Decision != "deny" {
		return req, errors.New("Agent 3 confirmation decision must be approve or deny")
	}
	return req, nil
}

func agent3ArgsSHA256(args map[string]any) (string, error) {
	// The dormant write pilot authorizes exactly note_append.text. Hashing generic
	// JSON across Go and Python is not a stable contract: number rendering and
	// escaping differ. The immutable confirmation digest already binds the whole
	// step; this separate claim binds the exact executable UTF-8 text.
	if len(args) != 1 {
		return "", errors.New("note_append approval requires exactly one text argument")
	}
	text, ok := args["text"].(string)
	if !ok || strings.TrimSpace(text) == "" || len([]rune(text)) > 10_000 {
		return "", errors.New("note_append approval text is invalid")
	}
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:]), nil
}

func (s *server) readAgent3WorkerJSON(
	ctx context.Context,
	requestID string,
	path string,
	dst any,
) error {
	if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		return errors.New("Agent 3 approval requires a loopback worker upstream")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.Worker.BaseURL+path, nil)
	if err != nil {
		return err
	}
	if requestID != "" {
		req.Header.Set("X-Request-ID", requestID)
	}
	client := &http.Client{Timeout: s.Cfg.RequestTimeout}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxAgent3WorkerBody+1))
	if err != nil {
		return err
	}
	if len(raw) > maxAgent3WorkerBody {
		return errors.New("Agent 3 worker approval response is too large")
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("Agent 3 worker returned HTTP %d", resp.StatusCode)
	}
	if err := json.Unmarshal(raw, dst); err != nil {
		return errors.New("Agent 3 worker returned invalid approval state")
	}
	return nil
}

func (s *server) currentAgent3ApprovalTerms(
	r *http.Request,
	requested agent3ConfirmRequest,
) (agent3ApprovalStep, int, int64, error) {
	runID := r.PathValue("id")
	if strings.TrimSpace(runID) == "" {
		return agent3ApprovalStep{}, 0, 0, errors.New("Agent 3 run id is missing")
	}
	escapedRunID := url.PathEscape(runID)
	requestID := r.Header.Get("X-Request-ID")
	var envelope agent3RunEnvelope
	if err := s.readAgent3WorkerJSON(
		r.Context(), requestID,
		"/experimental/agent3/runs/"+escapedRunID,
		&envelope,
	); err != nil {
		return agent3ApprovalStep{}, 0, 0, err
	}
	run := envelope.Run
	if run.ID != runID || run.State != "waiting_confirmation" {
		return agent3ApprovalStep{}, 0, 0, errors.New("Agent 3 run is not waiting for confirmation")
	}
	if run.CurrentStep < 0 || run.CurrentStep >= len(run.Steps) {
		return agent3ApprovalStep{}, 0, 0, errors.New("Agent 3 run has no current confirmation step")
	}
	step := run.Steps[run.CurrentStep]
	if step.ID != requested.StepID || step.ConfirmationDigest == nil ||
		*step.ConfirmationDigest != requested.Digest {
		return agent3ApprovalStep{}, 0, 0, errors.New("Agent 3 confirmation changed; review it again")
	}
	if step.Tool != "note_append" || step.Risk != "write" {
		return agent3ApprovalStep{}, 0, 0, errors.New("Agent 3 write pilot approval is restricted to note_append")
	}
	if _, err := agent3ArgsSHA256(step.Args); err != nil {
		return agent3ApprovalStep{}, 0, 0, err
	}
	if step.ConfirmationExpiresAt == nil {
		return agent3ApprovalStep{}, 0, 0, errors.New("Agent 3 confirmation has no expiry")
	}
	confirmationExpiry := int64(*step.ConfirmationExpiresAt)
	if confirmationExpiry <= time.Now().Unix() {
		return agent3ApprovalStep{}, 0, 0, errors.New("Agent 3 confirmation expired; review it again")
	}

	var replans agent3ReplanState
	if err := s.readAgent3WorkerJSON(
		r.Context(), requestID,
		"/experimental/agent3/runs/"+escapedRunID+"/replans",
		&replans,
	); err != nil {
		return agent3ApprovalStep{}, 0, 0, err
	}
	if replans.Revision < 0 {
		return agent3ApprovalStep{}, 0, 0, errors.New("Agent 3 worker returned an invalid plan revision")
	}
	return step, replans.Revision, confirmationExpiry, nil
}

func issueAgent3ApprovalToken(
	deviceID string,
	runID string,
	step agent3ApprovalStep,
	planRevision int,
	confirmationExpiry int64,
	now time.Time,
) (string, agent3ApprovalClaims, error) {
	secret, err := agent3ApprovalSecret()
	if err != nil {
		return "", agent3ApprovalClaims{}, err
	}
	if strings.TrimSpace(deviceID) == "" {
		return "", agent3ApprovalClaims{}, errors.New("Agent 3 approval is not bound to an authenticated device")
	}
	argsSHA, err := agent3ArgsSHA256(step.Args)
	if err != nil {
		return "", agent3ApprovalClaims{}, err
	}
	if step.ConfirmationDigest == nil || strings.TrimSpace(*step.ConfirmationDigest) == "" {
		return "", agent3ApprovalClaims{}, errors.New("Agent 3 confirmation digest is missing")
	}
	expiresAt := now.Add(agent3ApprovalTTL).Unix()
	if confirmationExpiry < expiresAt {
		expiresAt = confirmationExpiry
	}
	if expiresAt <= now.Unix() {
		return "", agent3ApprovalClaims{}, errors.New("Agent 3 confirmation expired before approval could be issued")
	}
	nonceBytes := make([]byte, 32)
	if _, err := rand.Read(nonceBytes); err != nil {
		return "", agent3ApprovalClaims{}, fmt.Errorf("Agent 3 approval nonce: %w", err)
	}
	claims := agent3ApprovalClaims{
		Version:            1,
		Nonce:              base64.RawURLEncoding.EncodeToString(nonceBytes),
		DeviceID:           deviceID,
		RunID:              runID,
		StepID:             step.ID,
		Tool:               step.Tool,
		ArgsSHA256:         argsSHA,
		ConfirmationDigest: *step.ConfirmationDigest,
		PlanRevision:       planRevision,
		IssuedAt:           now.Unix(),
		ExpiresAt:          expiresAt,
	}
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", agent3ApprovalClaims{}, err
	}
	payloadPart := base64.RawURLEncoding.EncodeToString(payload)
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(payloadPart))
	signaturePart := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	return payloadPart + "." + signaturePart, claims, nil
}

func (s *server) handleAgent3ApprovalConfirm(w http.ResponseWriter, r *http.Request) {
	body, err := readAgent3ApprovalBody(r)
	if err != nil {
		writeErr(w, http.StatusBadRequest, err.Error())
		return
	}
	confirm, err := decodeAgent3Confirm(body)
	if err != nil {
		writeErr(w, http.StatusBadRequest, "invalid Agent 3 confirmation: "+err.Error())
		return
	}

	forward := agent3WorkerConfirmRequest{
		StepID:   confirm.StepID,
		Decision: confirm.Decision,
		Digest:   confirm.Digest,
	}
	if confirm.Decision == "approve" {
		secretConfigured := false
		if _, secretErr := agent3ApprovalSecret(); secretErr == nil {
			secretConfigured = true
		} else if !errors.Is(secretErr, errAgent3ApprovalUnavailable) {
			writeErr(w, http.StatusServiceUnavailable, secretErr.Error())
			return
		}
		if agent3ApprovalRequired() || secretConfigured {
			if !secretConfigured {
				writeErr(w, http.StatusServiceUnavailable,
					agent3ApprovalSecretEnv+" is not configured in backend and worker")
				return
			}
			deviceID, ok := scheduleDeviceID(r)
			if !ok {
				writeErr(w, http.StatusUnauthorized, "authenticated device context is missing")
				return
			}
			step, revision, confirmationExpiry, err := s.currentAgent3ApprovalTerms(r, confirm)
			if err != nil {
				writeErr(w, http.StatusConflict, err.Error())
				return
			}
			token, _, err := issueAgent3ApprovalToken(
				deviceID,
				r.PathValue("id"),
				step,
				revision,
				confirmationExpiry,
				time.Now(),
			)
			if err != nil {
				writeErr(w, http.StatusConflict, err.Error())
				return
			}
			forward.ApprovalToken = token
		}
	}

	forwardBody, err := json.Marshal(forward)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "could not encode Agent 3 confirmation")
		return
	}
	r.Body = io.NopCloser(bytes.NewReader(forwardBody))
	r.ContentLength = int64(len(forwardBody))
	r.Header.Set("Content-Type", "application/json")
	s.WorkerSlow.Forward(w, r, agent3RunTarget(r, "/confirm"))
}
