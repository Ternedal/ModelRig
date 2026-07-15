package httpapi

import (
	"net/http"
	"net/url"
	"strings"
)

// Agent 3.0 is an experimental, feature-flagged worker API. The Go server does
// not implement planning, memory or policy; it remains the authenticated gateway
// and forwards to the loopback-only worker. Routes are registered only when
// KALIV_AGENT3_ENABLED=1.

func agent3Target(r *http.Request, path string) string {
	if r.URL.RawQuery != "" {
		return path + "?" + r.URL.RawQuery
	}
	return path
}

func agent3RunTarget(r *http.Request, suffix string) string {
	id := url.PathEscape(r.PathValue("id"))
	return agent3Target(r, "/experimental/agent3/runs/"+id+suffix)
}

func agent3PlanTarget(r *http.Request) string {
	id := url.PathEscape(r.PathValue("id"))
	return agent3Target(r, "/experimental/agent3/plans/"+id+"/start")
}

func agent3MemoryTarget(r *http.Request) string {
	const publicPrefix = "/api/v1/experimental/agent3/memory"
	suffix := strings.TrimPrefix(r.URL.Path, publicPrefix)
	return agent3Target(r, "/experimental/agent3/memory"+suffix)
}

func (s *server) handleAgent3Status(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, agent3Target(r, "/experimental/agent3/status"))
}

func (s *server) handleAgent3Plan(w http.ResponseWriter, r *http.Request) {
	// Planning invokes the local LLM but never executes a tool.
	s.WorkerSlow.Forward(w, r, agent3Target(r, "/experimental/agent3/plan"))
}

func (s *server) handleAgent3PlanStart(w http.ResponseWriter, r *http.Request) {
	// A reviewed single-use plan may immediately run reads or park on a write.
	s.WorkerSlow.Forward(w, r, agent3PlanTarget(r))
}

func (s *server) handleAgent3Memory(w http.ResponseWriter, r *http.Request) {
	// Memory CRUD is local SQLite work and never calls a model.
	s.Worker.Forward(w, r, agent3MemoryTarget(r))
}

func (s *server) handleAgent3RunsList(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, agent3Target(r, "/experimental/agent3/runs"))
}

func (s *server) handleAgent3RunsStart(w http.ResponseWriter, r *http.Request) {
	// A run may execute several read steps or wait on a model-backed adapter in a
	// later phase, so use the long-lived worker proxy just like /tools/chat.
	s.WorkerSlow.Forward(w, r, agent3Target(r, "/experimental/agent3/runs"))
}

func (s *server) handleAgent3RunGet(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, agent3RunTarget(r, ""))
}

func (s *server) handleAgent3RunEvents(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, agent3RunTarget(r, "/events"))
}

func (s *server) handleAgent3RunConfirm(w http.ResponseWriter, r *http.Request) {
	// Approval can execute a write and then advance the run.
	s.WorkerSlow.Forward(w, r, agent3RunTarget(r, "/confirm"))
}

func (s *server) handleAgent3RunResume(w http.ResponseWriter, r *http.Request) {
	s.WorkerSlow.Forward(w, r, agent3RunTarget(r, "/resume"))
}

func (s *server) handleAgent3RunCancel(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, agent3RunTarget(r, "/cancel"))
}
