package httpapi

import (
	"net/http"
	"time"
)

// memory4WorkerClient preserves the loopback-only authority boundary across
// HTTP semantics. Memory 4 worker requests may contain private query/turn data,
// so a loopback endpoint cannot delegate that request to another destination
// through a redirect.
func memory4WorkerClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Timeout: timeout,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
}
