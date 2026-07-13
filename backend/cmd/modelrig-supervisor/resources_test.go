package main

import "testing"

func TestShouldWarnDisk(t *testing.T) {
	if warn, _ := shouldWarnDisk(3.0, 5.0); !warn {
		t.Error("3 GB free with a 5 GB floor should warn")
	}
	if warn, _ := shouldWarnDisk(50.0, 5.0); warn {
		t.Error("50 GB free with a 5 GB floor should NOT warn")
	}
	// The message names both numbers so the log is actionable.
	if _, msg := shouldWarnDisk(2.5, 5.0); msg == "" {
		t.Error("a warning should carry a message")
	}
}

func TestParseNvidiaSmi(t *testing.T) {
	used, total, err := parseNvidiaSmi("1234, 12288\n")
	if err != nil {
		t.Fatal(err)
	}
	if used != 1234 || total != 12288 {
		t.Fatalf("parsed used=%d total=%d, want 1234/12288", used, total)
	}
	// Multi-GPU: first line wins (the rig has one GPU; be defensive anyway).
	if u, tot, err := parseNvidiaSmi("500, 8192\n600, 8192\n"); err != nil || u != 500 || tot != 8192 {
		t.Fatalf("multi-line: used=%d total=%d err=%v", u, tot, err)
	}
	if _, _, err := parseNvidiaSmi(""); err == nil {
		t.Error("empty output should error")
	}
	if _, _, err := parseNvidiaSmi("garbage"); err == nil {
		t.Error("malformed output should error")
	}
}

func TestShouldWarnVram(t *testing.T) {
	// 11.7 / 12 GiB ~ 97.5% -> warn at 95%.
	if warn, _ := shouldWarnVram(11980, 12288, 95.0); !warn {
		t.Error("97% VRAM should warn at a 95% threshold")
	}
	if warn, _ := shouldWarnVram(4000, 12288, 95.0); warn {
		t.Error("33% VRAM should NOT warn at a 95% threshold")
	}
	// total=0 (nvidia-smi absent / odd output) must not divide by zero or warn.
	if warn, _ := shouldWarnVram(0, 0, 95.0); warn {
		t.Error("total=0 should not warn")
	}
}
