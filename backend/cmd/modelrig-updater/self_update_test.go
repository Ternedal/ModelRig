package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseSelfUpdateArgs(t *testing.T) {
	root := t.TempDir()
	cfg, err := parseSelfUpdateArgs([]string{
		"-self-update",
		"-repo", "Example/Repo",
		"-dir", root,
		"-skip-attestation",
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.repo != "Example/Repo" {
		t.Fatalf("repo = %q", cfg.repo)
	}
	wantRoot, _ := filepath.Abs(root)
	if cfg.root != wantRoot {
		t.Fatalf("root = %q, want %q", cfg.root, wantRoot)
	}
	if !cfg.skipAttestation || cfg.skipVerify {
		t.Fatalf("flags parsed incorrectly: %+v", cfg)
	}
}

func TestParseSelfUpdateArgsRejectsUnknownArgument(t *testing.T) {
	if _, err := parseSelfUpdateArgs([]string{"-self-update", "-current", "1.2.3"}); err == nil {
		t.Fatal("unknown normal-update flags must not silently change self-update behaviour")
	}
}

func TestResolveUpdaterVersionPrefersEmbeddedVersion(t *testing.T) {
	old := updaterVersion
	defer func() { updaterVersion = old }()
	updaterVersion = "v9.8.7"
	if got := resolveUpdaterVersion(t.TempDir()); got != "9.8.7" {
		t.Fatalf("version = %q", got)
	}
}

func TestResolveUpdaterVersionFallsBackToVersionFile(t *testing.T) {
	old := updaterVersion
	defer func() { updaterVersion = old }()
	updaterVersion = "dev"
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "VERSION"), []byte("1.58.151\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got := resolveUpdaterVersion(root); got != "1.58.151" {
		t.Fatalf("version = %q", got)
	}
}

func TestResolveUpdaterVersionFailsClosedToDev(t *testing.T) {
	old := updaterVersion
	defer func() { updaterVersion = old }()
	updaterVersion = "not-semver"
	if got := resolveUpdaterVersion(t.TempDir()); got != "dev" {
		t.Fatalf("version = %q, want dev", got)
	}
}

func TestCopyFileExclusive(t *testing.T) {
	root := t.TempDir()
	src := filepath.Join(root, "new.exe")
	dst := filepath.Join(root, "live.exe.pending")
	if err := os.WriteFile(src, []byte("NEW"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := copyFileExclusive(src, dst); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(dst)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "NEW" {
		t.Fatalf("pending = %q", b)
	}
	if err := copyFileExclusive(src, dst); err == nil {
		t.Fatal("existing pending file must fail closed instead of being overwritten")
	}
	b, err = os.ReadFile(dst)
	if err != nil || string(b) != "NEW" {
		t.Fatalf("existing pending changed after refused overwrite: %q, %v", b, err)
	}
}

func TestPowerShellLiteralEscapesSingleQuote(t *testing.T) {
	if got, want := powershellLiteral(`C:\Anders's Rig\updater.exe`), `'C:\Anders''s Rig\updater.exe'`; got != want {
		t.Fatalf("literal = %q, want %q", got, want)
	}
}

func TestReplacementHelperWaitsThenMovesPending(t *testing.T) {
	script := replacementHelperScript(1234, `C:\Rig\updater.exe.pending`, `C:\Rig\updater.exe`)
	for _, required := range []string{
		"Wait-Process -Id 1234",
		"-ErrorAction SilentlyContinue",
		"Move-Item -LiteralPath 'C:\\Rig\\updater.exe.pending'",
		"-Destination 'C:\\Rig\\updater.exe' -Force",
	} {
		if !strings.Contains(script, required) {
			t.Fatalf("helper script missing %q: %s", required, script)
		}
	}
	if strings.Index(script, "Wait-Process") > strings.Index(script, "Move-Item") {
		t.Fatalf("helper moves before the updater exits: %s", script)
	}
}
