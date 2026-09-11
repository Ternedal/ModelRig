package httpapi

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	memory4ChatWriteFlag              = "KALIV_MEMORY4_CHAT_WRITE_ENABLED"
	memory4CompletedTurnWritePath     = "/experimental/memory4/commit-completed-turn"
	memory4TurnWriteReceiptSchema     = "kaliv-memory-completed-turn-write-receipt/v1"
	memory4MaxCompletedTurnCharacters = 16_000
	memory4MaxWriteResponseBytes      = 64 << 10
	memory4MaxObservedFrameBytes      = 256 << 10
	memory4MaxDurableIDBytes          = 100
)

type memory4CompletedTurnWriteRequest struct {
	UserText      string `json:"user_text"`
	AssistantText string `json:"assistant_text"`
	SourceRef     string `json:"source_ref"`
}

type memory4CompletedTurnWriteReceipt struct {
	Schema           string   `json:"schema"`
	CandidateCount   int      `json:"candidate_count"`
	ConsideredCount  int      `json:"considered_count"`
	CreatedCount     int      `json:"created_count"`
	SupersededCount  int      `json:"superseded_count"`
	DedupedCount     int      `json:"deduped_count"`
	SkippedCount     int      `json:"skipped_count"`
	CreatedIDs       []string `json:"created_ids"`
	SupersededIDs    []string `json:"superseded_ids"`
	SupersedingIDs   []string `json:"superseding_ids"`
	DedupedIDs       []string `json:"deduped_ids"`
	Replayed         bool     `json:"replayed"`
	SentToStore      bool     `json:"sent_to_store"`
}

type memory4OllamaChatFrame struct {
	Message *struct {
		Role    string `json:"role"`
		Content string `json:"content"`
	} `json:"message"`
	Done  *bool           `json:"done"`
	Error json.RawMessage `json:"error"`
}

// handleMemory4ChatWrite preserves the existing R05/read handler as the owner of
// model request semantics. It only probes the original bounded request to retain
// the current user text, then observes the already-streamed model response. The
// W04-A call happens synchronously after a valid terminal frame so there is no
// background authority, queue or retry path. Any memory failure is secondary and
// cannot rewrite an HTTP response that the chat path already emitted.
func (s *server) handleMemory4ChatWrite(w http.ResponseWriter, r *http.Request) {
	originalLength := r.ContentLength
	probe, err := io.ReadAll(io.LimitReader(r.Body, memory4MaxChatProbeBytes+1))
	if err != nil {
		memory4RestorePartialProbe(r, probe, originalLength)
		s.handleMemory4ChatRead(w, r)
		return
	}
	if len(probe) > memory4MaxChatProbeBytes {
		memory4RestorePartialProbe(r, probe, originalLength)
		s.handleMemory4ChatRead(w, r)
		return
	}

	userText, ok := memory4WriteUserForTurn(probe)
	restoreMemory4ChatBody(r, probe, originalLength)
	if !ok || s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		s.handleMemory4ChatRead(w, r)
		return
	}

	observer := newMemory4ChatWriteObserver(w)
	s.handleMemory4ChatRead(observer, r)
	assistantText, ok := observer.completedAssistant()
	if !ok {
		return
	}
	sourceRef, err := memory4NewChatSourceRef()
	if err != nil {
		return
	}
	_ = s.requestMemory4CompletedTurnWrite(
		r,
		memory4CompletedTurnWriteRequest{
			UserText:      userText,
			AssistantText: assistantText,
			SourceRef:     sourceRef,
		},
	)
}

func memory4RestorePartialProbe(r *http.Request, probe []byte, originalLength int64) {
	r.Body = io.NopCloser(io.MultiReader(bytes.NewReader(probe), r.Body))
	r.ContentLength = originalLength
}

func memory4WriteUserForTurn(raw []byte) (string, bool) {
	var probe memory4ChatProbe
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
	canonical := strings.TrimSpace(content)
	if canonical == "" || utf8.RuneCountInString(canonical) > memory4MaxCompletedTurnCharacters {
		return "", false
	}
	return canonical, true
}

func memory4NewChatSourceRef() (string, error) {
	var nonce [16]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return "", err
	}
	return "chat:" + hex.EncodeToString(nonce[:]), nil
}

type memory4ChatWriteObserver struct {
	dst            http.ResponseWriter
	status         int
	invalid        bool
	terminal       bool
	finalized      bool
	pending        []byte
	assistant      strings.Builder
	assistantRunes int
}

func newMemory4ChatWriteObserver(dst http.ResponseWriter) *memory4ChatWriteObserver {
	return &memory4ChatWriteObserver{dst: dst}
}

func (o *memory4ChatWriteObserver) Header() http.Header {
	return o.dst.Header()
}

func (o *memory4ChatWriteObserver) WriteHeader(status int) {
	if o.status == 0 {
		o.status = status
	}
	o.dst.WriteHeader(status)
}

func (o *memory4ChatWriteObserver) Write(p []byte) (int, error) {
	if o.status == 0 {
		o.status = http.StatusOK
	}
	n, err := o.dst.Write(p)
	if n > 0 {
		o.observe(p[:n])
	}
	if err != nil || n != len(p) {
		o.invalid = true
	}
	return n, err
}

func (o *memory4ChatWriteObserver) Flush() {
	if flusher, ok := o.dst.(http.Flusher); ok {
		flusher.Flush()
	}
}

func (o *memory4ChatWriteObserver) observe(data []byte) {
	if o.invalid || o.finalized {
		return
	}
	for len(data) > 0 {
		newline := bytes.IndexByte(data, '\n')
		if newline < 0 {
			o.appendPending(data)
			return
		}
		o.appendPending(data[:newline])
		if o.invalid {
			return
		}
		o.processFrame(o.pending)
		o.pending = o.pending[:0]
		if o.invalid {
			return
		}
		data = data[newline+1:]
	}
}

func (o *memory4ChatWriteObserver) appendPending(data []byte) {
	if len(o.pending)+len(data) > memory4MaxObservedFrameBytes {
		o.invalid = true
		o.pending = nil
		return
	}
	o.pending = append(o.pending, data...)
}

func (o *memory4ChatWriteObserver) processFrame(raw []byte) {
	line := bytes.TrimSpace(raw)
	if len(line) == 0 {
		return
	}
	if o.terminal || !utf8.Valid(line) {
		o.invalid = true
		return
	}
	var frame memory4OllamaChatFrame
	if err := json.Unmarshal(line, &frame); err != nil || frame.Done == nil {
		o.invalid = true
		return
	}
	if len(frame.Error) != 0 && !bytes.Equal(bytes.TrimSpace(frame.Error), []byte("null")) {
		o.invalid = true
		return
	}
	if frame.Message == nil {
		if !*frame.Done {
			o.invalid = true
			return
		}
	} else {
		if frame.Message.Role != "assistant" {
			o.invalid = true
			return
		}
		if frame.Message.Content != "" {
			added := utf8.RuneCountInString(frame.Message.Content)
			if o.assistantRunes+added > memory4MaxCompletedTurnCharacters {
				o.invalid = true
				return
			}
			o.assistant.WriteString(frame.Message.Content)
			o.assistantRunes += added
		}
	}
	if *frame.Done {
		o.terminal = true
	}
}

func (o *memory4ChatWriteObserver) completedAssistant() (string, bool) {
	if !o.finalized {
		o.finalized = true
		if !o.invalid && len(bytes.TrimSpace(o.pending)) != 0 {
			o.processFrame(o.pending)
		}
		o.pending = nil
	}
	if o.invalid || !o.terminal || o.status < 200 || o.status >= 300 {
		return "", false
	}
	assistant := strings.TrimSpace(o.assistant.String())
	if assistant == "" || utf8.RuneCountInString(assistant) > memory4MaxCompletedTurnCharacters {
		return "", false
	}
	return assistant, true
}

func (s *server) requestMemory4CompletedTurnWrite(
	r *http.Request,
	turn memory4CompletedTurnWriteRequest,
) error {
	if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		return errors.New("memory completed-turn write requires loopback worker")
	}
	payload, err := json.Marshal(turn)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(
		r.Context(),
		http.MethodPost,
		s.Worker.BaseURL+memory4CompletedTurnWritePath,
		bytes.NewReader(payload),
	)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if rid := r.Header.Get("X-Request-ID"); rid != "" {
		req.Header.Set("X-Request-ID", rid)
	}

	timeout := s.Cfg.RequestTimeout
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	resp, err := (&http.Client{Timeout: timeout}).Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		return errors.New("memory completed-turn write worker refused request")
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, memory4MaxWriteResponseBytes+1))
	if err != nil {
		return err
	}
	if len(body) > memory4MaxWriteResponseBytes {
		return errors.New("memory completed-turn write response exceeds bound")
	}
	if err := requireMemory4WriteReceiptFields(body); err != nil {
		return err
	}
	var receipt memory4CompletedTurnWriteReceipt
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&receipt); err != nil {
		return err
	}
	if err := ensureMemory4JSONEOF(dec); err != nil {
		return err
	}
	return validateMemory4WriteReceipt(receipt)
}

func requireMemory4WriteReceiptFields(raw []byte) error {
	var top map[string]json.RawMessage
	if err := json.Unmarshal(raw, &top); err != nil {
		return err
	}
	required := []string{
		"schema",
		"candidate_count",
		"considered_count",
		"created_count",
		"superseded_count",
		"deduped_count",
		"skipped_count",
		"created_ids",
		"superseded_ids",
		"superseding_ids",
		"deduped_ids",
		"replayed",
		"sent_to_store",
	}
	if len(top) != len(required) {
		return errors.New("memory completed-turn write receipt fields mismatch")
	}
	for _, name := range required {
		if _, ok := top[name]; !ok {
			return errors.New("memory completed-turn write receipt missing required field")
		}
	}
	return nil
}

func validateMemory4WriteReceipt(receipt memory4CompletedTurnWriteReceipt) error {
	if receipt.Schema != memory4TurnWriteReceiptSchema {
		return errors.New("memory completed-turn write receipt schema mismatch")
	}
	if receipt.CandidateCount < 0 || receipt.ConsideredCount < 0 ||
		receipt.CreatedCount < 0 || receipt.SupersededCount < 0 ||
		receipt.DedupedCount < 0 || receipt.SkippedCount < 0 {
		return errors.New("memory completed-turn write receipt has negative counts")
	}
	if receipt.CandidateCount != receipt.ConsideredCount ||
		receipt.CreatedCount != len(receipt.CreatedIDs) ||
		receipt.SupersededCount != len(receipt.SupersededIDs) ||
		receipt.SupersededCount != len(receipt.SupersedingIDs) ||
		receipt.DedupedCount != len(receipt.DedupedIDs) {
		return errors.New("memory completed-turn write receipt count mismatch")
	}
	if receipt.CreatedCount+receipt.DedupedCount+receipt.SkippedCount != receipt.CandidateCount {
		return errors.New("memory completed-turn write receipt action partition mismatch")
	}
	if receipt.SupersededCount > receipt.CreatedCount {
		return errors.New("memory completed-turn write receipt supersede count mismatch")
	}
	created, err := memory4ValidatedReceiptIDs(receipt.CreatedIDs)
	if err != nil {
		return err
	}
	superseded, err := memory4ValidatedReceiptIDs(receipt.SupersededIDs)
	if err != nil {
		return err
	}
	superseding, err := memory4ValidatedReceiptIDs(receipt.SupersedingIDs)
	if err != nil {
		return err
	}
	deduped, err := memory4ValidatedReceiptIDs(receipt.DedupedIDs)
	if err != nil {
		return err
	}
	for id := range superseding {
		if _, ok := created[id]; !ok {
			return errors.New("memory completed-turn write receipt superseding id is not created")
		}
	}
	if memory4IDSetOverlap(created, superseded) ||
		memory4IDSetOverlap(created, deduped) ||
		memory4IDSetOverlap(superseded, deduped) {
		return errors.New("memory completed-turn write receipt id roles overlap")
	}
	if receipt.Replayed && (receipt.CreatedCount != 0 || receipt.SupersededCount != 0) {
		return errors.New("memory completed-turn write replay receipt reports mutations")
	}
	if receipt.CandidateCount == 0 {
		if receipt.SentToStore || receipt.Replayed || receipt.SkippedCount != 0 ||
			len(created) != 0 || len(superseded) != 0 || len(superseding) != 0 || len(deduped) != 0 {
			return errors.New("memory completed-turn zero receipt is invalid")
		}
		return nil
	}
	if !receipt.SentToStore {
		return errors.New("memory completed-turn nonempty receipt did not reach store")
	}
	return nil
}

func memory4ValidatedReceiptIDs(ids []string) (map[string]struct{}, error) {
	seen := make(map[string]struct{}, len(ids))
	for _, id := range ids {
		if id == "" || strings.TrimSpace(id) != id || strings.ContainsRune(id, '\x00') || len(id) > memory4MaxDurableIDBytes {
			return nil, errors.New("memory completed-turn write receipt contains invalid id")
		}
		if _, exists := seen[id]; exists {
			return nil, errors.New("memory completed-turn write receipt contains duplicate id")
		}
		seen[id] = struct{}{}
	}
	return seen, nil
}

func memory4IDSetOverlap(left, right map[string]struct{}) bool {
	for id := range left {
		if _, ok := right[id]; ok {
			return true
		}
	}
	return false
}

func memory4ChatWriteEnabled() bool {
	return os.Getenv(memory4ChatWriteFlag) == "1"
}
