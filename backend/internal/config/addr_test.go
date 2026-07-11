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
