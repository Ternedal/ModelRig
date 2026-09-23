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
	consciousnessUserTurnPath            = "/experimental/consciousness/user-turn"
	consciousnessTurnReceiptSchema       = "kaliv-consciousness-core/user-turn-admission/v1"
	consciousnessMaxChatProbeBytes       = 2 << 20
	consciousnessMaxUserTurnCharacters   = 2048
	consciousnessMaxRequestIDCharacters  = 128
	consciousnessMaxWorkerResponseBytes  = 64 << 10
	consciousnessAdmissionTimeout        = 2 * time.Second
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
	_ = s.requestConsciousnessUserTurn(r, consciousnessUserTurnRequest{
		TurnID:    turnID,
		UserText:  userText,
		SourceRef: consciousnessBackendSourceRefPrefix + turnID,
	})
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
) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(
		r.Context(),
		http.MethodPost,
		s.Worker.BaseURL+consciousnessUserTurnPath,
		bytes.NewReader(body),
	)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if traceID := strings.TrimSpace(r.Header.Get("X-Request-ID")); traceID != "" {
		req.Header.Set("X-Request-ID", traceID)
	}

	resp, err := memory4WorkerHTTPClient(consciousnessAdmissionTimeout).Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return errors.New("consciousness user-turn worker refused request")
	}

	raw, err := io.ReadAll(io.LimitReader(resp.Body, consciousnessMaxWorkerResponseBytes+1))
	if err != nil {
		return err
	}
	if len(raw) > consciousnessMaxWorkerResponseBytes {
		return errors.New("consciousness user-turn response exceeds bound")
	}
	if err := requireConsciousnessTurnReceiptFields(raw); err != nil {
		return err
	}

	var receipt consciousnessUserTurnReceipt
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&receipt); err != nil {
		return err
	}
	if err := ensureMemory4JSONEOF(dec); err != nil {
		return err
	}
	return validateConsciousnessTurnReceipt(receipt, payload.TurnID)
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
