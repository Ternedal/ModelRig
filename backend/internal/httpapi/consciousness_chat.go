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
	consciousnessStepPath                = "/experimental/consciousness/step"
	consciousnessTurnReceiptSchema       = "kaliv-consciousness-core/user-turn-admission/v1"
	consciousnessStepReceiptSchema       = "kaliv-consciousness-core/cognition-step-receipt/v1"
	consciousnessMaxChatProbeBytes       = 2 << 20
	consciousnessMaxUserTurnCharacters   = 2048
	consciousnessMaxRequestIDCharacters  = 128
	consciousnessMaxWorkerResponseBytes  = 64 << 10
	consciousnessAdmissionTimeout        = 2 * time.Second
	consciousnessCognitionTimeout        = 10 * time.Minute
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

type consciousnessStepRequest struct {
	RequiredEventID string `json:"required_event_id"`
}

type consciousnessStepReceipt struct {
	Schema                      string   `json:"schema"`
	RequiredEventID             string   `json:"required_event_id"`
	Decision                    string   `json:"decision"`
	SelectedEventIDs            []string `json:"selected_event_ids"`
	ThoughtEngineInvoked        bool     `json:"thought_engine_invoked"`
	ModelCalls                  int      `json:"model_calls"`
	ProfileRef                  string   `json:"profile_ref"`
	ProfileConfigRef            string   `json:"profile_config_ref"`
	SelfStateRef                string   `json:"self_state_ref"`
	WorldStateRef               string   `json:"world_state_ref"`
	WorkspaceRef                string   `json:"workspace_ref"`
	TransitionReceiptRef        *string  `json:"transition_receipt_ref"`
	CompletedCycles             int      `json:"completed_cycles"`
	ContextUpdated              bool     `json:"context_updated"`
	AutomaticRepeat             bool     `json:"automatic_repeat"`
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

	turnID, ok := consciousnessTurnID(r)
	if !ok || s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		s.handleMemory4Chat(w, r)
		return
	}

	// Secondary best-effort observation. There is deliberately no retry,
	// goroutine, queue or response mutation on failure.
	turnReceipt, _ := s.requestConsciousnessUserTurn(r, consciousnessUserTurnRequest{
		TurnID:    turnID,
		UserText:  userText,
		SourceRef: consciousnessBackendSourceRefPrefix + turnID,
	})
	if turnReceipt != nil &&
		os.Getenv(consciousnessTurnCognitionFlag) == "1" &&
		!turnReceipt.Replayed &&
		turnReceipt.CognitionEventID != nil {
		// Stronger opt-in: bind at most one private C22-C cognition step to the
		// exact newly admitted event. Failure remains secondary to normal chat.
		_ = s.requestConsciousnessStep(r, *turnReceipt.CognitionEventID)
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

func consciousnessTurnID(r *http.Request) (string, bool) {
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

func consciousnessTurnRef(turnID string) string {
	sum := sha256.Sum256([]byte(turnID))
	return "chat-turn:" + hex.EncodeToString(sum[:])
}

func (s *server) requestConsciousnessUserTurn(
	r *http.Request,
	payload consciousnessUserTurnRequest,
) (*consciousnessUserTurnReceipt, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(
		r.Context(),
		http.MethodPost,
		s.Worker.BaseURL+consciousnessUserTurnPath,
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Request-ID", payload.TurnID)

	resp, err := memory4WorkerHTTPClient(consciousnessAdmissionTimeout).Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return nil, errors.New("consciousness user-turn worker refused request")
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, consciousnessMaxWorkerResponseBytes+1))
	if err != nil {
		return nil, err
	}
	if len(raw) > consciousnessMaxWorkerResponseBytes {
		return nil, errors.New("consciousness user-turn response exceeds bound")
	}
	if err := requireConsciousnessTurnReceiptFields(raw); err != nil {
		return nil, err
	}

	var receipt consciousnessUserTurnReceipt
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&receipt); err != nil {
		return nil, err
	}
	if err := ensureMemory4JSONEOF(dec); err != nil {
		return nil, err
	}
	if err := validateConsciousnessTurnReceipt(receipt, payload.TurnID); err != nil {
		return nil, err
	}
	return &receipt, nil
}

func (s *server) requestConsciousnessStep(
	r *http.Request,
	requiredEventID string,
) error {
	if !validConsciousnessEventID(requiredEventID) {
		return errors.New("invalid required cognition event id")
	}
	body, err := json.Marshal(consciousnessStepRequest{
		RequiredEventID: requiredEventID,
	})
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(
		r.Context(),
		http.MethodPost,
		s.Worker.BaseURL+consciousnessStepPath,
		bytes.NewReader(body),
	)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if requestID, ok := consciousnessTurnID(r); ok {
		req.Header.Set("X-Request-ID", requestID)
	}

	resp, err := memory4WorkerHTTPClient(consciousnessCognitionTimeout).Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return errors.New("consciousness cognition worker refused request")
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, consciousnessMaxWorkerResponseBytes+1))
	if err != nil {
		return err
	}
	if len(raw) > consciousnessMaxWorkerResponseBytes {
		return errors.New("consciousness cognition response exceeds bound")
	}
	if err := requireConsciousnessStepReceiptFields(raw); err != nil {
		return err
	}

	var receipt consciousnessStepReceipt
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&receipt); err != nil {
		return err
	}
	if err := ensureMemory4JSONEOF(dec); err != nil {
		return err
	}
	return validateConsciousnessStepReceipt(receipt, requiredEventID)
}

func requireConsciousnessStepReceiptFields(raw []byte) error {
	var top map[string]json.RawMessage
	if err := json.Unmarshal(raw, &top); err != nil {
		return err
	}
	required := []string{
		"schema",
		"required_event_id",
		"decision",
		"selected_event_ids",
		"thought_engine_invoked",
		"model_calls",
		"profile_ref",
		"profile_config_ref",
		"self_state_ref",
		"world_state_ref",
		"workspace_ref",
		"transition_receipt_ref",
		"completed_cycles",
		"context_updated",
		"automatic_repeat",
		"self_state_store_write_applied",
		"durable_memory_write_authority",
		"execution_authority",
		"scheduling_authority",
		"production_activation",
	}
	if len(top) != len(required) {
		return errors.New("consciousness cognition receipt fields mismatch")
	}
	for _, name := range required {
		if _, ok := top[name]; !ok {
			return errors.New("consciousness cognition receipt missing required field")
		}
	}
	return nil
}

func validateConsciousnessStepReceipt(
	receipt consciousnessStepReceipt,
	requiredEventID string,
) error {
	if receipt.Schema != consciousnessStepReceiptSchema {
		return errors.New("consciousness cognition receipt schema mismatch")
	}
	if receipt.RequiredEventID != requiredEventID ||
		!validConsciousnessEventID(receipt.RequiredEventID) {
		return errors.New("consciousness cognition receipt event binding mismatch")
	}
	for _, eventID := range receipt.SelectedEventIDs {
		if !validConsciousnessEventID(eventID) {
			return errors.New("consciousness cognition selected event id is invalid")
		}
	}
	if !validConsciousnessSHARef(receipt.ProfileRef, "cognitive-profile:") ||
		!validConsciousnessSHARef(receipt.ProfileConfigRef, "cognitive-profile-config:") ||
		!validConsciousnessSHARef(receipt.SelfStateRef, "self-state:") ||
		!validConsciousnessSHARef(receipt.WorldStateRef, "world-state:") ||
		!validConsciousnessSHARef(receipt.WorkspaceRef, "workspace:") {
		return errors.New("consciousness cognition receipt contains invalid refs")
	}
	if receipt.CompletedCycles < 0 ||
		receipt.AutomaticRepeat ||
		receipt.SelfStateStoreWriteApplied ||
		receipt.DurableMemoryWriteAuthority ||
		receipt.ExecutionAuthority ||
		receipt.SchedulingAuthority ||
		receipt.ProductionActivation {
		return errors.New("consciousness cognition receipt grants forbidden authority")
	}

	switch receipt.Decision {
	case "WAIT":
		if receipt.ThoughtEngineInvoked ||
			receipt.ModelCalls != 0 ||
			receipt.ContextUpdated ||
			receipt.TransitionReceiptRef != nil {
			return errors.New("consciousness WAIT receipt reports a transition")
		}
	case "RUN":
		if !receipt.ThoughtEngineInvoked ||
			receipt.ModelCalls != 1 ||
			!receipt.ContextUpdated ||
			receipt.TransitionReceiptRef == nil {
			return errors.New("consciousness RUN receipt is incomplete")
		}
		if !validConsciousnessSHARef(
			*receipt.TransitionReceiptRef,
			"cognitive-transition-receipt:",
		) {
			return errors.New("consciousness transition receipt ref is invalid")
		}
		selected := false
		for _, eventID := range receipt.SelectedEventIDs {
			if eventID == requiredEventID {
				selected = true
				break
			}
		}
		if !selected {
			return errors.New("consciousness RUN receipt omitted required event")
		}
	default:
		return errors.New("consciousness cognition receipt decision is invalid")
	}
	return nil
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
