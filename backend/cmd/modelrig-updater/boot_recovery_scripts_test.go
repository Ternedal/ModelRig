package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func repositoryFile(t *testing.T, parts ...string) string {
	t.Helper()
	_, testFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot resolve updater test source path")
	}
	root := filepath.Clean(filepath.Join(filepath.Dir(testFile), "..", "..", ".."))
	path := filepath.Join(append([]string{root}, parts...)...)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return string(data)
}

func repositoryScript(t *testing.T, name string) string {
	t.Helper()
	return repositoryFile(t, "scripts", name)
}

func requireContains(t *testing.T, text, want, claim string) {
	t.Helper()
	if !strings.Contains(text, want) {
		t.Fatalf("%s: missing %q", claim, want)
	}
}

func TestBootstrapRecoversBeforeStartingSupervisor(t *testing.T) {
	bootstrap := repositoryScript(t, "kaliv-bootstrap.ps1")
	recovery := "& $updater -dir $RepoRoot -recover -supervisor-task $SupervisorTaskName"
	start := "Start-ScheduledTask -TaskName $SupervisorTaskName"
	recoveryAt := strings.Index(bootstrap, recovery)
	startAt := strings.Index(bootstrap, start)
	if recoveryAt < 0 {
		t.Fatalf("bootstrap does not invoke updater offline recovery: missing %q", recovery)
	}
	if startAt < 0 {
		t.Fatalf("bootstrap does not start the supervisor after recovery: missing %q", start)
	}
	if recoveryAt >= startAt {
		t.Fatalf("supervisor startup appears before recovery (recovery=%d, start=%d)", recoveryAt, startAt)
	}
	requireContains(t, bootstrap, "$recoveryExitCode = $LASTEXITCODE", "native updater exit code is captured")
	requireContains(t, bootstrap, "if ($recoveryExitCode -ne 0)", "non-zero recovery fails closed")
	requireContains(t, bootstrap, "The supervisor was not started", "failure explains that startup was withheld")
	requireContains(t, bootstrap, "Test-Path -LiteralPath $updater -PathType Leaf", "missing updater blocks startup")
}

func TestAutostartSeparatesBootstrapAndSupervisorTasks(t *testing.T) {
	autostart := repositoryScript(t, "kaliv-autostart.ps1")
	requireContains(t, autostart, "-TaskName \"KalivBootstrap\"", "bootstrap task is registered")
	requireContains(t, autostart, "-TaskName \"KalivSupervisor\"", "supervisor task is registered")
	requireContains(t, autostart, "$bootstrapTrigger = New-ScheduledTaskTrigger -AtLogOn", "logon trigger belongs to bootstrap")
	requireContains(t, autostart, "-File `\"$bootstrap`\"", "bootstrap task executes the checked-in script")
	requireContains(t, autostart, "modelrig-updater-windows-x64.exe", "registration requires the updater")
	requireContains(t, autostart, "kaliv-bootstrap.ps1", "registration requires the bootstrap script")

	firstRegistration := strings.Index(autostart, "Register-ScheduledTask")
	if firstRegistration < 0 {
		t.Fatal("supervisor task registration is missing")
	}
	secondRelative := strings.Index(autostart[firstRegistration+1:], "Register-ScheduledTask")
	if secondRelative < 0 {
		t.Fatal("bootstrap task registration is missing")
	}
	secondRegistration := firstRegistration + 1 + secondRelative
	supervisorRegistration := autostart[firstRegistration:secondRegistration]
	if strings.Contains(supervisorRegistration, "-Trigger") {
		t.Fatalf("supervisor task has a direct trigger and can race recovery:\n%s", supervisorRegistration)
	}
}

func TestOperatorDocumentationCannotBypassRecovery(t *testing.T) {
	readme := repositoryFile(t, "deploy", "README.md")
	requireContains(t, readme, "modelrig-updater-windows-x64.exe` in the ModelRig root", "fresh appliance prerequisites include the updater")
	requireContains(t, readme, "Mandatory migration for an existing appliance", "existing rigs receive an explicit migration procedure")
	requireContains(t, readme, "normal\nbinary update does **not** rewrite Windows Task Scheduler definitions", "migration explains why normal updates are insufficient")
	requireContains(t, readme, "(Get-ScheduledTask -TaskName KalivSupervisor).Triggers.Count  # must be 0", "migration verifies the old direct trigger is gone")
	requireContains(t, readme, "Start-ScheduledTask -TaskName KalivBootstrap", "documented manual start routes through recovery")
	requireContains(t, readme, "Do not start `KalivSupervisor` directly", "direct supervisor starts are explicitly prohibited")
}
