package pairing

import (
	"strings"
	"testing"
)

// The alphabet comment promises that visually ambiguous characters are
// excluded. Nothing enforced it until now: a typo re-adding "0" or "1" would
// have shipped, and the symptom is a user who cannot pair and does not know why.
func TestAlphabetExcludesAmbiguousCharacters(t *testing.T) {
	for _, bad := range []string{"0", "O", "1", "I", "L"} {
		if strings.Contains(alphabet, bad) {
			t.Errorf("alphabet contains the ambiguous character %q", bad)
		}
	}
	if len(alphabet) != 31 {
		t.Errorf("alphabet length = %d, want 31 (A-Z minus I,L,O plus 2-9)", len(alphabet))
	}
	seen := map[rune]bool{}
	for _, r := range alphabet {
		if seen[r] {
			t.Errorf("alphabet repeats %q, which skews the draw", r)
		}
		seen[r] = true
	}
}

func TestCodeShape(t *testing.T) {
	for i := 0; i < 64; i++ {
		c, err := Code()
		if err != nil {
			t.Fatalf("Code: %v", err)
		}
		if len(c) != 9 {
			t.Fatalf("Code length = %d, want 9 (%q)", len(c), c)
		}
		if c[4] != '-' {
			t.Fatalf("Code is not XXXX-XXXX: %q", c)
		}
		for _, r := range strings.ReplaceAll(c, "-", "") {
			if !strings.ContainsRune(alphabet, r) {
				t.Fatalf("Code %q contains %q, which is outside the alphabet", c, r)
			}
		}
	}
}

func TestCodeIsUnpredictable(t *testing.T) {
	seen := map[string]bool{}
	for i := 0; i < 64; i++ {
		c, err := Code()
		if err != nil {
			t.Fatalf("Code: %v", err)
		}
		if seen[c] {
			t.Fatalf("Code repeated a value after %d draws", i+1)
		}
		seen[c] = true
	}
}

func TestNormalizeAcceptsWhatAUserActuallyTypes(t *testing.T) {
	const want = "AB23-4CDE"
	for _, in := range []string{
		"AB23-4CDE", "ab23-4cde", " AB234CDE ", "AB23 4CDE", "a b 2 3 4 c d e",
	} {
		if got := Normalize(in); got != want {
			t.Errorf("Normalize(%q) = %q, want %q", in, got, want)
		}
	}
}

// Normalize's doc says callers must still validate the length, so a wrong-length
// input must come back WITHOUT a dash -- otherwise a caller checking only the
// shape would accept it.
func TestNormalizeDoesNotFabricateShapeForWrongLength(t *testing.T) {
	for _, in := range []string{"", "ABC", "AB23-4CDEF", strings.Repeat("A", 20)} {
		got := Normalize(in)
		if len(got) == 9 && strings.Count(got, "-") == 1 {
			t.Errorf("Normalize(%q) = %q, which passes a shape check it should not", in, got)
		}
	}
}

func TestNormalizeRoundTripsCode(t *testing.T) {
	c, err := Code()
	if err != nil {
		t.Fatalf("Code: %v", err)
	}
	if got := Normalize(c); got != c {
		t.Errorf("Normalize(Code()) = %q, want %q", got, c)
	}
}
