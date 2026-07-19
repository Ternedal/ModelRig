package capabilityschema

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

type fixtureSet struct {
	Schema string `json:"schema"`
	Valid  []struct {
		Name       string          `json:"name"`
		Descriptor json.RawMessage `json:"descriptor"`
		Canonical  string          `json:"canonical"`
	} `json:"valid"`
	Invalid []struct {
		Name       string          `json:"name"`
		Descriptor json.RawMessage `json:"descriptor"`
	} `json:"invalid"`
}

func TestSharedFixtures(t *testing.T) {
	fixtures := loadFixtures(t)
	if fixtures.Schema != "kaliv-capability-fixtures/v1" {
		t.Fatalf("unexpected fixture schema %q", fixtures.Schema)
	}
	if len(fixtures.Valid) < 2 || len(fixtures.Invalid) < 10 {
		t.Fatalf("fixture coverage is unexpectedly small: %d valid, %d invalid",
			len(fixtures.Valid), len(fixtures.Invalid))
	}

	for _, fixture := range fixtures.Valid {
		fixture := fixture
		t.Run("valid/"+fixture.Name, func(t *testing.T) {
			descriptor, err := Parse(fixture.Descriptor)
			if err != nil {
				t.Fatalf("Parse: %v", err)
			}
			canonical, err := descriptor.CanonicalJSON()
			if err != nil {
				t.Fatalf("CanonicalJSON: %v", err)
			}
			if string(canonical) != fixture.Canonical {
				t.Fatalf("canonical mismatch\nwant: %s\n got: %s",
					fixture.Canonical, canonical)
			}
			roundTrip, err := Parse(canonical)
			if err != nil {
				t.Fatalf("canonical round-trip: %v", err)
			}
			if roundTrip.CapabilityID != descriptor.CapabilityID {
				t.Fatalf("round-trip id mismatch: %q != %q",
					roundTrip.CapabilityID, descriptor.CapabilityID)
			}
		})
	}

	for _, fixture := range fixtures.Invalid {
		fixture := fixture
		t.Run("invalid/"+fixture.Name, func(t *testing.T) {
			if _, err := Parse(fixture.Descriptor); err == nil {
				t.Fatal("invalid descriptor was accepted")
			}
		})
	}
}

func TestCanonicalJSONDoesNotHTMLEscape(t *testing.T) {
	fixtures := loadFixtures(t)
	for _, fixture := range fixtures.Valid {
		if !bytes.Contains(fixture.Descriptor, []byte("<lokal>")) {
			continue
		}
		descriptor, err := Parse(fixture.Descriptor)
		if err != nil {
			t.Fatal(err)
		}
		canonical, err := descriptor.CanonicalJSON()
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(canonical), `\u003c`) ||
			strings.Contains(string(canonical), `\u0026`) {
			t.Fatalf("canonical JSON HTML-escaped visible text: %s", canonical)
		}
		return
	}
	t.Fatal("fixture with visible HTML-sensitive characters is missing")
}

func TestSortedIDsRejectsDuplicates(t *testing.T) {
	fixtures := loadFixtures(t)
	first, err := Parse(fixtures.Valid[0].Descriptor)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := SortedIDs([]Descriptor{first, first}); err == nil {
		t.Fatal("duplicate capability ids were accepted")
	}
}

func loadFixtures(t *testing.T) fixtureSet {
	t.Helper()
	_, current, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot resolve test path")
	}
	path := filepath.Join(
		filepath.Dir(current),
		"..", "..", "..",
		"contracts",
		"kaliv-capability-v2-fixtures.json",
	)
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read fixtures: %v", err)
	}
	var fixtures fixtureSet
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&fixtures); err != nil {
		t.Fatalf("decode fixtures: %v", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); err == nil {
		t.Fatal("fixture file contains trailing JSON")
	}
	return fixtures
}
