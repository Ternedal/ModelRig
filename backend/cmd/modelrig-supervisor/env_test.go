package main

import (
	"os"
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
