package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestParseAutomaticSelfUpdateArgsWatchesNormalUpdate(t *testing.T) {
	root := t.TempDir()
	cfg, mode, err := parseAutomaticSelfUpdateArgs([]string{
		"-dir", root,
		"-repo=Example/Repo",
		"-current", "1.2.3", // ordinary main flag: ignored by the observer
		"-insecure-skip-verify",
		"-skip-attestation",
	}, ".")
	if err != nil {
		t.Fatal(err)
	}
	if mode != automaticSelfUpdateWatch {
		t.Fatalf("mode = %v, want watch", mode)
	}
	wantRoot, _ := filepath.Abs(root)
	if cfg.root != wantRoot || cfg.repo != "Example/Repo" {
		t.Fatalf("config = %+v", cfg)
	}
	if !cfg.skipVerify || !cfg.skipAttestation {
		t.Fatalf("verification overrides were not preserved: %+v", cfg)
	}
}

func TestParseAutomaticSelfUpdateArgsDisablesNonMutatingCommands(t *testing.T) {
	for _, arg := range []string{"-self-update", "-check", "-recover", "-version", "--version", "-test.v"} {
		_, mode, err := parseAutomaticSelfUpdateArgs([]string{arg}, t.TempDir())
		if err != nil {
			t.Fatalf("%s: %v", arg, err)
		}
		if mode != automaticSelfUpdateDisabled {
			t.Fatalf("%s mode = %v, want disabled", arg, mode)
		}
	}
}

func TestParseAutomaticSelfUpdateArgsRecognizesPostCommitChild(t *testing.T) {
	fingerprint := strings.Repeat("ab", 32)
	cfg, mode, err := parseAutomaticSelfUpdateArgs([]string{
		postCommitSelfUpdateArg,
		"-dir", t.TempDir(),
		"-baseline-commit=" + fingerprint,
	}, ".")
	if err != nil {
		t.Fatal(err)
	}
	if mode != automaticSelfUpdatePostCommit {
		t.Fatalf("mode = %v, want post-commit", mode)
	}
	if !reflect.DeepEqual(cfg.baseline, []string{fingerprint}) {
		t.Fatalf("baseline = %v", cfg.baseline)
	}
}

func TestParseAutomaticSelfUpdateArgsRejectsInvalidObservedValues(t *testing.T) {
	for _, args := range [][]string{
		{"-dir"},
		{"-repo", ""},
		{postCommitSelfUpdateArg, "-baseline-commit=not-a-hash"},
	} {
		if _, _, err := parseAutomaticSelfUpdateArgs(args, t.TempDir()); err == nil {
			t.Fatalf("expected error for %v", args)
		}
	}
}

func TestCommittedTransactionFingerprintsOnlyIncludesCommittedEvidence(t *testing.T) {
	root := t.TempDir()
	journal := filepath.Join(root, "update-transaction.json")
	committed := txData{ID: "tx-1", From: "1.0.0", To: "1.1.0", State: "committed", Revision: 7}
	body, err := json.Marshal(committed)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(journal+".last", body, 0o644); err != nil {
		t.Fatal(err)
	}
	fingerprints, err := committedTransactionFingerprints(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(fingerprints) != 1 {
		t.Fatalf("fingerprints = %v, want one", fingerprints)
	}

	rolledBack := committed
	rolledBack.State = "rolled_back"
	body, _ = json.Marshal(rolledBack)
	if err := os.WriteFile(journal, body, 0o644); err != nil {
		t.Fatal(err)
	}
	after, err := committedTransactionFingerprints(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(after) != 1 || after[0] != fingerprints[0] {
		t.Fatalf("rolled-back evidence affected committed set: before=%v after=%v", fingerprints, after)
	}
}

func TestHasNewCommittedTransaction(t *testing.T) {
	if hasNewCommittedTransaction([]string{"a"}, []string{"a"}) {
		t.Fatal("unchanged committed evidence must not trigger self-update")
	}
	if !hasNewCommittedTransaction([]string{"a"}, []string{"b"}) {
		t.Fatal("new committed evidence must trigger self-update")
	}
	if hasNewCommittedTransaction([]string{"a"}, nil) {
		t.Fatal("missing committed evidence must not trigger self-update")
	}
}

func TestPostCommitSelfUpdateArgsPreserveTrustOverrides(t *testing.T) {
	cfg := automaticSelfUpdateConfig{
		root:            `C:\Rig`,
		repo:            "Example/Repo",
		skipVerify:      true,
		skipAttestation: true,
	}
	got := postCommitSelfUpdateArgs(cfg)
	want := []string{
		"-self-update", "-dir", `C:\Rig`, "-repo", "Example/Repo",
		"-insecure-skip-verify", "-skip-attestation",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("args = %#v, want %#v", got, want)
	}
}
