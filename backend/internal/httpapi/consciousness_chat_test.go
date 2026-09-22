package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
)

func consciousnessValidReceipt(turnID string, replayed bool) map[string]any {
	var eventID any = "cevt-" + strings.Repeat("a", 32)
	worldChanged := true
	queued := true
	if replayed {
		eventID = nil
		worldChanged = false
		queued = false
	}
	return map[string]any{
		"schema":                         consciousnessTurnReceiptSchema,
		"turn_ref":                       consciousnessTurnRef(turnID),
		"evidence_ref":                   "world-evidence-event:" + strings.Repeat("b", 64),
		"cognition_event_id":             eventID,
		"world_changed":                  worldChanged,
		"replayed":                       replayed,
		"cognition_event_queued":         queued,
		"epistemic_status":               "reported",
		"confidence":                     1.0,
		"observed_sequence":              1,
		"model_calls":                    0,
		"self_state_store_write_applied": false,
		"durable_memory_write_authority": false,
		"execution_authority":            false,
		"scheduling_authority":           false,
		"production_activation":          false,
	}
}

func consciousnessValidStepReceipt(eventID, decision string) map[string]any {
	var transition any = nil
	selected := []string{}
	thought := false
	modelCalls := 0
	contextUpdated := false
	completedCycles := 0
	if decision == "RUN" {
		transition = "cognitive-transition-receipt:" + strings.Repeat("f", 64)
		selected = []string{eventID}
		thought = true
		modelCalls = 1
		contextUpdated = true
		completedCycles = 1
	}
	return map[string]any{
		"schema":                         consciousnessStepReceiptSchema,
		"required_event_id":              eventID,
		"decision":                       decision,
		"selected_event_ids":             selected,
		"thought_engine_invoked":         thought,
		"model_calls":                    modelCalls,
		"profile_ref":                    "cognitive-profile:" + strings.Repeat("1", 64),
		"profile_config_ref":             "cognitive-profile-config:" + strings.Repeat("2", 64),
		"self_state_ref":                 "self-state:" + strings.Repeat("3", 64),
		"world_state_ref":                "world-state:" + strings.Repeat("4", 64),
		"workspace_ref":                  "workspace:" + strings.Repeat("5", 64),
		"transition_receipt_ref":         transition,
		"completed_cycles":               completedCycles,
		"context_updated":                contextUpdated,
		"automatic_repeat":               false,
		"self_state_store_write_applied": false,
		"durable_memory_write_authority": false,
		"execution_authority":            false,
		"scheduling_authority":           false,
		"production_activation":          false,
	}
}

func consciousnessRouteRequest(raw, requestID string) *http.Request {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/chat", strings.NewReader(raw))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+memory4TestToken)
	if requestID != "" {
		req.Header.Set("X-Request-ID", requestID)
	}
	return req
}

func TestConsciousnessChatFlagOffPreservesBaselineAndSkipsWorker(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "0")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer worker.Close()

	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	raw := "{\n  \"model\":\"qwen\", \"messages\":[{\"role\":\"user\",\"content\":\"hello\"}], \"stream\":true\n}"
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, "req-c21b-off"))

	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 0 {
		t.Fatalf("flag-off reached worker %d time(s)", workerHits.Load())
	}
	if modelBody != raw {
		t.Fatalf("flag-off model body changed:\n got: %q\nwant: %q", modelBody, raw)
	}
}

func TestConsciousnessChatEnabledSubmitsExactFinalUserAndPreservesModelBody(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "0")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const turnID = "req-c21b-exact"
	const userText = "  Jeg siger præcis dette.  "
	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		if r.URL.Path != consciousnessUserTurnPath {
			t.Errorf("worker path=%q", r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "" {
			t.Errorf("client bearer leaked to worker: %q", got)
		}
		if got := r.Header.Get("X-Request-ID"); got != turnID {
			t.Errorf("worker request id=%q want %q", got, turnID)
		}
		var got consciousnessUserTurnRequest
		dec := json.NewDecoder(r.Body)
		dec.DisallowUnknownFields()
		if err := dec.Decode(&got); err != nil {
			t.Errorf("decode worker request: %v", err)
		}
		if got.TurnID != turnID {
			t.Errorf("turn id=%q", got.TurnID)
		}
		if got.UserText != userText {
			t.Errorf("user text changed: got=%q want=%q", got.UserText, userText)
		}
		if got.SourceRef != consciousnessBackendSourceRefPrefix+turnID {
			t.Errorf("source ref=%q", got.SourceRef)
		}
		writeJSON(w, http.StatusOK, consciousnessValidReceipt(turnID, false))
	}))
	defer worker.Close()

	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"system","content":"be concise"},{"role":"user","content":"  Jeg siger præcis dette.  "}],"stream":true}`
	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, turnID))

	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 1 {
		t.Fatalf("worker hits=%d want 1", workerHits.Load())
	}
	if modelBody != raw {
		t.Fatalf("C21-B changed model body:\n got: %q\nwant: %q", modelBody, raw)
	}
}

func TestConsciousnessChatRestoresOriginalTurnBeforeMemory4Context(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "0")
	t.Setenv(memory4ChatFlag, "1")
	t.Setenv(memory4ChatWriteFlag, "0")

	const turnID = "req-c21b-memory4"
	const userText = " what do I like? "
	var consciousnessHits atomic.Int32
	var contextHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			consciousnessHits.Add(1)
			var got consciousnessUserTurnRequest
			if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
				t.Errorf("decode consciousness request: %v", err)
				return
			}
			if got.UserText != userText {
				t.Errorf("consciousness saw altered user text: got=%q want=%q", got.UserText, userText)
			}
			writeJSON(w, http.StatusOK, consciousnessValidReceipt(turnID, false))
		case memory4ContextPath:
			contextHits.Add(1)
			var got memory4ContextRequest
			if err := json.NewDecoder(r.Body).Decode(&got); err != nil {
				t.Errorf("decode memory context request: %v", err)
				return
			}
			if got.Query != "what do I like?" {
				t.Errorf("memory query=%q", got.Query)
			}
			context := "----- BEGIN KALIV MEMORY DATA -----\n{\"items\":[{\"value\":\"espresso\"}]}\n----- END KALIV MEMORY DATA -----"
			writeJSON(w, http.StatusOK, memory4ReceiptResponse(context, "local", 1, 1, []string{"memory-1"}))
		default:
			t.Errorf("unexpected worker path=%q", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	var modelBody []byte
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelBody, _ = io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"espresso\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"system","content":"be concise"},{"role":"user","content":" what do I like? "}],"stream":true}`
	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, turnID))

	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if consciousnessHits.Load() != 1 || contextHits.Load() != 1 {
		t.Fatalf("worker hits consciousness=%d context=%d want 1/1", consciousnessHits.Load(), contextHits.Load())
	}

	var got struct {
		Messages []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
	}
	if err := json.Unmarshal(modelBody, &got); err != nil {
		t.Fatalf("model body JSON: %v body=%s", err, string(modelBody))
	}
	if len(got.Messages) != 2 {
		t.Fatalf("model messages=%d want 2", len(got.Messages))
	}
	if !strings.Contains(got.Messages[1].Content, "espresso") ||
		!strings.Contains(got.Messages[1].Content, "what do I like?") {
		t.Fatalf("Memory 4 did not receive/restorably wrap original user turn: %q", got.Messages[1].Content)
	}
}

func TestConsciousnessChatBothFlagsRunRequiredStepBeforeNormalResponse(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const turnID = "req-c22d-run"
	eventID := "cevt-" + strings.Repeat("a", 32)
	var userTurnHits atomic.Int32
	var stepHits atomic.Int32
	var stepDone atomic.Bool
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "" {
			t.Errorf("client bearer leaked to consciousness worker: %q", got)
		}
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			userTurnHits.Add(1)
			receipt := consciousnessValidReceipt(turnID, false)
			receipt["cognition_event_id"] = eventID
			writeJSON(w, http.StatusOK, receipt)
		case consciousnessStepPath:
			stepHits.Add(1)
			var got consciousnessStepRequest
			dec := json.NewDecoder(r.Body)
			dec.DisallowUnknownFields()
			if err := dec.Decode(&got); err != nil {
				t.Errorf("decode cognition step: %v", err)
				return
			}
			if got.RequiredEventID != eventID {
				t.Errorf("step event=%q want %q", got.RequiredEventID, eventID)
			}
			if gotID := r.Header.Get("X-Request-ID"); gotID != turnID {
				t.Errorf("step request id=%q want %q", gotID, turnID)
			}
			stepDone.Store(true)
			writeJSON(w, http.StatusOK, consciousnessValidStepReceipt(eventID, "RUN"))
		default:
			t.Errorf("unexpected worker path=%q", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		if !stepDone.Load() {
			t.Error("normal chat model started before required cognition step completed")
		}
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	raw := `{"model":"qwen","messages":[{"role":"user","content":"think then answer"}],"stream":true}`
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, turnID))

	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if userTurnHits.Load() != 1 || stepHits.Load() != 1 || modelHits.Load() != 1 {
		t.Fatalf("hits user=%d step=%d model=%d want 1/1/1",
			userTurnHits.Load(), stepHits.Load(), modelHits.Load())
	}
}

func TestConsciousnessChatReplayDoesNotRunCognitionAgain(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const turnID = "req-c22d-replay"
	var userTurnHits atomic.Int32
	var stepHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			userTurnHits.Add(1)
			writeJSON(w, http.StatusOK, consciousnessValidReceipt(turnID, true))
		case consciousnessStepPath:
			stepHits.Add(1)
			w.WriteHeader(http.StatusInternalServerError)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	raw := `{"model":"qwen","messages":[{"role":"user","content":"same turn"}],"stream":true}`
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, turnID))

	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if userTurnHits.Load() != 1 || stepHits.Load() != 0 {
		t.Fatalf("hits user=%d step=%d want 1/0", userTurnHits.Load(), stepHits.Load())
	}
}

func TestConsciousnessChatAcceptsWaitWithoutBlockingNormalResponse(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const turnID = "req-c22d-wait"
	eventID := "cevt-" + strings.Repeat("b", 32)
	var stepHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			receipt := consciousnessValidReceipt(turnID, false)
			receipt["cognition_event_id"] = eventID
			writeJSON(w, http.StatusOK, receipt)
		case consciousnessStepPath:
			stepHits.Add(1)
			writeJSON(w, http.StatusOK, consciousnessValidStepReceipt(eventID, "WAIT"))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	raw := `{"model":"qwen","messages":[{"role":"user","content":"paced turn"}],"stream":true}`
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, turnID))

	if rec.Code != http.StatusOK || stepHits.Load() != 1 || modelHits.Load() != 1 {
		t.Fatalf("WAIT changed normal chat: status=%d step=%d model=%d body=%s",
			rec.Code, stepHits.Load(), modelHits.Load(), rec.Body.String())
	}
}

func TestConsciousnessChatCognitionFailureIsSecondaryToNormalResponse(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const turnID = "req-c22d-step-failure"
	eventID := "cevt-" + strings.Repeat("c", 32)
	var stepHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			receipt := consciousnessValidReceipt(turnID, false)
			receipt["cognition_event_id"] = eventID
			writeJSON(w, http.StatusOK, receipt)
		case consciousnessStepPath:
			stepHits.Add(1)
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"detail": "profile unavailable"})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"normal response\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	raw := `{"model":"qwen","messages":[{"role":"user","content":"still answer me"}],"stream":true}`
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, turnID))

	if rec.Code != http.StatusOK || stepHits.Load() != 1 || modelHits.Load() != 1 {
		t.Fatalf("cognition failure changed normal chat: status=%d step=%d model=%d body=%s",
			rec.Code, stepHits.Load(), modelHits.Load(), rec.Body.String())
	}
}

func TestConsciousnessChatTamperedCognitionReceiptIsSecondary(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const turnID = "req-c22d-tampered-step"
	eventID := "cevt-" + strings.Repeat("d", 32)
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			receipt := consciousnessValidReceipt(turnID, false)
			receipt["cognition_event_id"] = eventID
			writeJSON(w, http.StatusOK, receipt)
		case consciousnessStepPath:
			bad := consciousnessValidStepReceipt(eventID, "RUN")
			bad["execution_authority"] = true
			writeJSON(w, http.StatusOK, bad)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	raw := `{"model":"qwen","messages":[{"role":"user","content":"tampered step"}],"stream":true}`
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, turnID))
	if rec.Code != http.StatusOK || modelHits.Load() != 1 {
		t.Fatalf("tampered cognition receipt changed normal chat: status=%d model=%d body=%s",
			rec.Code, modelHits.Load(), rec.Body.String())
	}
}

func TestValidateConsciousnessStepReceiptShapes(t *testing.T) {
	eventID := "cevt-" + strings.Repeat("e", 32)
	for _, decision := range []string{"WAIT", "RUN"} {
		raw, err := json.Marshal(consciousnessValidStepReceipt(eventID, decision))
		if err != nil {
			t.Fatal(err)
		}
		if err := requireConsciousnessStepReceiptFields(raw); err != nil {
			t.Fatalf("%s required fields: %v", decision, err)
		}
		var receipt consciousnessStepReceipt
		if err := json.Unmarshal(raw, &receipt); err != nil {
			t.Fatal(err)
		}
		if err := validateConsciousnessStepReceipt(receipt, eventID); err != nil {
			t.Fatalf("valid %s receipt rejected: %v", decision, err)
		}
	}

	bad := consciousnessValidStepReceipt(eventID, "RUN")
	bad["selected_event_ids"] = []string{"cevt-" + strings.Repeat("f", 32)}
	raw, _ := json.Marshal(bad)
	var receipt consciousnessStepReceipt
	_ = json.Unmarshal(raw, &receipt)
	if err := validateConsciousnessStepReceipt(receipt, eventID); err == nil {
		t.Fatal("RUN receipt omitting required event was accepted")
	}
}

func TestConsciousnessChatWorkerFailureIsSecondaryToNormalChat(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "no session"})
	}))
	defer worker.Close()

	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"still works\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	raw := `{"model":"qwen","messages":[{"role":"user","content":"hello"}],"stream":true}`
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, "req-c21b-failure"))

	if rec.Code != http.StatusOK {
		t.Fatalf("chat failed because consciousness worker failed: %d body=%s", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 1 || modelHits.Load() != 1 {
		t.Fatalf("hits worker=%d model=%d want 1/1", workerHits.Load(), modelHits.Load())
	}
}

func TestConsciousnessChatTamperedReceiptDoesNotRewriteChat(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const turnID = "req-c21b-tampered"
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		bad := consciousnessValidReceipt(turnID, false)
		bad["execution_authority"] = true
		writeJSON(w, http.StatusOK, bad)
	}))
	defer worker.Close()

	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	raw := `{"model":"qwen","messages":[{"role":"user","content":"hello"}],"stream":true}`
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, turnID))
	if rec.Code != http.StatusOK || modelHits.Load() != 1 {
		t.Fatalf("tampered secondary receipt changed chat: status=%d modelHits=%d body=%s", rec.Code, modelHits.Load(), rec.Body.String())
	}
}

func TestConsciousnessChatDoesNotFollowWorkerRedirect(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	var externalHits atomic.Int32
	external := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		externalHits.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer external.Close()

	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		http.Redirect(w, r, external.URL+"/stolen", http.StatusTemporaryRedirect)
	}))
	defer worker.Close()

	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	raw := `{"model":"qwen","messages":[{"role":"user","content":"private redirect sentinel"}],"stream":true}`
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, "req-c21b-redirect"))

	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if workerHits.Load() != 1 {
		t.Fatalf("worker hits=%d want 1", workerHits.Load())
	}
	if externalHits.Load() != 0 {
		t.Fatalf("private user turn followed redirect %d time(s)", externalHits.Load())
	}
}

func TestConsciousnessChatSkipsUnsupportedTurnShapesAndUnboundedRequestID(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	var workerHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		workerHits.Add(1)
		writeJSON(w, http.StatusOK, consciousnessValidReceipt("unused", false))
	}))
	defer worker.Close()

	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	cases := []struct {
		name string
		raw  string
		rid  string
	}{
		{
			name: "last message is assistant",
			raw:  `{"model":"qwen","messages":[{"role":"assistant","content":"not a user turn"}],"stream":true}`,
			rid:  "req-assistant",
		},
		{
			name: "multimodal non-string content",
			raw:  `{"model":"qwen","messages":[{"role":"user","content":[{"type":"text","text":"hello"}]}],"stream":true}`,
			rid:  "req-multimodal",
		},
		{
			name: "too long user text",
			raw:  `{"model":"qwen","messages":[{"role":"user","content":"` + strings.Repeat("x", consciousnessMaxUserTurnCharacters+1) + `"}],"stream":true}`,
			rid:  "req-too-long",
		},
		{
			name: "unbounded request id",
			raw:  `{"model":"qwen","messages":[{"role":"user","content":"hello"}],"stream":true}`,
			rid:  strings.Repeat("r", consciousnessMaxRequestIDCharacters+1),
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, consciousnessRouteRequest(tc.raw, tc.rid))
			if rec.Code != http.StatusOK {
				t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
			}
		})
	}
	if workerHits.Load() != 0 {
		t.Fatalf("unsupported turns reached consciousness worker %d time(s)", workerHits.Load())
	}
}

func TestValidateConsciousnessReplayReceipt(t *testing.T) {
	const turnID = "req-c21b-replay"
	raw, err := json.Marshal(consciousnessValidReceipt(turnID, true))
	if err != nil {
		t.Fatal(err)
	}
	if err := requireConsciousnessTurnReceiptFields(raw); err != nil {
		t.Fatalf("required fields rejected valid replay: %v", err)
	}
	var receipt consciousnessUserTurnReceipt
	if err := json.Unmarshal(raw, &receipt); err != nil {
		t.Fatal(err)
	}
	if err := validateConsciousnessTurnReceipt(receipt, turnID); err != nil {
		t.Fatalf("valid replay receipt rejected: %v", err)
	}

	bad := receipt
	bad.WorldChanged = true
	if err := validateConsciousnessTurnReceipt(bad, turnID); err == nil {
		t.Fatal("replay receipt claiming world change was accepted")
	}
}
