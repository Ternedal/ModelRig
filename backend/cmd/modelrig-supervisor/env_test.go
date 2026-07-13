package main

import (
	"os"
	"strings"
	"path/filepath"
	"testing"
)

func TestLoadEnvFile(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "modelrig.env")
	os.WriteFile(p, []byte("# comment\n\nMODELRIG_HOST=0.0.0.0\nKALIV_TOOLS_ENABLED=1\nQUOTED=\"a b\"\n"), 0o644)
	env, err := loadEnvFile(p)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]bool{"MODELRIG_HOST=0.0.0.0": true, "KALIV_TOOLS_ENABLED=1": true, "QUOTED=a b": true}
	if len(env) != 3 {
		t.Fatalf("got %d vars, want 3: %v", len(env), env)
	}
	for _, e := range env {
		if !want[e] {
			t.Errorf("unexpected env pair %q", e)
		}
	}
	// A missing file is fine, not an error.
	if env, err := loadEnvFile(filepath.Join(dir, "nope.env")); err != nil || env != nil {
		t.Errorf("missing file should be empty+nil, got %v err=%v", env, err)
	}
	// Malformed line errors.
	bad := filepath.Join(dir, "bad.env")
	os.WriteFile(bad, []byte("no_equals_here\n"), 0o644)
	if _, err := loadEnvFile(bad); err == nil {
		t.Error("a line without = should error")
	}
}

func TestLoadEnvFile_RealExample(t *testing.T) {
	// The documented file the user actually copies. It carries inline comments
	// on almost every line; the parser must not fold them into the values.
	p := filepath.Join("..", "..", "..", "deploy", "modelrig.env.example")
	env, err := loadEnvFile(p)
	if err != nil {
		t.Fatalf("the shipped env example must parse cleanly: %v", err)
	}
	m := map[string]string{}
	for _, e := range env {
		k, v, _ := strings.Cut(e, "=")
		m[k] = v
	}
	if m["MODELRIG_HOST"] != "0.0.0.0" {
		t.Fatalf("MODELRIG_HOST parsed as %q, want 0.0.0.0 (an inline comment leaked into the value)", m["MODELRIG_HOST"])
	}
	for k, v := range m {
		if strings.Contains(v, "#") {
			t.Errorf("%s=%q still contains an inline comment", k, v)
		}
	}
}
