package httpapi

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

const (
	consciousnessChatFlag                = "KALIV_CONSCIOUSNESS_CHAT_ENABLED"
	consciousnessTurnCognitionFlag       = "KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED"
	consciousnessUserTurnPath            = "/experimental/consciousness/user-turn"
	consciousnessExactEventStepPath      = "/experimental/consciousness/step-event"
	consciousnessTurnReceiptSchema       = "kaliv-consciousness-core/user-turn-admission/v1"
	consciousnessExactEventReceiptSchema = "kaliv-consciousness-core/exact-event-step-receipt/v1"
	consciousnessMaxChatProbeBytes       = 2 << 20
	consciousnessMaxUserTurnCharacters   = 2048
	consciousnessMaxRequestIDCharacters  = 128
	consciousnessMaxWorkerResponseBytes  = 64 << 10
	consciousnessAdmissionTimeout        = 2 * time.Second
	consciousnessCognitionTimeout        = 2 * time.Minute
	consciousnessBackendSourceRefPrefix  = "backend-chat:"
)

type consciousnessChatProbe struct {
	Messages []consciousnessChatProbeMessage `json:"messages"`
}

type consciousnessChatProbeMessage struct {
	Role    string          `json:"role"`
	Content json.RawMessage `json:"content"`
}

type consciousnessUserTurnRequest struct {
	TurnID    string `json:"turn_id"`
	UserText  string `json:"user_text"`
	SourceRef string `json:"source_ref"`
}

type consciousnessUserTurnReceipt struct {
	Schema                      string  `json:"schema"`
	TurnRef                     string  `json:"turn_ref"`
	EvidenceRef                 string  `json:"evidence_ref"`
	CognitionEventID            *string `json:"cognition_event_id"`
	WorldChanged                bool    `json:"world_changed"`
	Replayed                    bool    `json:"replayed"`
	CognitionEventQueued        bool    `json:"cognition_event_queued"`
	EpistemicStatus             string  `json:"epistemic_status"`
	Confidence                  float64 `json:"confidence"`
	ObservedSequence            int64   `json:"observed_sequence"`
	ModelCalls                  int     `json:"model_calls"`
	SelfStateStoreWriteApplied  bool    `json:"self_state_store_write_applied"`
	DurableMemoryWriteAuthority bool    `json:"durable_memory_write_authority"`
	ExecutionAuthority          bool    `json:"execution_authority"`
	SchedulingAuthority         bool    `json:"scheduling_authority"`
	ProductionActivation        bool    `json:"production_activation"`
}

type consciousnessExactEventStepRequest struct {
	RequiredEventID string `json:"required_event_id"`
}

type consciousnessExactEventStepReceipt struct {
	Schema                      string   `json:"schema"`
	RequiredEventID             string   `json:"required_event_id"`
	Decision                    string   `json:"decision"`
	SelectedEventIDs            []string `json:"selected_event_ids"`
	RequiredEventSelected       bool     `json:"required_event_selected"`
	ThoughtEngineInvoked        bool     `json:"thought_engine_invoked"`
	ModelCalls                  int      `json:"model_calls"`
	ProfileRef                  string   `json:"profile_ref"`
	ProfileID                   string   `json:"profile_id"`
	ProfileConfigSHA256         string   `json:"profile_config_sha256"`
	SelfStateRef                string   `json:"self_state_ref"`
	WorldStateRef               string   `json:"world_state_ref"`
	WorkspaceRef                string   `json:"workspace_ref"`
	TransitionReceiptRef        *string  `json:"transition_receipt_ref"`
	CompletedCycles             int      `json:"completed_cycles"`
	ContextUpdated              bool     `json:"context_updated"`
	AutomaticRepeat             bool     `json:"automatic_repeat"`
	InternalThreadCreated       bool     `json:"internal_thread_created"`
	InternalTimerCreated        bool     `json:"internal_timer_created"`
	SelfStateStoreWriteApplied  bool     `json:"self_state_store_write_applied"`
	DurableMemoryWriteAuthority bool     `json:"durable_memory_write_authority"`
	ExecutionAuthority          bool     `json:"execution_authority"`
	SchedulingAuthority         bool     `json:"scheduling_authority"`
	ProductionActivation        bool     `json:"production_activation"`
}

// handleConsciousnessChat is an additive pre-turn observer around the existing
// normal-chat owner. Flag-off delegates immediately without touching the body or
// worker. Flag-on may submit one bounded final user message to C21-A, then always
// restores the original body and delegates model/memory semantics unchanged.
func (s *server) handleConsciousnessChat(w http.ResponseWriter, r *http.Request) {
	if os.Getenv(consciousnessChatFlag) != "1" {
		s.handleMemory4Chat(w, r)
		return
	}

	originalLength := r.ContentLength
	probe, err := io.ReadAll(io.LimitReader(r.Body, consciousnessMaxChatProbeBytes+1))
	if err != nil {
		consciousnessRestorePartialProbe(r, probe, originalLength)
		s.handleMemory4Chat(w, r)
		return
	}
	if len(probe) > consciousnessMaxChatProbeBytes {
		consciousnessRestorePartialProbe(r, probe, originalLength)
		s.handleMemory4Chat(w, r)
		return
	}

	userText, ok := consciousnessUserForTurn(probe)
	restoreConsciousnessChatBody(r, probe, originalLength)
	if !ok {
		s.handleMemory4Chat(w, r)
		return
	}

	requestID, ok := consciousnessRequestID(r)
	deviceID, deviceOK := scheduleDeviceID(r)
	if !ok || !deviceOK || s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		s.handleMemory4Chat(w, r)
		return
	}
	turnID := consciousnessBoundTurnID(deviceID, requestID)

	// Secondary best-effort observation. There is deliberately no retry,
	// goroutine, queue or response mutation on failure.
	receipt, admissionErr := s.requestConsciousnessUserTurn(r, consciousnessUserTurnRequest{
		TurnID:    turnID,
		UserText:  userText,
		SourceRef: consciousnessBackendSourceRefPrefix + turnID,
	})
	if admissionErr == nil &&
		os.Getenv(consciousnessTurnCognitionFlag) == "1" &&
		!receipt.Replayed &&
		receipt.CognitionEventQueued &&
		receipt.CognitionEventID != nil {
		eventID := *receipt.CognitionEventID
		// Explicit opt-in only. The exact event id is obtained from the already
		// validated C21 receipt; no caller prompt/model/profile crosses this seam.
		step, stepErr := s.requestConsciousnessExactEventStep(r, eventID)
		if stepErr == nil &&
			consciousnessReplyGuidanceEnabled() &&
			step.Decision == "RUN" &&
			step.RequiredEventSelected &&
			containsConsciousnessEventID(step.SelectedEventIDs, eventID) {
			guidance, guidanceErr := s.requestConsciousnessGuidance(r, eventID)
			if guidanceErr == nil {
				guidedBody, injectErr := injectConsciousnessResponseGuidance(
					probe,
					guidance.Text,
				)
				if injectErr == nil {
					r.Body = io.NopCloser(bytes.NewReader(guidedBody))
					r.ContentLength = int64(len(guidedBody))
					r.Header.Del("Content-Length")
					s.handleMemory4Chat(w, r)
					return
				}
			}
		}
	}
	s.handleMemory4Chat(w, r)
}

func consciousnessRestorePartialProbe(r *http.Request, probe []byte, originalLength int64) {
	r.Body = io.NopCloser(io.MultiReader(bytes.NewReader(probe), r.Body))
	r.ContentLength = originalLength
}

func restoreConsciousnessChatBody(r *http.Request, raw []byte, originalLength int64) {
	r.Body = io.NopCloser(bytes.NewReader(raw))
	r.ContentLength = originalLength
}

func consciousnessUserForTurn(raw []byte) (string, bool) {
	var probe consciousnessChatProbe
	if err := json.Unmarshal(raw, &probe); err != nil || len(probe.Messages) == 0 {
		return "", false
	}
	turn := probe.Messages[len(probe.Messages)-1]
	if turn.Role != "user" {
		return "", false
	}
	var content string
	if err := json.Unmarshal(turn.Content, &content); err != nil {
		return "", false
	}
	if strings.TrimSpace(content) == "" ||
		utf8.RuneCountInString(content) > consciousnessMaxUserTurnCharacters {
		return "", false
	}
	return content, true
}

func consciousnessRequestID(r *http.Request) (string, bool) {
	value := strings.TrimSpace(r.Header.Get("X-Request-ID"))
	if value == "" || utf8.RuneCountInString(value) > consciousnessMaxRequestIDCharacters {
		return "", false
	}
	for _, ch := range value {
		if unicode.IsControl(ch) {
			return "", false
		}
	}
	return value, true
}

func consciousnessBoundTurnID(deviceID, requestID string) string {
	sum := sha256.Sum256([]byte(deviceID + "\x00" + requestID))
	return "chat-" + hex.EncodeToString(sum[:])
}

func consciousnessTurnRef(turnID string) string {
	sum := sha256.Sum256([]byte(turnID))
	return "chat-turn:" + hex.EncodeToString(sum[:])
}

func (s *server) requestConsciousnessUserTurn(
	r *http.Request,
	payload consciousnessUserTurnRequest,
) (consciousnessUserTurnReceipt, error) {
	var zero consciousnessUserTurnReceipt
	body, err := json.Marshal(payload)
	if err != nil {
		return zero, err
	}
	req, err := http.NewRequestWithContext(
		r.Context(),
		http.MethodPost,
		s.Worker.BaseURL+consciousnessUserTurnPath,
		bytes.NewReader(body),
	)
	if err != nil {
		return zero, err
	}
	req.Header.Set("Content-Type", "application/json")
	if traceID := strings.TrimSpace(r.Header.Get("X-Request-ID")); traceID != "" {
		req.Header.Set("X-Request-ID", traceID)
	}

	resp, err := memory4WorkerHTTPClient(consciousnessAdmissionTimeout).Do(req)
	if err != nil {
		return zero, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return zero, errors.New("consciousness user-turn worker refused request")
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, consciousnessMaxWorkerResponseBytes+1))
	if err != nil {
		return zero, err
	}
	if len(raw) > consciousnessMaxWorkerResponseBytes {
		return zero, errors.New("consciousness user-turn response exceeds bound")
	}
	if err := requireConsciousnessTurnReceiptFields(raw); err != nil {
		return zero, err
	}

	var receipt consciousnessUserTurnReceipt
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&receipt); err != nil {
		return zero, err
	}
	if err := ensureMemory4JSONEOF(dec); err != nil {
		return zero, err
	}
	if err := validateConsciousnessTurnReceipt(receipt, payload.TurnID); err != nil {
		return zero, err
	}
	return receipt, nil
}

func (s *server) requestConsciousnessExactEventStep(
	r *http.Request,
	requiredEventID string,
) (consciousnessExactEventStepReceipt, error) {
	var zero consciousnessExactEventStepReceipt
	if !validConsciousnessEventID(requiredEventID) {
		return zero, errors.New("consciousness exact-event id is invalid")
	}
	body, err := json.Marshal(consciousnessExactEventStepRequest{
		RequiredEventID: requiredEventID,
	})
	if err != nil {
		return zero, err
	}
	req, err := http.NewRequestWithContext(
		r.Context(),
		http.MethodPost,
		s.Worker.BaseURL+consciousnessExactEventStepPath,
		bytes.NewReader(body),
	)
	if err != nil {
		return zero, err
	}
	req.Header.Set("Content-Type", "application/json")
	if traceID := strings.TrimSpace(r.Header.Get("X-Request-ID")); traceID != "" {
		req.Header.Set("X-Request-ID", traceID)
	}

	resp, err := memory4WorkerHTTPClient(consciousnessCognitionTimeout).Do(req)
	if err != nil {
		return zero, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return zero, errors.New("consciousness exact-event worker refused request")
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, consciousnessMaxWorkerResponseBytes+1))
	if err != nil {
		return zero, err
	}
	if len(raw) > consciousnessMaxWorkerResponseBytes {
		return zero, errors.New("consciousness exact-event response exceeds bound")
	}
	if err := requireConsciousnessExactEventReceiptFields(raw); err != nil {
		return zero, err
	}

	var receipt consciousnessExactEventStepReceipt
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&receipt); err != nil {
		return zero, err
	}
	if err := ensureMemory4JSONEOF(dec); err != nil {
		return zero, err
	}
	if err := validateConsciousnessExactEventReceipt(receipt, requiredEventID); err != nil {
		return zero, err
	}
	return receipt, nil
}

func requireConsciousnessExactEventReceiptFields(raw []byte) error {
	var top map[string]json.RawMessage
	if err := json.Unmarshal(raw, &top); err != nil {
		return err
	}
	required := []string{
		"schema",
		"required_event_id",
		"decision",
		"selected_event_ids",
		"required_event_selected",
		"thought_engine_invoked",
		"model_calls",
		"profile_ref",
		"profile_id",
		"profile_config_sha256",
		"self_state_ref",
		"world_state_ref",
		"workspace_ref",
		"transition_receipt_ref",
		"completed_cycles",
		"context_updated",
		"automatic_repeat",
		"internal_thread_created",
		"internal_timer_created",
		"self_state_store_write_applied",
		"durable_memory_write_authority",
		"execution_authority",
		"scheduling_authority",
		"production_activation",
	}
	if len(top) != len(required) {
		return errors.New("consciousness exact-event receipt fields mismatch")
	}
	for _, name := range required {
		if _, ok := top[name]; !ok {
			return errors.New("consciousness exact-event receipt missing required field")
		}
	}
	return nil
}

func validateConsciousnessExactEventReceipt(
	receipt consciousnessExactEventStepReceipt,
	requiredEventID string,
) error {
	if receipt.Schema != consciousnessExactEventReceiptSchema {
		return errors.New("consciousness exact-event receipt schema mismatch")
	}
	if receipt.RequiredEventID != requiredEventID ||
		!validConsciousnessEventID(receipt.RequiredEventID) {
		return errors.New("consciousness exact-event receipt binding mismatch")
	}
	if !validConsciousnessProfileID(receipt.ProfileID) ||
		!validConsciousnessHex(receipt.ProfileConfigSHA256, 64) {
		return errors.New("consciousness exact-event profile receipt is invalid")
	}
	if strings.TrimSpace(receipt.ProfileRef) == "" ||
		len(receipt.ProfileRef) > 256 ||
		strings.TrimSpace(receipt.SelfStateRef) == "" ||
		len(receipt.SelfStateRef) > 256 ||
		strings.TrimSpace(receipt.WorldStateRef) == "" ||
		len(receipt.WorldStateRef) > 256 ||
		strings.TrimSpace(receipt.WorkspaceRef) == "" ||
		len(receipt.WorkspaceRef) > 256 {
		return errors.New("consciousness exact-event state refs are invalid")
	}
	if receipt.CompletedCycles < 0 ||
		receipt.AutomaticRepeat ||
		receipt.InternalThreadCreated ||
		receipt.InternalTimerCreated ||
		receipt.SelfStateStoreWriteApplied ||
		receipt.DurableMemoryWriteAuthority ||
		receipt.ExecutionAuthority ||
		receipt.SchedulingAuthority ||
		receipt.ProductionActivation {
		return errors.New("consciousness exact-event receipt grants forbidden authority")
	}

	switch receipt.Decision {
	case "WAIT":
		if receipt.RequiredEventSelected ||
			len(receipt.SelectedEventIDs) != 0 ||
			receipt.ThoughtEngineInvoked ||
			receipt.ModelCalls != 0 ||
			receipt.ContextUpdated ||
			receipt.TransitionReceiptRef != nil {
			return errors.New("consciousness WAIT receipt is inconsistent")
		}
	case "RUN":
		if !receipt.RequiredEventSelected ||
			!containsConsciousnessEventID(receipt.SelectedEventIDs, requiredEventID) ||
			!receipt.ThoughtEngineInvoked ||
			receipt.ModelCalls != 1 ||
			!receipt.ContextUpdated ||
			receipt.TransitionReceiptRef == nil ||
			strings.TrimSpace(*receipt.TransitionReceiptRef) == "" ||
			len(*receipt.TransitionReceiptRef) > 256 {
			return errors.New("consciousness RUN receipt is inconsistent")
		}
	default:
		return errors.New("consciousness exact-event decision is invalid")
	}

	for _, eventID := range receipt.SelectedEventIDs {
		if !validConsciousnessEventID(eventID) {
			return errors.New("consciousness selected event id is invalid")
		}
	}
	return nil
}

func containsConsciousnessEventID(values []string, wanted string) bool {
	for _, value := range values {
		if value == wanted {
			return true
		}
	}
	return false
}

func validConsciousnessProfileID(value string) bool {
	return strings.HasPrefix(value, "cog-") &&
		len(value) == len("cog-")+32 &&
		validConsciousnessHex(value[len("cog-"):], 32)
}

func validConsciousnessHex(value string, length int) bool {
	if len(value) != length {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func requireConsciousnessTurnReceiptFields(raw []byte) error {
	var top map[string]json.RawMessage
	if err := json.Unmarshal(raw, &top); err != nil {
		return err
	}
	required := []string{
		"schema",
		"turn_ref",
		"evidence_ref",
		"cognition_event_id",
		"world_changed",
		"replayed",
		"cognition_event_queued",
		"epistemic_status",
		"confidence",
		"observed_sequence",
		"model_calls",
		"self_state_store_write_applied",
		"durable_memory_write_authority",
		"execution_authority",
		"scheduling_authority",
		"production_activation",
	}
	if len(top) != len(required) {
		return errors.New("consciousness user-turn receipt fields mismatch")
	}
	for _, name := range required {
		if _, ok := top[name]; !ok {
			return errors.New("consciousness user-turn receipt missing required field")
		}
	}
	return nil
}

func validateConsciousnessTurnReceipt(
	receipt consciousnessUserTurnReceipt,
	turnID string,
) error {
	if receipt.Schema != consciousnessTurnReceiptSchema {
		return errors.New("consciousness user-turn receipt schema mismatch")
	}
	if receipt.TurnRef != consciousnessTurnRef(turnID) {
		return errors.New("consciousness user-turn receipt turn binding mismatch")
	}
	if !validConsciousnessSHARef(receipt.EvidenceRef, "world-evidence-event:") {
		return errors.New("consciousness user-turn evidence ref is invalid")
	}
	if receipt.EpistemicStatus != "reported" || receipt.Confidence != 1.0 {
		return errors.New("consciousness user-turn epistemic receipt mismatch")
	}
	if receipt.ObservedSequence <= 0 || receipt.ModelCalls != 0 {
		return errors.New("consciousness user-turn authority receipt mismatch")
	}
	if receipt.SelfStateStoreWriteApplied ||
		receipt.DurableMemoryWriteAuthority ||
		receipt.ExecutionAuthority ||
		receipt.SchedulingAuthority ||
		receipt.ProductionActivation {
		return errors.New("consciousness user-turn receipt grants forbidden authority")
	}

	if receipt.Replayed {
		if receipt.WorldChanged || receipt.CognitionEventQueued || receipt.CognitionEventID != nil {
			return errors.New("consciousness replay receipt reports new admission")
		}
		return nil
	}

	if !receipt.WorldChanged || !receipt.CognitionEventQueued || receipt.CognitionEventID == nil {
		return errors.New("consciousness new-turn receipt is incomplete")
	}
	if !validConsciousnessEventID(*receipt.CognitionEventID) {
		return errors.New("consciousness cognition event id is invalid")
	}
	return nil
}

func validConsciousnessSHARef(value, prefix string) bool {
	if !strings.HasPrefix(value, prefix) || len(value) != len(prefix)+64 {
		return false
	}
	_, err := hex.DecodeString(value[len(prefix):])
	return err == nil
}

func validConsciousnessEventID(value string) bool {
	if !strings.HasPrefix(value, "cevt-") || len(value) != len("cevt-")+32 {
		return false
	}
	_, err := hex.DecodeString(value[len("cevt-"):])
	return err == nil
}
