package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"

	"modelrig/internal/config"
)

const (
	updaterAssetName   = "modelrig-updater-windows-x64.exe"
	releaseWorkflowPath = ".github/workflows/build-and-release.yml"
)

// updaterVersion is compiled into the updater from the same version constant
// used by the backend. scripts/version_tool.py already proves that constant
// matches the repository VERSION and release tag, so an old updater cannot
// impersonate a newer one by reading a mutable file beside itself.
var updaterVersion = config.Version

type selfUpdateConfig struct {
	repo            string
	root            string
	skipVerify      bool
	skipAttestation bool
}

// The existing main flag set predates updater self-replacement. Intercept the
// two updater-owned commands before main parses flags, so the normal appliance
// update path remains byte-for-byte untouched and keeps its rollback model.
func init() {
	for _, arg := range os.Args[1:] {
		switch arg {
		case "-version", "--version":
			fmt.Println(resolveUpdaterVersion())
			os.Exit(0)
		case "-self-update":
			if err := selfUpdateCommand(os.Args[1:]); err != nil {
				fmt.Fprintln(os.Stderr, "updater self-update:", err)
				os.Exit(1)
			}
			os.Exit(0)
		}
	}
}

func executableDir() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	exe, err = filepath.Abs(exe)
	if err != nil {
		return "", err
	}
	return filepath.Dir(exe), nil
}

func parseSelfUpdateArgs(args []string) (selfUpdateConfig, error) {
	root, err := executableDir()
	if err != nil {
		return selfUpdateConfig{}, err
	}
	cfg := selfUpdateConfig{repo: "Ternedal/ModelRig", root: root}
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "-self-update":
			// command selector; already consumed by init
		case a == "-repo" || a == "-dir":
			if i+1 >= len(args) {
				return selfUpdateConfig{}, fmt.Errorf("%s requires a value", a)
			}
			i++
			if a == "-repo" {
				cfg.repo = strings.TrimSpace(args[i])
			} else {
				cfg.root = args[i]
			}
		case strings.HasPrefix(a, "-repo="):
			cfg.repo = strings.TrimSpace(strings.TrimPrefix(a, "-repo="))
		case strings.HasPrefix(a, "-dir="):
			cfg.root = strings.TrimPrefix(a, "-dir=")
		case a == "-insecure-skip-verify":
			cfg.skipVerify = true
		case a == "-skip-attestation":
			cfg.skipAttestation = true
		default:
			return selfUpdateConfig{}, fmt.Errorf("unknown self-update argument %q", a)
		}
	}
	if cfg.repo == "" {
		return selfUpdateConfig{}, fmt.Errorf("repository must not be empty")
	}
	absRoot, err := filepath.Abs(cfg.root)
	if err != nil {
		return selfUpdateConfig{}, fmt.Errorf("resolve updater root: %w", err)
	}
	cfg.root = absRoot
	return cfg, nil
}

func selfUpdateCommand(args []string) error {
	cfg, err := parseSelfUpdateArgs(args)
	if err != nil {
		return err
	}
	lockPath := filepath.Join(cfg.root, "updater.lock")
	if err := acquireLock(lockPath); err != nil {
		return err
	}
	lockTransferred := false
	defer func() {
		if !lockTransferred {
			releaseLock(lockPath)
		}
	}()
	return runSelfUpdate(cfg, lockPath, func() { lockTransferred = true })
}

func resolveUpdaterVersion() string {
	v := strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(updaterVersion), "v"))
	if v != "" && v != "dev" {
		if _, err := parseSemver(v); err == nil {
			return v
		}
	}
	return "dev"
}

func runSelfUpdate(cfg selfUpdateConfig, lockPath string, transferLock func()) error {
	current := resolveUpdaterVersion()
	if current == "dev" {
		return fmt.Errorf("current updater version is unknown; refusing self-update without a compiled version identity")
	}

	relBody, err := httpGet(fmt.Sprintf("https://api.github.com/repos/%s/releases/latest", cfg.repo))
	if err != nil {
		return fmt.Errorf("fetch latest release: %w", err)
	}
	tag, urls, err := selectAssets(relBody, []string{updaterAssetName})
	if err != nil {
		return err
	}
	newer, err := isNewer(current, tag)
	if err != nil {
		return fmt.Errorf("version compare: %w", err)
	}
	if !newer {
		log.Printf("updater already current (running %s, latest %s)", current, tag)
		return nil
	}

	staged, err := os.MkdirTemp("", "kaliv-updater-self-")
	if err != nil {
		return fmt.Errorf("staging dir: %w", err)
	}
	defer os.RemoveAll(staged)
	stagedAsset := filepath.Join(staged, updaterAssetName)
	if err := download(urls[updaterAssetName], stagedAsset); err != nil {
		return fmt.Errorf("download %s: %w", updaterAssetName, err)
	}

	sumsURL := assetURL(relBody, "SHA256SUMS.txt")
	if sumsURL == "" && !cfg.skipVerify {
		return fmt.Errorf("release %s has no SHA256SUMS.txt -- refusing self-update", tag)
	}
	if sumsURL != "" {
		sumsPath := filepath.Join(staged, "SHA256SUMS.txt")
		if err := download(sumsURL, sumsPath); err != nil {
			return fmt.Errorf("download SHA256SUMS.txt: %w", err)
		}
		data, err := os.ReadFile(sumsPath)
		if err != nil {
			return fmt.Errorf("read SHA256SUMS.txt: %w", err)
		}
		want, ok := parseSums(data)[updaterAssetName]
		if !ok {
			return fmt.Errorf("SHA256SUMS.txt has no entry for %s", updaterAssetName)
		}
		got, err := fileSHA256(stagedAsset)
		if err != nil {
			return fmt.Errorf("hash updater: %w", err)
		}
		if !strings.EqualFold(got, want) {
			return fmt.Errorf("checksum mismatch for %s (want %s, got %s)", updaterAssetName, want, got)
		}
		if !cfg.skipAttestation {
			lookup := func(repo, digest string) (int, error) {
				return attestedForRelease(repo, digest, tag)
			}
			if err := verifyProvenance([]target{{asset: updaterAssetName}}, staged, cfg.repo, lookup); err != nil {
				return err
			}
		} else {
			log.Printf("WARNING: updater self-update without release-bound provenance verification (-skip-attestation)")
		}
	} else {
		log.Printf("WARNING: updater self-update without checksum or provenance verification (-insecure-skip-verify)")
	}

	live := filepath.Join(cfg.root, updaterAssetName)
	exe, err := os.Executable()
	if err != nil {
		return fmt.Errorf("resolve running updater: %w", err)
	}
	exe, err = filepath.Abs(exe)
	if err != nil {
		return fmt.Errorf("resolve running updater path: %w", err)
	}
	live, err = filepath.Abs(live)
	if err != nil {
		return fmt.Errorf("resolve installed updater path: %w", err)
	}
	if !strings.EqualFold(filepath.Clean(exe), filepath.Clean(live)) {
		return fmt.Errorf("running updater is %s, but -dir points to %s; refusing to replace a different executable", exe, live)
	}

	pending := live + ".pending"
	if err := copyFileExclusive(stagedAsset, pending); err != nil {
		return fmt.Errorf("stage verified updater at %s: %w", pending, err)
	}
	if err := spawnWindowsReplacementHelper(os.Getpid(), pending, live, lockPath); err != nil {
		_ = os.Remove(pending)
		return fmt.Errorf("start replacement helper: %w", err)
	}
	// The detached helper now owns the lock lifecycle. It waits for this process,
	// attempts the replacement, and only then removes updater.lock. Keeping the
	// file across process exit prevents a second old updater from pinning the live
	// executable while the helper is trying to replace it.
	transferLock()
	log.Printf("verified updater %s staged at %s; replacement helper will swap it after process exit", strings.TrimPrefix(tag, "v"), pending)
	return nil
}

func copyFileExclusive(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o755)
	if err != nil {
		return err
	}
	ok := false
	defer func() {
		_ = out.Close()
		if !ok {
			_ = os.Remove(dst)
		}
	}()
	if _, err := io.Copy(out, in); err != nil {
		return err
	}
	if err := out.Sync(); err != nil {
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	ok = true
	return nil
}

func powershellLiteral(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "''") + "'"
}

func replacementHelperScript(pid int, pending, live, lockPath string) string {
	return fmt.Sprintf(
		"$ErrorActionPreference='Stop'; Wait-Process -Id %d -ErrorAction SilentlyContinue; try { Move-Item -LiteralPath %s -Destination %s -Force } finally { Remove-Item -LiteralPath %s -Force -ErrorAction SilentlyContinue }",
		pid, powershellLiteral(pending), powershellLiteral(live), powershellLiteral(lockPath),
	)
}

func attestedForRelease(repo, digest, tag string) (int, error) {
	body, err := httpGet(fmt.Sprintf(
		"https://api.github.com/repos/%s/attestations/sha256:%s", repo, digest))
	if err != nil {
		return 0, err
	}
	return countReleaseAttestations(body, repo, digest, tag)
}

func countReleaseAttestations(body []byte, repo, digest, tag string) (int, error) {
	var payload struct {
		Attestations []struct {
			Bundle struct {
				DSSEEnvelope struct {
					Payload string `json:"payload"`
				} `json:"dsseEnvelope"`
			} `json:"bundle"`
		} `json:"attestations"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		return 0, fmt.Errorf("parse GitHub attestations: %w", err)
	}

	wantRepo := normalizeRepository(repo)
	wantRef := "refs/tags/" + strings.TrimPrefix(strings.TrimSpace(tag), "refs/tags/")
	wantDigest := strings.ToLower(strings.TrimSpace(digest))
	matches := 0
	for _, att := range payload.Attestations {
		encoded := strings.TrimSpace(att.Bundle.DSSEEnvelope.Payload)
		if encoded == "" {
			continue
		}
		statementBytes, err := base64.StdEncoding.DecodeString(encoded)
		if err != nil {
			statementBytes, err = base64.RawStdEncoding.DecodeString(encoded)
		}
		if err != nil {
			return 0, fmt.Errorf("decode attestation payload: %w", err)
		}
		var statement struct {
			PredicateType string `json:"predicateType"`
			Subject       []struct {
				Digest map[string]string `json:"digest"`
			} `json:"subject"`
			Predicate struct {
				BuildDefinition struct {
					ExternalParameters struct {
						Workflow struct {
							Ref        string `json:"ref"`
							Repository string `json:"repository"`
							Path       string `json:"path"`
						} `json:"workflow"`
					} `json:"externalParameters"`
				} `json:"buildDefinition"`
			} `json:"predicate"`
		}
		if err := json.Unmarshal(statementBytes, &statement); err != nil {
			return 0, fmt.Errorf("parse attestation statement: %w", err)
		}
		workflow := statement.Predicate.BuildDefinition.ExternalParameters.Workflow
		if statement.PredicateType != "https://slsa.dev/provenance/v1" ||
			workflow.Ref != wantRef ||
			normalizeRepository(workflow.Repository) != wantRepo ||
			strings.SplitN(workflow.Path, "@", 2)[0] != releaseWorkflowPath ||
			!statementHasDigest(statement.Subject, wantDigest) {
			continue
		}
		matches++
	}
	return matches, nil
}

func normalizeRepository(value string) string {
	value = strings.TrimSpace(strings.ToLower(value))
	value = strings.TrimPrefix(value, "https://github.com/")
	value = strings.TrimPrefix(value, "http://github.com/")
	value = strings.TrimPrefix(value, "github.com/")
	value = strings.TrimSuffix(value, ".git")
	return strings.Trim(value, "/")
}

func statementHasDigest(subjects []struct {
	Digest map[string]string `json:"digest"`
}, want string) bool {
	for _, subject := range subjects {
		if strings.EqualFold(strings.TrimSpace(subject.Digest["sha256"]), want) {
			return true
		}
	}
	return false
}
