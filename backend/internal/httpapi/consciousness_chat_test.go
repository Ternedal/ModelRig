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
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const requestID = "req-c21b-exact"
	turnID := consciousnessBoundTurnID("memory4-device", requestID)
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
		if got := r.Header.Get("X-Request-ID"); got != requestID {
			t.Errorf("worker request id=%q want %q", got, requestID)
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
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, requestID))

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
	t.Setenv(memory4ChatFlag, "1")
	t.Setenv(memory4ChatWriteFlag, "0")

	const requestID = "req-c21b-memory4"
	turnID := consciousnessBoundTurnID("memory4-device", requestID)
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
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, requestID))

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

	const requestID = "req-c21b-tampered"
	turnID := consciousnessBoundTurnID("memory4-device", requestID)
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
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, requestID))
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

func TestConsciousnessBoundTurnIDSeparatesDevicesAndPreservesRetryIdentity(t *testing.T) {
	const requestID = "req-shared-client-id"
	a1 := consciousnessBoundTurnID("device-a", requestID)
	a2 := consciousnessBoundTurnID("device-a", requestID)
	b := consciousnessBoundTurnID("device-b", requestID)
	if a1 != a2 {
		t.Fatal("same authenticated device/request pair did not produce stable turn id")
	}
	if a1 == b {
		t.Fatal("different authenticated devices collided on the same turn id")
	}
	if !strings.HasPrefix(a1, "chat-") || len(a1) != len("chat-")+64 {
		t.Fatalf("unexpected bound turn id shape: %q", a1)
	}
}

func TestValidateConsciousnessReplayReceipt(t *testing.T) {
	const requestID = "req-c21b-replay"
	turnID := consciousnessBoundTurnID("memory4-device", requestID)
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

func consciousnessValidExactEventReceipt(eventID string, decision string) map[string]any {
	selected := []string{}
	requiredSelected := false
	invoked := false
	modelCalls := 0
	contextUpdated := false
	var transition any
	completed := 0
	if decision == "RUN" {
		selected = []string{eventID}
		requiredSelected = true
		invoked = true
		modelCalls = 1
		contextUpdated = true
		transition = "cognitive-transition-receipt:" + strings.Repeat("c", 64)
		completed = 1
	}
	return map[string]any{
		"schema":                         consciousnessExactEventReceiptSchema,
		"required_event_id":              eventID,
		"decision":                       decision,
		"selected_event_ids":             selected,
		"required_event_selected":        requiredSelected,
		"thought_engine_invoked":         invoked,
		"model_calls":                    modelCalls,
		"profile_ref":                    "cognitive-profile:" + strings.Repeat("d", 64),
		"profile_id":                     "cog-" + strings.Repeat("e", 32),
		"profile_config_sha256":          strings.Repeat("f", 64),
		"self_state_ref":                 "self-state:" + strings.Repeat("1", 64),
		"world_state_ref":                "world-state:" + strings.Repeat("2", 64),
		"workspace_ref":                  "workspace:" + strings.Repeat("3", 64),
		"transition_receipt_ref":         transition,
		"completed_cycles":               completed,
		"context_updated":                contextUpdated,
		"automatic_repeat":               false,
		"internal_thread_created":        false,
		"internal_timer_created":         false,
		"self_state_store_write_applied": false,
		"durable_memory_write_authority": false,
		"execution_authority":            false,
		"scheduling_authority":           false,
		"production_activation":          false,
	}
}

func TestConsciousnessTurnCognitionFlagOffKeepsAdmissionOnly(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "0")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const requestID = "req-c22d-off"
	turnID := consciousnessBoundTurnID("memory4-device", requestID)
	var admissionHits atomic.Int32
	var cognitionHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			admissionHits.Add(1)
			writeJSON(w, http.StatusOK, consciousnessValidReceipt(turnID, false))
		case consciousnessExactEventStepPath:
			cognitionHits.Add(1)
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
	raw := `{"model":"qwen","messages":[{"role":"user","content":"hello"}],"stream":true}`
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, requestID))

	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if admissionHits.Load() != 1 {
		t.Fatalf("admission hits=%d want 1", admissionHits.Load())
	}
	if cognitionHits.Load() != 0 {
		t.Fatalf("turn-cognition flag off produced %d cognition hit(s)", cognitionHits.Load())
	}
}

func TestConsciousnessTurnCognitionRunsExactNewEventBeforeNormalChat(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const requestID = "req-c22d-run"
	turnID := consciousnessBoundTurnID("memory4-device", requestID)
	eventID := "cevt-" + strings.Repeat("a", 32)
	var admissionHits atomic.Int32
	var cognitionHits atomic.Int32
	var cognitionDone atomic.Bool

	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			admissionHits.Add(1)
			receipt := consciousnessValidReceipt(turnID, false)
			receipt["cognition_event_id"] = eventID
			writeJSON(w, http.StatusOK, receipt)
		case consciousnessExactEventStepPath:
			cognitionHits.Add(1)
			if got := r.Header.Get("Authorization"); got != "" {
				t.Errorf("client bearer leaked to exact-event worker: %q", got)
			}
			if got := r.Header.Get("X-Request-ID"); got != requestID {
				t.Errorf("step request id=%q want %q", got, requestID)
			}
			var got consciousnessExactEventStepRequest
			dec := json.NewDecoder(r.Body)
			dec.DisallowUnknownFields()
			if err := dec.Decode(&got); err != nil {
				t.Errorf("decode exact-event request: %v", err)
			}
			if got.RequiredEventID != eventID {
				t.Errorf("required event=%q want %q", got.RequiredEventID, eventID)
			}
			cognitionDone.Store(true)
			writeJSON(w, http.StatusOK, consciousnessValidExactEventReceipt(eventID, "RUN"))
		default:
			t.Errorf("unexpected worker path=%q", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !cognitionDone.Load() {
			t.Error("normal chat model ran before synchronous exact-event cognition attempt")
		}
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	raw := `{"model":"qwen","messages":[{"role":"system","content":"be concise"},{"role":"user","content":"continue"}],"stream":true}`
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, requestID))

	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if admissionHits.Load() != 1 || cognitionHits.Load() != 1 {
		t.Fatalf("worker hits admission=%d cognition=%d want 1/1", admissionHits.Load(), cognitionHits.Load())
	}
	if modelBody != raw {
		t.Fatalf("C22-D changed normal chat body:\n got: %q\nwant: %q", modelBody, raw)
	}
}

func TestConsciousnessTurnCognitionReplayNeverSteps(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const requestID = "req-c22d-replay"
	turnID := consciousnessBoundTurnID("memory4-device", requestID)
	var cognitionHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			writeJSON(w, http.StatusOK, consciousnessValidReceipt(turnID, true))
		case consciousnessExactEventStepPath:
			cognitionHits.Add(1)
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
	raw := `{"model":"qwen","messages":[{"role":"user","content":"replay"}],"stream":true}`
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, requestID))
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if cognitionHits.Load() != 0 {
		t.Fatalf("replay produced %d cognition hit(s)", cognitionHits.Load())
	}
}

func TestConsciousnessTurnCognitionFailureIsIsolatedAndNeverRetried(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const requestID = "req-c22d-failure"
	turnID := consciousnessBoundTurnID("memory4-device", requestID)
	eventID := "cevt-" + strings.Repeat("a", 32)
	var cognitionHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			receipt := consciousnessValidReceipt(turnID, false)
			receipt["cognition_event_id"] = eventID
			writeJSON(w, http.StatusOK, receipt)
		case consciousnessExactEventStepPath:
			cognitionHits.Add(1)
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{
				"detail": "PRIVATE-WORKER-FAILURE",
			})
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	var modelHits atomic.Int32
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelHits.Add(1)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"normal-chat-ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	raw := `{"model":"qwen","messages":[{"role":"user","content":"still answer"}],"stream":true}`
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, requestID))
	if rec.Code != http.StatusOK {
		t.Fatalf("cognition failure broke normal chat: status=%d body=%s", rec.Code, rec.Body.String())
	}
	if cognitionHits.Load() != 1 {
		t.Fatalf("cognition attempts=%d want exactly 1", cognitionHits.Load())
	}
	if modelHits.Load() != 1 {
		t.Fatalf("normal chat model calls=%d want 1", modelHits.Load())
	}
	if strings.Contains(rec.Body.String(), "PRIVATE-WORKER-FAILURE") {
		t.Fatal("private cognition failure leaked into normal chat response")
	}
}

func TestValidateConsciousnessExactEventReceiptsFailClosed(t *testing.T) {
	eventID := "cevt-" + strings.Repeat("a", 32)

	for _, decision := range []string{"WAIT", "RUN"} {
		raw, err := json.Marshal(consciousnessValidExactEventReceipt(eventID, decision))
		if err != nil {
			t.Fatal(err)
		}
		if err := requireConsciousnessExactEventReceiptFields(raw); err != nil {
			t.Fatalf("%s required fields rejected: %v", decision, err)
		}
		var receipt consciousnessExactEventStepReceipt
		if err := json.Unmarshal(raw, &receipt); err != nil {
			t.Fatal(err)
		}
		if err := validateConsciousnessExactEventReceipt(receipt, eventID); err != nil {
			t.Fatalf("valid %s receipt rejected: %v", decision, err)
		}
	}

	run := consciousnessValidExactEventReceipt(eventID, "RUN")
	run["execution_authority"] = true
	raw, _ := json.Marshal(run)
	var authority consciousnessExactEventStepReceipt
	_ = json.Unmarshal(raw, &authority)
	if err := validateConsciousnessExactEventReceipt(authority, eventID); err == nil {
		t.Fatal("RUN receipt granting execution authority was accepted")
	}

	wait := consciousnessValidExactEventReceipt(eventID, "WAIT")
	wait["model_calls"] = 1
	wait["thought_engine_invoked"] = true
	raw, _ = json.Marshal(wait)
	var invalidWait consciousnessExactEventStepReceipt
	_ = json.Unmarshal(raw, &invalidWait)
	if err := validateConsciousnessExactEventReceipt(invalidWait, eventID); err == nil {
		t.Fatal("WAIT receipt claiming model invocation was accepted")
	}

	mismatch := consciousnessValidExactEventReceipt(eventID, "RUN")
	mismatch["required_event_id"] = "cevt-" + strings.Repeat("b", 32)
	raw, _ = json.Marshal(mismatch)
	var invalidBinding consciousnessExactEventStepReceipt
	_ = json.Unmarshal(raw, &invalidBinding)
	if err := validateConsciousnessExactEventReceipt(invalidBinding, eventID); err == nil {
		t.Fatal("receipt bound to another event was accepted")
	}
}

