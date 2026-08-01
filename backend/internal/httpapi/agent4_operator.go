package httpapi

import (
	"net/http"
	"strings"

	"modelrig/internal/store"
)

// Agent 4 operator reads (ADR-A4-007): the backend is the single
// authenticated door to the worker-hosted, default-off, GET-only operator
// read surface. Transport is backend-proxied ONLY — the worker keeps its
// loopback invariant, and no new listen surface exists.
//
// Authorization is two-layered by decision: the normal paired-device Bearer
// (authMW) proves "my device"; the explicit per-device “agent4:read“ grant
// proves "may read orchestrator-internal campaign and evidence data". The
// grant is absent by default for every device, including ones paired before
// the field existed. Granting is an explicit operator action on the store —
// nothing mints grants automatically, and this slice deliberately ships no
// HTTP surface for granting.
const agent4ReadGrant = "agent4:read"

func (s *server) handleAgent4OperatorRead(w http.ResponseWriter, r *http.Request) {
	// Layer 2: the explicit read grant. authMW already proved the Bearer and
	// put the device on the context — reuse it, never re-derive.
	dv, ok := r.Context().Value(deviceKey).(store.Device)
	if !ok || !dv.HasGrant(agent4ReadGrant) {
		writeErr(w, http.StatusForbidden, "agent4 read grant required")
		return
	}

	// Raw pass-through via the house forwarder: the worker serialises the
	// canonical hash-bound payloads (ADR-A4-007, decision 6), and Forward
	// streams status, headers and body back without re-serialising.
	s.Worker.Forward(w, r, strings.TrimPrefix(r.URL.Path, "/api/v1"))
}
