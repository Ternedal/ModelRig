package config

import "testing"

func TestSchedulerApprovalPrivateKeyLoadsOnlyFromExplicitEnv(t *testing.T) {
	t.Setenv("KALIV_SCHEDULER_APPROVAL_PRIVATE_KEY", "private-seed")
	cfg, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.SchedulerApprovalPrivateKey != "private-seed" {
		t.Fatalf("scheduler approval private key not loaded: %q", cfg.SchedulerApprovalPrivateKey)
	}
	if Default().SchedulerApprovalPrivateKey != "" {
		t.Fatal("scheduler approval signing must be off by default")
	}
}
