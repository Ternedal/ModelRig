package httpapi

import (
	"encoding/json"
	"testing"
)

func TestMemory4ReceiptMustStillBePreModel(t *testing.T) {
	resp := memory4ContextResponse{
		Schema:  memory4ContextServiceSchema,
		Context: "memory-data",
		Receipt: memory4ContextReceipt{
			Schema:         memory4ContextReceiptSchema,
			Target:         "local",
			CandidateCount: 1,
			RankedCount:    1,
			IncludedIDs:    []string{"memory-1"},
			ExcludedCount:  0,
			ExclusionReasons: map[string]int{
				"not_relevant_or_below_threshold": 0,
				"context_budget":                   0,
			},
			CharacterCount: 11,
			ByteCount:      11,
			ContextSHA256:  "301409d873c62d096f9f044934ab859ba1d1f3b2d29559bce893f9ffbe58e196",
			SentToModel:    true,
		},
	}
	if err := validateMemory4Context(resp, "local"); err == nil {
		t.Fatal("sent_to_model=true receipt must be rejected before model egress")
	}
}

func TestMemory4ResponseRequiresCompleteReceipt(t *testing.T) {
	resp := memory4ReceiptResponse("", "local", 0, 0, []string{})
	receipt := resp["receipt"].(map[string]any)
	delete(receipt, "sent_to_model")
	raw, err := json.Marshal(resp)
	if err != nil {
		t.Fatalf("marshal fixture: %v", err)
	}
	if err := requireMemory4ResponseFields(raw); err == nil {
		t.Fatal("missing sent_to_model field must fail the R04 wire contract")
	}
}
