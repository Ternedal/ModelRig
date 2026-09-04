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
	"strconv"
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

type observedFlag struct {
	name     string
	value    string
	hasValue bool
}

// splitObservedFlag mirrors the spellings accepted by Go's flag package: one
// or two leading dashes, with an optional =value suffix. A positional argument,
// a lone dash, --, or three-plus leading dashes is not a flag.
func splitObservedFlag(raw string) (observedFlag, bool) {
	if raw == "" || raw == "-" || raw == "--" || raw[0] != '-' {
		return observedFlag{}, false
	}
	trimmed := raw[1:]
	if strings.HasPrefix(trimmed, "-") {
		trimmed = trimmed[1:]
	}
	if trimmed == "" || strings.HasPrefix(trimmed, "-") {
		return observedFlag{}, false
	}
	name, value, hasValue := strings.Cut(trimmed, "=")
	if name == "" {
		return observedFlag{}, false
	}
	return observedFlag{name: name, value: value, hasValue: hasValue}, true
}

func observedStringValue(flag observedFlag, args []string, index *int) (string, error) {
	if flag.hasValue {
		return flag.value, nil
	}
	if *index+1 >= len(args) {
		return "", fmt.Errorf("-%s requires a value", flag.name)
	}
	*index = *index + 1
	return args[*index], nil
}

func observedBoolValue(flag observedFlag) (bool, error) {
	if !flag.hasValue {
		return true, nil
	}
	value, err := strconv.ParseBool(flag.value)
	if err != nil {
		return false, fmt.Errorf("invalid value %q for -%s: %w", flag.value, flag.name, err)
	}
	return value, nil
}

// parseAutomaticSelfUpdateArgs observes only the flags needed to faithfully
// replay self-update after a normal appliance update. It also consumes values
// for every ordinary updater string flag so its scan stays aligned with the
// same command line parsed by flag.Parse in main. Repeated booleans use their
// final value, matching flag.Parse rather than short-circuiting on the first
// true occurrence.
func parseAutomaticSelfUpdateArgs(args []string, defaultRoot string) (automaticSelfUpdateConfig, automaticSelfUpdateMode, error) {
	cfg := automaticSelfUpdateConfig{root: defaultRoot, repo: "Ternedal/ModelRig"}
	check := false
	recoverOnly := false
	selectorSeen := false
	selector := false
	for i := 0; i < len(args); i++ {
		raw := args[i]
		if raw == "--" {
			break
		}
		flag, ok := splitObservedFlag(raw)
		if !ok {
			break // flag.Parse stops at the first positional argument.
		}

		switch {
		case flag.name == "post-commit-self-update":
			value, err := observedBoolValue(flag)
			if err != nil {
				return cfg, automaticSelfUpdateDisabled, err
			}
			selectorSeen = true
			selector = value
		case flag.name == "self-update" || flag.name == "version":
			return cfg, automaticSelfUpdateDisabled, nil
		case strings.HasPrefix(flag.name, "test."):
			return cfg, automaticSelfUpdateDisabled, nil
		case flag.name == "check" || flag.name == "recover":
			value, err := observedBoolValue(flag)
			if err != nil {
				return cfg, automaticSelfUpdateDisabled, err
			}
			if flag.name == "check" {
				check = value
			} else {
				recoverOnly = value
			}
		case flag.name == "insecure-skip-verify" || flag.name == "skip-attestation":
			value, err := observedBoolValue(flag)
			if err != nil {
				return cfg, automaticSelfUpdateDisabled, err
			}
			if flag.name == "insecure-skip-verify" {
				cfg.skipVerify = value
			} else {
				cfg.skipAttestation = value
			}
		case flag.name == "dir" || flag.name == "repo" ||
			flag.name == "current" || flag.name == "server-health" ||
			flag.name == "worker-health" || flag.name == "heartbeat" ||
			flag.name == "supervisor-interval" || flag.name == "supervisor-task" ||
			flag.name == "baseline-commit":
			value, err := observedStringValue(flag, args, &i)
			if err != nil {
				return cfg, automaticSelfUpdateDisabled, err
			}
			switch flag.name {
			case "dir":
				cfg.root = value
			case "repo":
				cfg.repo = strings.TrimSpace(value)
			case "baseline-commit":
				fingerprint := strings.ToLower(strings.TrimSpace(value))
				if len(fingerprint) != sha256.Size*2 {
					return cfg, automaticSelfUpdateDisabled, fmt.Errorf("invalid committed-journal fingerprint %q", fingerprint)
				}
				if _, err := hex.DecodeString(fingerprint); err != nil {
					return cfg, automaticSelfUpdateDisabled, fmt.Errorf("invalid committed-journal fingerprint %q", fingerprint)
				}
				cfg.baseline = append(cfg.baseline, fingerprint)
			}
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

	if check || recoverOnly {
		return cfg, automaticSelfUpdateDisabled, nil
	}
	if selectorSeen {
		if selector {
			return cfg, automaticSelfUpdatePostCommit, nil
		}
		// The selector is internal, not an ordinary updater flag. A final false
		// value must disable both the hidden child and normal watcher startup;
		// main will reject the malformed internal invocation normally.
		return cfg, automaticSelfUpdateDisabled, nil
	}
	return cfg, automaticSelfUpdateWatch, nil
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
	root, err := os.Getwd()
	if err != nil {
		return
	}
	cfg, mode, err := parseAutomaticSelfUpdateArgs(os.Args[1:], root)
	if err != nil || mode != automaticSelfUpdatePostCommit {
		return
	}
	log.SetPrefix("updater automatic self-update: ")
	log.SetFlags(log.LstdFlags)
	if err := runPostCommitSelfUpdate(cfg); err != nil {
		log.Printf("FAILED: %v", err)
		os.Exit(1)
	}
	os.Exit(0)
}
