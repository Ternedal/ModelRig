package main

import (
	"net/http"
	"testing"
)

func TestRequestedMutationRequiresExactlyOneAction(t *testing.T) {
	for _, test := range []struct {
		grant  string
		revoke string
		ok     bool
		method string
		device string
	}{
		{grant: "device-1", ok: true, method: http.MethodPut, device: "device-1"},
		{revoke: "device-1", ok: true, method: http.MethodDelete, device: "device-1"},
		{},
		{grant: "device-1", revoke: "device-2"},
	} {
		device, method, err := requestedMutation(test.grant, test.revoke)
		if test.ok {
			if err != nil || device != test.device || method != test.method {
				t.Fatalf("unexpected mutation result: device=%q method=%q err=%v", device, method, err)
			}
		} else if err == nil {
			t.Fatalf("expected invalid mutation for grant=%q revoke=%q", test.grant, test.revoke)
		}
	}
}

func TestParseLoopbackBackendURL(t *testing.T) {
	for _, raw := range []string{
		"http://127.0.0.1:8080",
		"http://localhost:8080",
		"http://[::1]:8080/base/",
	} {
		if _, err := parseLoopbackBackendURL(raw); err != nil {
			t.Fatalf("expected loopback URL %q to pass: %v", raw, err)
		}
	}

	for _, raw := range []string{
		"https://127.0.0.1:8080",
		"http://192.0.2.1:8080",
		"http://user:secret@127.0.0.1:8080",
		"http://127.0.0.1:8080?token=secret",
	} {
		if _, err := parseLoopbackBackendURL(raw); err == nil {
			t.Fatalf("expected URL %q to fail closed", raw)
		}
	}
}
