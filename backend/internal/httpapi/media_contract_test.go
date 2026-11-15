package httpapi

import (
    "strings"
    "testing"
)

func TestMediaIDContract(t *testing.T) {
    for _, id := range []string{"a", "asset_012-XYZ", strings.Repeat("a", 128)} {
        if !validMediaID(id) { t.Fatalf("valid id refused: %q", id) }
    }
    for _, id := range []string{"", "../a", "a/b", "a%2fb", "a.b", "a b", strings.Repeat("a", 129), "é"} {
        if validMediaID(id) { t.Fatalf("unsafe id accepted: %q", id) }
    }
}

func TestMediaPageLimitContract(t *testing.T) {
    for raw, want := range map[string]int{"": 50, "1": 1, "50": 50, "100": 100} {
        got, err := parseMediaLimit(raw)
        if err != nil || got != want { t.Fatalf("%q: %d, %v", raw, got, err) }
    }
    for _, raw := range []string{"0", "101", "-1", "+1", " 1", "1 ", "1.0", "abc", "1000"} {
        if _, err := parseMediaLimit(raw); err == nil { t.Fatalf("accepted %q", raw) }
    }
}

func TestMediaCursorContract(t *testing.T) {
    for _, cursor := range []string{"", "abc-DEF_123", strings.Repeat("x", 128)} {
        if err := validateMediaCursor(cursor); err != nil { t.Fatalf("refused valid cursor: %v", err) }
    }
    for _, cursor := range []string{"hello world", "a\n", "é", strings.Repeat("x", 129)} {
        if err := validateMediaCursor(cursor); err == nil { t.Fatalf("accepted invalid cursor %q", cursor) }
    }
}
