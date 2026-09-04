package httpapi

import (
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
)

// T-044 consumes the T-036 worker pilot through the same two-boundary model as
// schedule administration: paired-device Bearer auth at the Go backend, then a
// worker endpoint that is reachable only over loopback. The worker independently
// re-checks loopback for both observability and grant mutations.
func githubConnectorPilotEnabled() bool {
	// Keep the canonical off-by-default decision syntactically explicit. The
	// readiness generator deliberately recognises only unambiguous Go switches;
	// the normalized fallback preserves the worker-compatible aliases and
	// whitespace handling without making readiness infer semantics from a parser.
	if os.Getenv("KALIV_GITHUB_CONNECTOR_PILOT") == "1" {
		return true
	}
	switch strings.ToLower(strings.TrimSpace(os.Getenv("KALIV_GITHUB_CONNECTOR_PILOT"))) {
	case "1", "true", "on":
		return true
	default:
		return false
	}
}

func githubConnectorWorkerIsLoopback(raw string) bool {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") {
		return false
	}
	host := strings.TrimSuffix(strings.ToLower(u.Hostname()), ".")
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func validGitHubGrantID(id string) bool {
	if len(id) != 36 || !strings.HasPrefix(id, "ghg_") {
		return false
	}
	for _, r := range id[4:] {
		if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f')) {
			return false
		}
	}
	return true
}

func (s *server) forwardGitHubConnector(w http.ResponseWriter, r *http.Request, workerPath string) {
	if s.Worker == nil || !githubConnectorWorkerIsLoopback(s.Worker.BaseURL) {
		writeErr(w, http.StatusServiceUnavailable,
			"GitHub connector administration requires a loopback worker upstream")
		return
	}
	s.Worker.Forward(w, r, workerPath)
}

func (s *server) handleGitHubConnectorGrants(w http.ResponseWriter, r *http.Request) {
	s.forwardGitHubConnector(w, r, "/github-connector/grants")
}

func (s *server) handleGitHubConnectorGrantPreview(w http.ResponseWriter, r *http.Request) {
	s.forwardGitHubConnector(w, r, "/github-connector/grants/preview")
}

func (s *server) handleGitHubConnectorGrantRevoke(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if !validGitHubGrantID(id) {
		writeErr(w, http.StatusBadRequest, "invalid GitHub connector grant id")
		return
	}
	s.forwardGitHubConnector(w, r, "/github-connector/grants/"+id+"/revoke")
}

func (s *server) handleGitHubConnectorAudit(w http.ResponseWriter, r *http.Request) {
	s.forwardGitHubConnector(w, r, "/github-connector/audit")
}
