//go:build windows

package main

import (
	"strings"
	"testing"
)

func TestAutomaticSelfUpdateWatcherWaitsThenChecksCommittedTransaction(t *testing.T) {
	fingerprint := strings.Repeat("ab", 32)
	cfg := automaticSelfUpdateConfig{
		root:            `C:\ModelRig`,
		repo:            "Example/Repo",
		skipVerify:      true,
		skipAttestation: true,
		baseline:        []string{fingerprint},
	}
	script := automaticSelfUpdateWatcherScript(
		4242,
		`C:\ModelRig\modelrig-updater-windows-x64.exe`,
		`C:\ModelRig\logs\updater-self-update.log`,
		cfg,
	)
	for _, required := range []string{
		"Wait-Process -Id 4242",
		postCommitSelfUpdateArg,
		"-baseline-commit=" + fingerprint,
		"-insecure-skip-verify",
		"-skip-attestation",
		`C:\ModelRig\logs\updater-self-update.log`,
		"post-commit self-update exited",
		"post-commit self-update launcher failed",
		"exit 0",
	} {
		if !strings.Contains(script, required) {
			t.Fatalf("watcher script missing %q:\n%s", required, script)
		}
	}
	waitAt := strings.Index(script, "Wait-Process")
	childAt := strings.Index(script, postCommitSelfUpdateArg)
	if waitAt < 0 || childAt < 0 || waitAt >= childAt {
		t.Fatalf("post-commit child can run before parent exit: %s", script)
	}
	if strings.Contains(script, "'-self-update'") {
		t.Fatalf("watcher bypasses committed-journal decision and invokes self-update directly: %s", script)
	}
}
