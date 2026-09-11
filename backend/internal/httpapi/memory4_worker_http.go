package httpapi

import (
	"net/http"
	"time"
)

// memory4WorkerHTTPClient preserves the loopback-only Memory 4 egress boundary
// across HTTP redirects. The caller has already validated the configured worker
// base URL as loopback; following a 30x would otherwise allow that loopback
// endpoint to replay a private POST body to an arbitrary redirect target.
//
// Returning http.ErrUseLastResponse makes net/http return the original redirect
// response without issuing a second request. Existing Memory 4 status handling
// then treats the non-200 worker response as refusal/failure.
func memory4WorkerHTTPClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout: timeout,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
}
