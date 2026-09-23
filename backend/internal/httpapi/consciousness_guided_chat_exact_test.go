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

const c24ExactEventID = "cevt-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

func c24ExactGuidanceReceipt(eventID, guidance string) map[string]any {
	return map[string]any{
		"schema":                         consciousnessGuidanceReceiptSchema,
		"guidance_ref":                   "response-guidance:" + strings.Repeat("1", 64),
		"guidance_id":                    "rguid-" + strings.Repeat("2", 32),
		"user_turn_event_id":             eventID,
		"cycle_id":                       "cycle-" + strings.Repeat("3", 32),
		"proposal_ref":                   "thought-proposal:" + strings.Repeat("4", 64),
		"cognitive_profile_ref":          "cognitive-profile:" + strings.Repeat("5", 64),
		"person_revision":                "person-r0007",
		"self_revision":                  42,
		"text":                           guidance,
		"source_field":                   "thought-proposal.response_intent",
		"contains_only_response_intent":  true,
		"raw_chain_of_thought_included":  false,
		"consumed":                       true,
		"model_calls":                    0,
		"self_state_store_write_applied": false,
		"durable_memory_write_authority": false,
		"execution_authority":            false,
		"scheduling_authority":           false,
		"automatic_repeat":               false,
		"production_activation":          false,
	}
}

func c24ExactWorker(
	t *testing.T,
	guidance string,
	stepMutate func(map[string]any),
	guidanceMutate func(map[string]any),
) (*httptest.Server, *atomic.Int32, *atomic.Int32, *atomic.Int32) {
	t.Helper()
	var turnHits atomic.Int32
	var stepHits atomic.Int32
	var guidanceHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "" {
			t.Errorf("bearer leaked to worker path=%s: %q", r.URL.Path, got)
		}
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			turnHits.Add(1)
			var req consciousnessUserTurnRequest
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Errorf("decode user-turn: %v", err)
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			resp := consciousnessValidReceipt(req.TurnID, false)
			resp["cognition_event_id"] = c24ExactEventID
			writeJSON(w, http.StatusOK, resp)
		case consciousnessExactEventStepPath:
			stepHits.Add(1)
			var req consciousnessExactEventStepRequest
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Errorf("decode exact step: %v", err)
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			if req.RequiredEventID != c24ExactEventID {
				t.Errorf("required event=%q want %q", req.RequiredEventID, c24ExactEventID)
			}
			resp := consciousnessValidExactEventReceipt(c24ExactEventID, "RUN")
			if stepMutate != nil {
				stepMutate(resp)
			}
			writeJSON(w, http.StatusOK, resp)
		case consciousnessGuidanceConsumePath:
			guidanceHits.Add(1)
			var req consciousnessGuidanceConsumeRequest
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Errorf("decode guidance consume: %v", err)
				w.WriteHeader(http.StatusBadRequest)
				return
			}
			if req.UserTurnEventID != c24ExactEventID {
				t.Errorf("guidance event=%q want %q", req.UserTurnEventID, c24ExactEventID)
			}
			resp := c24ExactGuidanceReceipt(c24ExactEventID, guidance)
			if guidanceMutate != nil {
				guidanceMutate(resp)
			}
			writeJSON(w, http.StatusOK, resp)
		default:
			t.Errorf("unexpected worker path %q", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	return worker, &turnHits, &stepHits, &guidanceHits
}

func TestC24ExactGuidanceFlagOffKeepsC22DWithoutPromptRewrite(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(consciousnessReplyGuidanceFlag, "0")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	worker, turnHits, stepHits, guidanceHits := c24ExactWorker(t, "unused", nil, nil)
	defer worker.Close()

	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"user","content":"baseline exact"}],"stream":true}`
	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, "req-c24-exact-off"))

	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if turnHits.Load() != 1 || stepHits.Load() != 1 || guidanceHits.Load() != 0 {
		t.Fatalf("hits turn/step/guidance=%d/%d/%d want 1/1/0", turnHits.Load(), stepHits.Load(), guidanceHits.Load())
	}
	if modelBody != raw {
		t.Fatalf("reply-guidance flag off changed model body: got=%q want=%q", modelBody, raw)
	}
}

func TestC24ExactGuidanceShapesSameTurnReplyOnlyAfterExactRun(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(consciousnessReplyGuidanceFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	const guidance = "Svar kort, varmt og med fokus på brugerens konkrete spørgsmål."
	worker, turnHits, stepHits, guidanceHits := c24ExactWorker(t, guidance, nil, nil)
	defer worker.Close()

	var modelBody []byte
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelBody, _ = io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"system","content":"existing system"},{"role":"user","content":"  exact user text  "}],"stream":true}`
	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, "req-c24-exact-run"))
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if turnHits.Load() != 1 || stepHits.Load() != 1 || guidanceHits.Load() != 1 {
		t.Fatalf("hits turn/step/guidance=%d/%d/%d want 1/1/1", turnHits.Load(), stepHits.Load(), guidanceHits.Load())
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
	if len(got.Messages) != 3 {
		t.Fatalf("messages=%d want 3: %s", len(got.Messages), string(modelBody))
	}
	if got.Messages[0].Role != "system" || got.Messages[0].Content != "existing system" {
		t.Fatalf("existing system changed: %+v", got.Messages[0])
	}
	if got.Messages[1].Role != "system" ||
		!strings.Contains(got.Messages[1].Content, consciousnessGuidanceBegin) ||
		!strings.Contains(got.Messages[1].Content, guidance) ||
		!strings.Contains(got.Messages[1].Content, "not evidence of facts") ||
		!strings.Contains(got.Messages[1].Content, "not") {
		t.Fatalf("guidance system message malformed: %q", got.Messages[1].Content)
	}
	if got.Messages[2].Role != "user" || got.Messages[2].Content != "  exact user text  " {
		t.Fatalf("final user turn changed: %+v", got.Messages[2])
	}
	if strings.Contains(string(modelBody), "thought-proposal.response_intent") {
		t.Fatal("provenance metadata was unnecessarily injected into prompt")
	}
}

func TestC24ExactWaitFallsBackAndDoesNotConsumeGuidance(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(consciousnessReplyGuidanceFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	worker, _, _, guidanceHits := c24ExactWorker(t, "unused", func(step map[string]any) {
		step["decision"] = "WAIT"
		step["selected_event_ids"] = []string{}
		step["required_event_selected"] = false
		step["thought_engine_invoked"] = false
		step["model_calls"] = 0
		step["context_updated"] = false
		step["transition_receipt_ref"] = nil
	}, nil)
	defer worker.Close()

	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"user","content":"paced"}],"stream":true}`
	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, "req-c24-exact-wait"))
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d", rec.Code)
	}
	if guidanceHits.Load() != 0 {
		t.Fatalf("WAIT consumed guidance %d time(s)", guidanceHits.Load())
	}
	if modelBody != raw {
		t.Fatalf("WAIT fallback changed body: got=%q want=%q", modelBody, raw)
	}
}

func TestC24ExactTamperedGuidanceFallsBackToOriginalBody(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(consciousnessReplyGuidanceFlag, "1")
	t.Setenv(memory4ChatFlag, "0")
	t.Setenv(memory4ChatWriteFlag, "0")

	worker, _, _, _ := c24ExactWorker(t, "malicious", nil, func(g map[string]any) {
		g["execution_authority"] = true
	})
	defer worker.Close()

	var modelBody string
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		modelBody = string(body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"user","content":"tamper"}],"stream":true}`
	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, "req-c24-exact-tamper"))
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d", rec.Code)
	}
	if modelBody != raw {
		t.Fatalf("tampered guidance reached model: %s", modelBody)
	}
}

func TestC24ExactGuidanceSurvivesMemory4AndMemoryStillWrapsFinalUser(t *testing.T) {
	t.Setenv(consciousnessChatFlag, "1")
	t.Setenv(consciousnessTurnCognitionFlag, "1")
	t.Setenv(consciousnessReplyGuidanceFlag, "1")
	t.Setenv(memory4ChatFlag, "1")
	t.Setenv(memory4ChatWriteFlag, "0")

	const guidance = "Svar med fokus på den relevante hukommelse."
	var turnHits, stepHits, guidanceHits, memoryHits atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case consciousnessUserTurnPath:
			turnHits.Add(1)
			var req consciousnessUserTurnRequest
			_ = json.NewDecoder(r.Body).Decode(&req)
			resp := consciousnessValidReceipt(req.TurnID, false)
			resp["cognition_event_id"] = c24ExactEventID
			writeJSON(w, http.StatusOK, resp)
		case consciousnessExactEventStepPath:
			stepHits.Add(1)
			writeJSON(w, http.StatusOK, consciousnessValidExactEventReceipt(c24ExactEventID, "RUN"))
		case consciousnessGuidanceConsumePath:
			guidanceHits.Add(1)
			writeJSON(w, http.StatusOK, c24ExactGuidanceReceipt(c24ExactEventID, guidance))
		case memory4ContextPath:
			memoryHits.Add(1)
			context := "----- BEGIN KALIV MEMORY DATA -----\n{\"items\":[{\"value\":\"espresso\"}]}\n----- END KALIV MEMORY DATA -----"
			writeJSON(w, http.StatusOK, memory4ReceiptResponse(context, "local", 1, 1, []string{"m1"}))
		default:
			t.Errorf("unexpected worker path %q", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer worker.Close()

	var modelBody []byte
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelBody, _ = io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = w.Write([]byte("{\"message\":{\"role\":\"assistant\",\"content\":\"ok\"},\"done\":true}\n"))
	}))
	defer ollama.Close()

	raw := `{"model":"qwen","messages":[{"role":"user","content":"Hvad kan jeg lide?"}],"stream":true}`
	handler := memory4RouteHandler(t, worker.URL, ollama.URL)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, consciousnessRouteRequest(raw, "req-c24-exact-memory"))
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if turnHits.Load() != 1 || stepHits.Load() != 1 || guidanceHits.Load() != 1 || memoryHits.Load() != 1 {
		t.Fatalf("hits turn/step/guidance/memory=%d/%d/%d/%d", turnHits.Load(), stepHits.Load(), guidanceHits.Load(), memoryHits.Load())
	}
	var got struct {
		Messages []struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"messages"`
	}
	if err := json.Unmarshal(modelBody, &got); err != nil {
		t.Fatalf("model body: %v %s", err, string(modelBody))
	}
	if len(got.Messages) != 2 {
		t.Fatalf("messages=%d want guidance system + user", len(got.Messages))
	}
	if got.Messages[0].Role != "system" || !strings.Contains(got.Messages[0].Content, guidance) {
		t.Fatalf("guidance missing after Memory4: %+v", got.Messages[0])
	}
	if got.Messages[1].Role != "user" ||
		!strings.Contains(got.Messages[1].Content, "espresso") ||
		!strings.Contains(got.Messages[1].Content, "Hvad kan jeg lide?") {
		t.Fatalf("Memory4 did not wrap final user correctly: %+v", got.Messages[1])
	}
}

func TestInjectConsciousnessExactGuidanceKeepsFinalUserLast(t *testing.T) {
	raw := []byte(`{"model":"x","messages":[{"role":"system","content":"s"},{"role":"user","content":"u"}],"extra":{"keep":true}}`)
	out, err := injectConsciousnessResponseGuidance(raw, "guide")
	if err != nil {
		t.Fatal(err)
	}
	var top map[string]json.RawMessage
	if err := json.Unmarshal(out, &top); err != nil {
		t.Fatal(err)
	}
	if _, ok := top["extra"]; !ok {
		t.Fatal("unknown top-level field was dropped")
	}
	var messages []struct {
		Role    string `json:"role"`
		Content string `json:"content"`
	}
	if err := json.Unmarshal(top["messages"], &messages); err != nil {
		t.Fatal(err)
	}
	if len(messages) != 3 || messages[2].Role != "user" || messages[2].Content != "u" {
		t.Fatalf("final user is not preserved last: %+v", messages)
	}
	if messages[1].Role != "system" || !strings.Contains(messages[1].Content, "guide") {
		t.Fatalf("guidance message missing: %+v", messages)
	}
}
