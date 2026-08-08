package main

import (
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"

	"modelrig/internal/config"
)

const updaterAssetName = "modelrig-updater-windows-x64.exe"

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
	defer releaseLock(lockPath)
	return runSelfUpdate(cfg)
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

func runSelfUpdate(cfg selfUpdateConfig) error {
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
			if err := verifyProvenance([]target{{asset: updaterAssetName}}, staged, cfg.repo, attestedBy); err != nil {
				return err
			}
		} else {
			log.Printf("WARNING: updater self-update without provenance verification (-skip-attestation)")
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
	if err := spawnWindowsReplacementHelper(os.Getpid(), pending, live); err != nil {
		_ = os.Remove(pending)
		return fmt.Errorf("start replacement helper: %w", err)
	}
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

func replacementHelperScript(pid int, pending, live string) string {
	return fmt.Sprintf(
		"$ErrorActionPreference='Stop'; Wait-Process -Id %d -ErrorAction SilentlyContinue; Move-Item -LiteralPath %s -Destination %s -Force",
		pid, powershellLiteral(pending), powershellLiteral(live),
	)
}
