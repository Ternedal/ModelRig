package main

import (
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"modelrig/internal/startup"
)

type startingChild struct {
	fakeChild
	process procChild
}

func (c *startingChild) startupPending() bool { return c.process.startupPending() }

func newStartingChild() *startingChild {
	return &startingChild{
		fakeChild: fakeChild{nm: "worker", run: true},
		process: procChild{alive: true, startedAt: time.Now(), startupGrace: startup.GracePeriod},
	}
}

func TestSlowFirstBootSurvivesOldThreePollRestartWindow(t *testing.T) {
	c := newStartingChild()
	fails := map[string]int{}
	for age := 10 * time.Second; age <= 70*time.Second; age += 10 * time.Second {
		c.process.startedAt = time.Now().Add(-age)
		fails = superviseOnce([]child{c}, fails, 3, nil)
	}
	if c.restarts != 0 || fails["worker"] != 0 {
		t.Fatalf("live cold boot was interrupted: restarts=%d failures=%d", c.restarts, fails["worker"])
	}
	// A successful response ends startup grace immediately, even at age 70s.
	c.hlth = true
	c.process.markReady()
	superviseOnce([]child{c}, fails, 3, nil)
	c.hlth = false
	for i := 0; i < 3; i++ {
		fails = superviseOnce([]child{c}, fails, 3, nil)
	}
	if c.restarts != 1 {
		t.Fatalf("ready child lost normal watchdog recovery: %d restarts", c.restarts)
	}
}

func TestNeverReadyChildStillRestartsAfterBoundedGrace(t *testing.T) {
	c := newStartingChild()
	c.process.startedAt = time.Now().Add(-startup.GracePeriod - time.Second)
	fails := map[string]int{}
	for i := 0; i < 3; i++ {
		fails = superviseOnce([]child{c}, fails, 3, nil)
	}
	if c.restarts != 1 {
		t.Fatalf("expired startup grace hid a stuck process: %d restarts", c.restarts)
	}
}

func TestCrashDuringGraceRestartsImmediately(t *testing.T) {
	c := newStartingChild()
	c.run = false
	c.process.alive = false
	superviseOnce([]child{c}, nil, 3, nil)
	if c.restarts != 1 {
		t.Fatalf("startup grace delayed crash recovery: %d restarts", c.restarts)
	}
}

func TestActualHealthProbeEndsGraceOnlyOnSuccess(t *testing.T) {
	var status atomic.Int32
	status.Store(http.StatusServiceUnavailable)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(int(status.Load()))
	}))
	defer srv.Close()
	p := &procChild{alive: true, startedAt: time.Now(), startupGrace: startup.GracePeriod, healthURL: srv.URL}
	if p.healthy() || !p.startupPending() {
		t.Fatal("unready response consumed startup grace")
	}
	status.Store(http.StatusOK)
	if !p.healthy() || p.startupPending() {
		t.Fatal("healthy response did not end startup grace")
	}
}
