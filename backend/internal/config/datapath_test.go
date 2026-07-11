package config

import (
	"path/filepath"
	"testing"
)

// A relative data path must be anchored on the executable dir, so the server
// finds the same device-token file regardless of the working directory it is
// launched from (the 401-after-relaunch footgun). An absolute path is untouched.
func TestResolveDataPathAnchorsRelative(t *testing.T) {
	c := &Config{DataPath: "./modelrig-data.json"}
	c.ResolveDataPath()
	if !filepath.IsAbs(c.DataPath) {
		t.Fatalf("relative DataPath was not made absolute: %q", c.DataPath)
	}
	if filepath.Base(c.DataPath) != "modelrig-data.json" {
		t.Fatalf("basename changed: %q", c.DataPath)
	}

	abs := filepath.Join(string(filepath.Separator), "etc", "kaliv", "data.json")
	c2 := &Config{DataPath: abs}
	c2.ResolveDataPath()
	if c2.DataPath != abs {
		t.Fatalf("absolute DataPath must be left untouched: got %q want %q", c2.DataPath, abs)
	}
}
