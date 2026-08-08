//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

func init() {
	exe, err := os.Executable()
	if err != nil {
		return
	}
	// Package init functions also run in the real-Windows Go test binary. Never
	// launch detached orchestration from tests; the argument parser provides a
	// second guard for -test.* invocations.
	if strings.HasSuffix(strings.ToLower(filepath.Base(exe)), ".test.exe") {
		return
	}
	root, err := os.Getwd()
	if err != nil {
		fmt.Fprintln(os.Stderr, "updater automatic self-update watcher:", err)
		return
	}
	cfg, mode, err := parseAutomaticSelfUpdateArgs(os.Args[1:], root)
	if err != nil {
		fmt.Fprintln(os.Stderr, "updater automatic self-update watcher:", err)
		return
	}
	if mode != automaticSelfUpdateWatch {
		return
	}
	baseline, err := committedTransactionFingerprints(cfg.root)
	if err != nil {
		// Automatic self-update is deliberately non-gating. Ambiguous forensic
		// evidence disables only this follow-up; main retains its own strict
		// journal/recovery behaviour and continues normally.
		fmt.Fprintln(os.Stderr, "updater automatic self-update watcher disabled:", err)
		return
	}
	cfg.baseline = baseline
	logPath := filepath.Join(cfg.root, "logs", "updater-self-update.log")
	if err := spawnAutomaticSelfUpdateWatcher(os.Getpid(), exe, logPath, cfg); err != nil {
		fmt.Fprintln(os.Stderr, "updater automatic self-update watcher:", err)
	}
}

func spawnAutomaticSelfUpdateWatcher(parentPID int, updaterExe, logPath string, cfg automaticSelfUpdateConfig) error {
	script := automaticSelfUpdateWatcherScript(parentPID, updaterExe, logPath, cfg)
	cmd := exec.Command(
		"powershell.exe",
		"-NoProfile",
		"-NonInteractive",
		"-WindowStyle", "Hidden",
		"-Command", script,
	)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: createNewProcessGroup | detachedProcess,
	}
	return cmd.Start()
}

func automaticSelfUpdateWatcherScript(parentPID int, updaterExe, logPath string, cfg automaticSelfUpdateConfig) string {
	logDir := filepath.Dir(logPath)
	childArgs := []string{
		postCommitSelfUpdateArg,
		"-dir", cfg.root,
		"-repo", cfg.repo,
	}
	for _, fingerprint := range cfg.baseline {
		childArgs = append(childArgs, "-baseline-commit="+fingerprint)
	}
	if cfg.skipVerify {
		childArgs = append(childArgs, "-insecure-skip-verify")
	}
	if cfg.skipAttestation {
		childArgs = append(childArgs, "-skip-attestation")
	}
	quotedArgs := make([]string, len(childArgs))
	for i, arg := range childArgs {
		quotedArgs[i] = powershellLiteral(arg)
	}
	return fmt.Sprintf(
		"$ErrorActionPreference='Stop'; "+
			"Wait-Process -Id %d -ErrorAction SilentlyContinue; "+
			"New-Item -ItemType Directory -Path %s -Force | Out-Null; "+
			"try { & %s %s *>> %s; "+
			"if ($LASTEXITCODE -ne 0) { Add-Content -LiteralPath %s -Value ('post-commit self-update exited ' + $LASTEXITCODE) } } "+
			"catch { Add-Content -LiteralPath %s -Value ('post-commit self-update launcher failed: ' + $_.Exception.Message) }; exit 0",
		parentPID,
		powershellLiteral(logDir),
		powershellLiteral(updaterExe),
		strings.Join(quotedArgs, " "),
		powershellLiteral(logPath),
		powershellLiteral(logPath),
		powershellLiteral(logPath),
	)
}
