package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// The provenance check is the only thing in this updater that survives a stolen
// release token, so it gets driven rather than eyeballed. A verification step
// that silently no-ops looks exactly like one that works.
//
// These run against a fake GitHub so CI does not depend on the network or on a
// release existing. The same code was driven against the real API before it
// shipped: v1.58.80's server exe returns 1 attestation, and a digest of
// "tampered" returns 0.

func withFakeGitHub(t *testing.T, handler http.HandlerFunc) string {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	return srv.URL
}

func TestAttestedByCountsBundles(t *testing.T) {
	body := `{"attestations":[{"bundle":{"mediaType":"application/vnd.dev.sigstore.bundle+json;version=0.3"}}]}`
	srv := withFakeGitHub(t, func(w http.ResponseWriter, r *http.Request) {
		if !strings.Contains(r.URL.Path, "/attestations/sha256:") {
			t.Errorf("updater asked the wrong endpoint: %s", r.URL.Path)
		}
		fmt.Fprint(w, body)
	})
	n, err := attestationsAt(srv + "/repos/x/y/attestations/sha256:abc")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if n != 1 {
		t.Fatalf("an attested artifact must count 1, got %d", n)
	}
}

func TestAttestedByReportsZeroForTamperedArtifact(t *testing.T) {
	// GitHub answers 200 with an empty list for a digest it never signed. This
	// is the case that matters: the attacker replaced the exe, rewrote
	// SHA256SUMS to match, and every check above this one passed.
	srv := withFakeGitHub(t, func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"attestations":[]}`)
	})
	n, err := attestationsAt(srv + "/repos/x/y/attestations/sha256:abc")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if n != 0 {
		t.Fatalf("an unsigned artifact must count 0, got %d -- the updater would install it", n)
	}
}

func TestAttestedByTreatsUnreachableAsUnverifiable(t *testing.T) {
	// Unreachable is not the same as unattested, and neither is a reason to
	// install. The error must surface so the caller can refuse rather than
	// quietly read it as "no attestations".
	srv := withFakeGitHub(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
	if _, err := attestationsAt(srv + "/repos/x/y/attestations/sha256:abc"); err == nil {
		t.Fatal("a failed lookup must return an error, not zero attestations")
	}
}

func TestAttestedByRejectsGarbage(t *testing.T) {
	srv := withFakeGitHub(t, func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `not json`)
	})
	if _, err := attestationsAt(srv + "/repos/x/y/attestations/sha256:abc"); err == nil {
		t.Fatal("an unparseable answer must be an error, not an implicit zero")
	}
}
