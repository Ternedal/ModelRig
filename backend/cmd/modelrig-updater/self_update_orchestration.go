package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const postCommitSelfUpdateArg = "-post-commit-self-update"

type automaticSelfUpdateMode int

const (
	automaticSelfUpdateDisabled automaticSelfUpdateMode = iota
	automaticSelfUpdateWatch
	automaticSelfUpdatePostCommit
)

type automaticSelfUpdateConfig struct {
	root            string
	repo            string
	skipVerify      bool
	skipAttestation bool
	baseline        []string
}

// parseAutomaticSelfUpdateArgs observes only the flags needed to faithfully
// replay self-update after a normal appliance update. Unknown flags belong to
// main's ordinary flag set and are deliberately ignored here.
func parseAutomaticSelfUpdateArgs(args []string, defaultRoot string) (automaticSelfUpdateConfig, automaticSelfUpdateMode, error) {
	cfg := automaticSelfUpdateConfig{root: defaultRoot, repo: "Ternedal/ModelRig"}
	mode := automaticSelfUpdateWatch
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == postCommitSelfUpdateArg:
			mode = automaticSelfUpdatePostCommit
		case a == "-self-update" || a == "-check" || a == "-recover" || a == "-version" || a == "--version":
			return cfg, automaticSelfUpdateDisabled, nil
		case strings.HasPrefix(a, "-test."):
			return cfg, automaticSelfUpdateDisabled, nil
		case a == "-dir" || a == "-repo":
			if i+1 >= len(args) {
				return cfg, automaticSelfUpdateDisabled, fmt.Errorf("%s requires a value", a)
			}
			i++
			if a == "-dir" {
				cfg.root = args[i]
			} else {
				cfg.repo = strings.TrimSpace(args[i])
			}
		case strings.HasPrefix(a, "-dir="):
			cfg.root = strings.TrimPrefix(a, "-dir=")
		case strings.HasPrefix(a, "-repo="):
			cfg.repo = strings.TrimSpace(strings.TrimPrefix(a, "-repo="))
		case a == "-insecure-skip-verify":
			cfg.skipVerify = true
		case a == "-skip-attestation":
			cfg.skipAttestation = true
		case strings.HasPrefix(a, "-baseline-commit="):
			fingerprint := strings.ToLower(strings.TrimSpace(strings.TrimPrefix(a, "-baseline-commit=")))
			if len(fingerprint) != sha256.Size*2 {
				return cfg, automaticSelfUpdateDisabled, fmt.Errorf("invalid committed-journal fingerprint %q", fingerprint)
			}
			if _, err := hex.DecodeString(fingerprint); err != nil {
				return cfg, automaticSelfUpdateDisabled, fmt.Errorf("invalid committed-journal fingerprint %q", fingerprint)
			}
			cfg.baseline = append(cfg.baseline, fingerprint)
		}
	}
	if strings.TrimSpace(cfg.repo) == "" {
		return cfg, automaticSelfUpdateDisabled, fmt.Errorf("repository must not be empty")
	}
	absRoot, err := filepath.Abs(cfg.root)
	if err != nil {
		return cfg, automaticSelfUpdateDisabled, fmt.Errorf("resolve updater root: %w", err)
	}
	cfg.root = absRoot
	sort.Strings(cfg.baseline)
	return cfg, mode, nil
}

// committedTransactionFingerprints returns content hashes for every journal
// file that independently claims a committed appliance transaction. Capturing
// this set before the normal updater runs lets the detached watcher distinguish
// a newly committed update from an already-current check or a rollback without
// depending on a racy process-exit-code lookup.
func committedTransactionFingerprints(root string) ([]string, error) {
	journal := filepath.Join(root, "update-transaction.json")
	paths := []string{journal, journal + ".tmp", journal + ".last"}
	fingerprints := make([]string, 0, len(paths))
	seen := map[string]bool{}
	for _, path := range paths {
		body, err := os.ReadFile(path)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("read transaction evidence %s: %w", path, err)
		}
		var transaction txData
		if err := json.Unmarshal(body, &transaction); err != nil {
			return nil, fmt.Errorf("parse transaction evidence %s: %w", path, err)
		}
		if transaction.State != "committed" {
			continue
		}
		sum := sha256.Sum256(body)
		fingerprint := hex.EncodeToString(sum[:])
		if !seen[fingerprint] {
			seen[fingerprint] = true
			fingerprints = append(fingerprints, fingerprint)
		}
	}
	sort.Strings(fingerprints)
	return fingerprints, nil
}

func hasNewCommittedTransaction(before, after []string) bool {
	known := make(map[string]bool, len(before))
	for _, fingerprint := range before {
		known[fingerprint] = true
	}
	for _, fingerprint := range after {
		if !known[fingerprint] {
			return true
		}
	}
	return false
}

func postCommitSelfUpdateArgs(cfg automaticSelfUpdateConfig) []string {
	args := []string{"-self-update", "-dir", cfg.root, "-repo", cfg.repo}
	if cfg.skipVerify {
		args = append(args, "-insecure-skip-verify")
	}
	if cfg.skipAttestation {
		args = append(args, "-skip-attestation")
	}
	return args
}

func runPostCommitSelfUpdate(cfg automaticSelfUpdateConfig) error {
	current, err := committedTransactionFingerprints(cfg.root)
	if err != nil {
		return err
	}
	if !hasNewCommittedTransaction(cfg.baseline, current) {
		log.Printf("automatic self-update skipped: no new committed appliance transaction")
		return nil
	}
	log.Printf("new committed appliance transaction detected; checking updater self-update")
	return selfUpdateCommand(postCommitSelfUpdateArgs(cfg))
}

// The hidden post-commit child is invoked only by the detached Windows watcher.
// It runs after the normal updater process has exited and therefore cannot gate
// appliance rollback or change the original command's exit status.
func init() {
	found := false
	for _, arg := range os.Args[1:] {
		if arg == postCommitSelfUpdateArg {
			found = true
			break
		}
	}
	if !found {
		return
	}
	root, err := os.Getwd()
	if err != nil {
		fmt.Fprintln(os.Stderr, "updater automatic self-update:", err)
		os.Exit(1)
	}
	cfg, mode, err := parseAutomaticSelfUpdateArgs(os.Args[1:], root)
	if err != nil {
		fmt.Fprintln(os.Stderr, "updater automatic self-update:", err)
		os.Exit(1)
	}
	if mode != automaticSelfUpdatePostCommit {
		fmt.Fprintln(os.Stderr, "updater automatic self-update: invalid internal invocation")
		os.Exit(1)
	}
	log.SetPrefix("updater automatic self-update: ")
	log.SetFlags(log.LstdFlags)
	if err := runPostCommitSelfUpdate(cfg); err != nil {
		log.Printf("FAILED: %v", err)
		os.Exit(1)
	}
	os.Exit(0)
}
