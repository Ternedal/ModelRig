package httpapi

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

func TestAgent3AppendTextHashIsExactUTF8(t *testing.T) {
	text := "<pilot>& æøå — 日本語"
	got, err := agent3ArgsSHA256(map[string]any{"text": text})
	if err != nil {
		t.Fatalf("agent3ArgsSHA256: %v", err)
	}
	sum := sha256.Sum256([]byte(text))
	want := hex.EncodeToString(sum[:])
	if got != want {
		t.Fatalf("append digest = %q, want exact UTF-8 digest %q", got, want)
	}
}

func TestAgent3AppendTextHashRejectsBroaderShape(t *testing.T) {
	for _, args := range []map[string]any{
		{},
		{"text": ""},
		{"text": "MARKER", "extra": true},
		{"text": 7},
	} {
		if _, err := agent3ArgsSHA256(args); err == nil {
			t.Fatalf("broader/invalid append args were accepted: %#v", args)
		}
	}
}
