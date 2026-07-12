package config

import "testing"

// A trailing space in MODELRIG_HOST (a batch `set X=val && cmd` footgun) made
// Addr() produce "0.0.0.0 :8080", which Go's net.Listen tries to DNS-resolve
// -> "lookup 0.0.0.0 : no such host", and the server never binds. The phone
// then cannot reach the rig. Addr() must trim so a stray space cannot break it.
func TestAddrTrimsSpacedHost(t *testing.T) {
	c := Config{ServerHost: "0.0.0.0 ", ServerPort: 8080}
	if got := c.Addr(); got != "0.0.0.0:8080" {
		t.Fatalf("Addr() = %q, want %q (trailing space must be trimmed)", got, "0.0.0.0:8080")
	}
	c2 := Config{ServerHost: " 127.0.0.1 ", ServerPort: 8099}
	if got := c2.Addr(); got != "127.0.0.1:8099" {
		t.Fatalf("Addr() = %q, want %q", got, "127.0.0.1:8099")
	}
}

// Every string env var must be trimmed, not just the host. A batch
// `set X=val && cmd` captures a trailing space into ALL of them, and an
// untrimmed URL/path breaks silently the way the bind host did.
func TestEnvValuesAreTrimmed(t *testing.T) {
	t.Setenv("MODELRIG_OLLAMA_URL", "http://127.0.0.1:11434 ")
	t.Setenv("MODELRIG_WORKER_URL", " http://127.0.0.1:8099")
	t.Setenv("MODELRIG_DATA", " /tmp/x/data.json ")
	c, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.OllamaBaseURL != "http://127.0.0.1:11434" {
		t.Fatalf("OllamaBaseURL not trimmed: %q", c.OllamaBaseURL)
	}
	if c.WorkerBaseURL != "http://127.0.0.1:8099" {
		t.Fatalf("WorkerBaseURL not trimmed: %q", c.WorkerBaseURL)
	}
	if c.DataPath != "/tmp/x/data.json" {
		t.Fatalf("DataPath not trimmed: %q", c.DataPath)
	}
}
