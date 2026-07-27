package auth

import (
	"encoding/hex"
	"regexp"
	"testing"
)

var hex64 = regexp.MustCompile(`^[0-9a-f]{64}$`)

// The gate table in HANDOFF.md reads "everything authenticated -> 400" as
// "the token is not 64 chars". That is a contract, so it gets a test.
func TestNewTokenIs64HexChars(t *testing.T) {
	token, hash, err := NewToken()
	if err != nil {
		t.Fatalf("NewToken: %v", err)
	}
	if !hex64.MatchString(token) {
		t.Errorf("token is not 64 lowercase hex chars: %q (len %d)", token, len(token))
	}
	if !hex64.MatchString(hash) {
		t.Errorf("hash is not 64 lowercase hex chars: %q (len %d)", hash, len(hash))
	}
}

// Only the hash is persisted, so a caller that mixes the two must not silently
// still authenticate. They are never equal.
func TestTokenAndHashDiffer(t *testing.T) {
	token, hash, err := NewToken()
	if err != nil {
		t.Fatalf("NewToken: %v", err)
	}
	if token == hash {
		t.Fatal("token and its hash are identical; the stored value would grant access")
	}
	if got := Hash(token); got != hash {
		t.Errorf("NewToken's hash %q != Hash(token) %q", hash, got)
	}
}

func TestHashIsDeterministicAndNotIdentity(t *testing.T) {
	const sample = "not-a-real-token"
	a, b := Hash(sample), Hash(sample)
	if a != b {
		t.Errorf("Hash is not deterministic: %q vs %q", a, b)
	}
	if !hex64.MatchString(a) {
		t.Errorf("Hash output is not 64 hex chars: %q", a)
	}
	if a == sample {
		t.Error("Hash returned its input")
	}
	if Hash(sample) == Hash(sample+"x") {
		t.Error("Hash collided on a one-character difference")
	}
}

func TestNewTokenIsUnpredictable(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 64; i++ {
		token, _, err := NewToken()
		if err != nil {
			t.Fatalf("NewToken: %v", err)
		}
		if seen[token] {
			t.Fatalf("NewToken repeated a value after %d draws", i+1)
		}
		seen[token] = true
	}
}

func TestNewIDIs16HexChars(t *testing.T) {
	id, err := NewID()
	if err != nil {
		t.Fatalf("NewID: %v", err)
	}
	if len(id) != 16 {
		t.Errorf("NewID length = %d, want 16 (%q)", len(id), id)
	}
	if _, err := hex.DecodeString(id); err != nil {
		t.Errorf("NewID is not hex: %q (%v)", id, err)
	}
}
