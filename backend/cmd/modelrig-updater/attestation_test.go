package main

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
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

// --- the refusal itself, not the lookup ------------------------------------
//
// In 1.58.81 I tested attestationsAt and wrote "the updater refuses" in the
// release notes. That was a description, not a result: the refusal lived inline
// in main() behind die(), so the only machine that could ever discover whether
// it worked was the rig, mid-update, against a tampered binary. These drive the
// refusal.

func stageFile(t *testing.T, name, content string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestVerifyProvenanceRefusesUnsignedArtifact(t *testing.T) {
	dir := stageFile(t, "modelrig-server.exe", "a binary nobody signed")
	targets := []target{{asset: "modelrig-server.exe"}}

	err := verifyProvenance(targets, dir, "Ternedal/ModelRig",
		func(repo, digest string) (int, error) { return 0, nil })

	if err == nil {
		t.Fatal("an artifact with no attestation MUST NOT be installed")
	}
	if !strings.Contains(err.Error(), "NO BUILD PROVENANCE") {
		t.Fatalf("the refusal must say why, got: %v", err)
	}
}

func TestVerifyProvenanceRefusesWhenLookupFails(t *testing.T) {
	dir := stageFile(t, "modelrig-server.exe", "a binary")
	targets := []target{{asset: "modelrig-server.exe"}}

	err := verifyProvenance(targets, dir, "Ternedal/ModelRig",
		func(repo, digest string) (int, error) { return 0, fmt.Errorf("network is down") })

	if err == nil {
		t.Fatal("unreachable is not unattested, but neither is a reason to swap a live binary")
	}
	if !strings.Contains(err.Error(), "cannot check provenance") {
		t.Fatalf("the refusal must distinguish 'cannot verify' from 'not signed', got: %v", err)
	}
}

func TestVerifyProvenanceAcceptsSignedArtifact(t *testing.T) {
	dir := stageFile(t, "modelrig-server.exe", "a binary the workflow signed")
	targets := []target{{asset: "modelrig-server.exe"}}

	if err := verifyProvenance(targets, dir, "Ternedal/ModelRig",
		func(repo, digest string) (int, error) { return 1, nil }); err != nil {
		t.Fatalf("an attested artifact must install: %v", err)
	}
}

func TestVerifyProvenanceChecksEveryTarget(t *testing.T) {
	// The loop must not stop at the first good one: a release swaps several
	// binaries, and one unsigned exe among them is the whole attack.
	dir := t.TempDir()
	for _, n := range []string{"a.exe", "b.exe"} {
		if err := os.WriteFile(filepath.Join(dir, n), []byte(n), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	targets := []target{{asset: "a.exe"}, {asset: "b.exe"}}
	seen := map[string]bool{}

	err := verifyProvenance(targets, dir, "r", func(repo, digest string) (int, error) {
		seen[digest] = true
		if len(seen) == 1 {
			return 1, nil // the first is signed
		}
		return 0, nil // the second is not
	})

	if err == nil {
		t.Fatal("one unsigned binary among several must still refuse the whole swap")
	}
	if len(seen) != 2 {
		t.Fatalf("every target must be checked, saw %d", len(seen))
	}
}

func TestVerifyProvenanceRefusesMissingFile(t *testing.T) {
	targets := []target{{asset: "not-downloaded.exe"}}
	if err := verifyProvenance(targets, t.TempDir(), "r",
		func(repo, digest string) (int, error) { return 1, nil }); err == nil {
		t.Fatal("a file that cannot be hashed cannot be vouched for")
	}
}
