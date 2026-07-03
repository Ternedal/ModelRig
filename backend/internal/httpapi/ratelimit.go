package httpapi

import (
	"sync"
	"time"
)

// rateLimiter is a simple per-key sliding-window limiter. Used to throttle
// pairing-claim attempts so the 8-char code space can't be brute-forced.
// In-memory only (fine for a single-node LAN server); resets on restart.
type rateLimiter struct {
	mu     sync.Mutex
	max    int
	window time.Duration
	hits   map[string][]time.Time
}

func newRateLimiter(max int, window time.Duration) *rateLimiter {
	return &rateLimiter{max: max, window: window, hits: make(map[string][]time.Time)}
}

// allow records an attempt for key and reports whether it is within the limit.
func (r *rateLimiter) allow(key string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := time.Now()
	cutoff := now.Add(-r.window)

	kept := make([]time.Time, 0, len(r.hits[key])+1)
	for _, t := range r.hits[key] {
		if t.After(cutoff) {
			kept = append(kept, t)
		}
	}
	if len(kept) >= r.max {
		r.hits[key] = kept
		return false
	}
	kept = append(kept, now)
	r.hits[key] = kept
	return true
}

// sweep drops empty/expired buckets so the map doesn't grow unbounded.
func (r *rateLimiter) sweep() {
	r.mu.Lock()
	defer r.mu.Unlock()
	cutoff := time.Now().Add(-r.window)
	for k, times := range r.hits {
		alive := false
		for _, t := range times {
			if t.After(cutoff) {
				alive = true
				break
			}
		}
		if !alive {
			delete(r.hits, k)
		}
	}
}
