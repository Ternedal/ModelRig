package httpapi

import (
	"net/http"
	"net/url"
	"strings"
)

// Agent 3.0 is an experimental, feature-flagged worker API. The Go server does
// not implement planning, memory, replanning or policy; it remains the
// authenticated gateway and forwards to the loopback-only worker. Routes are
// registered only when KALIV_AGENT3_ENABLED=1.

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

func agent3TaskPlanTarget(r *http.Request) string {
	id := url.PathEscape(r.PathValue("id"))
	return agent3Target(r, "/experimental/agent3/task/plans/"+id+"/start")
}

func agent3TaskRunTarget(r *http.Request, suffix string) string {
	id := url.PathEscape(r.PathValue("id"))
	return agent3Target(r, "/experimental/agent3/task/runs/"+id+suffix)
}

func agent3ReplanPreviewTarget(r *http.Request) string {
	id := url.PathEscape(r.PathValue("id"))
	return agent3Target(r, "/experimental/agent3/replan-previews/"+id+"/apply")
}

func agent3MemoryTarget(r *http.Request) string {
	const publicPrefix = "/api/v1/experimental/agent3/memory"
	suffix := strings.TrimPrefix(r.URL.Path, publicPrefix)
	return agent3Target(r, "/experimental/agent3/memory"+suffix)
}

func (s *server) handleAgent3Status(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, agent3Target(r, "/experimental/agent3/status"))
}

func (s *server) handleAgent3TaskReadiness(w http.ResponseWriter, r *http.Request) {
	// Observational and read-only. The worker owns the evidence evaluation and
	// surface decision; this authenticated gateway cannot invoke a model/tool,
	// alter normal chat or activate production.
	s.Worker.Forward(w, r, agent3Target(r, "/experimental/agent3/task-readiness"))
}

func (s *server) handleAgent3TaskPlan(w http.ResponseWriter, r *http.Request) {
	// The worker owns readiness, route, risk and evidence binding. Planning may
	// cold-load the local model but never executes a tool, so use the long worker
	// timeout without adding any backend interpretation or fallback.
	s.WorkerSlow.Forward(w, r, agent3Target(r, "/experimental/agent3/task/plan"))
}

func (s *server) handleAgent3TaskPlanStart(w http.ResponseWriter, r *http.Request) {
	// Start returns a persisted run id before the read completes. The worker owns
	// the bounded execution pool and the single-use evidence-bound token.
	s.WorkerSlow.Forward(w, r, agent3TaskPlanTarget(r))
}

func (s *server) handleAgent3TaskRunGet(w http.ResponseWriter, r *http.Request) {
	// Status remains reachable after readiness falls back to Agent 2. The worker
	// exposes only runs carrying its task_surface_bound journal event.
	s.Worker.Forward(w, r, agent3TaskRunTarget(r, ""))
}

func (s *server) handleAgent3TaskRunCancel(w http.ResponseWriter, r *http.Request) {
	// Stop targets the persisted rig run and must stay fast even while a read is
	// in flight. The dedicated worker route refuses generic Agent 3 run ids.
	s.Worker.Forward(w, r, agent3TaskRunTarget(r, "/cancel"))
}

func (s *server) handleAgent3Capabilities(w http.ResponseWriter, r *http.Request) {
	// The graph is observational only: it cannot route, enable tools or promote Agent 3.0.
	s.Worker.Forward(w, r, agent3Target(r, "/experimental/agent3/capabilities"))
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

func (s *server) handleAgent3RunRetry(w http.ResponseWriter, r *http.Request) {
	// Retry clones the stored request, route and validated plan. The body may
	// report cloud-key readiness only; it cannot replace any executable step.
	s.WorkerSlow.Forward(w, r, agent3RunTarget(r, "/retry"))
}

func (s *server) handleAgent3RunGet(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, agent3RunTarget(r, ""))
}

func (s *server) handleAgent3RunEvents(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, agent3RunTarget(r, "/events"))
}

func (s *server) handleAgent3RunCapabilityReceipt(w http.ResponseWriter, r *http.Request) {
	// The receipt evaluates a stored run against the current read-only graph. It
	// returns hashes and blockers only and never advances or executes the run.
	s.Worker.Forward(w, r, agent3RunTarget(r, "/capability-receipt"))
}

func (s *server) handleAgent3RunReplans(w http.ResponseWriter, r *http.Request) {
	// Replan history and recovery are local journal reads.
	s.Worker.Forward(w, r, agent3RunTarget(r, "/replans"))
}

func (s *server) handleAgent3RunReplanPreview(w http.ResponseWriter, r *http.Request) {
	// Preview invokes the local read-only replanner model but cannot mutate the run.
	s.WorkerSlow.Forward(w, r, agent3RunTarget(r, "/replan-preview"))
}

func (s *server) handleAgent3RunAnswerPreview(w http.ResponseWriter, r *http.Request) {
	// Answer preview invokes a local answer-only model over bounded, redacted
	// successful tool results. It never persists or delivers the synthesized text.
	s.WorkerSlow.Forward(w, r, agent3RunTarget(r, "/answer-preview"))
}

func (s *server) handleAgent3ReplanPreviewApply(w http.ResponseWriter, r *http.Request) {
	// Apply consumes a reviewed single-use token. The request cannot supply a new
	// plan or tool arguments and does not invoke the model again.
	s.Worker.Forward(w, r, agent3ReplanPreviewTarget(r))
}

func (s *server) handleAgent3RunConfirm(w http.ResponseWriter, r *http.Request) {
	// Denials remain direct and side-effect free. An approval is rebound to the
	// current worker checkpoint and authenticated device before the backend sends
	// a short-lived one-use token over loopback.
	s.handleAgent3ApprovalConfirm(w, r)
}

func (s *server) handleAgent3RunResume(w http.ResponseWriter, r *http.Request) {
	s.WorkerSlow.Forward(w, r, agent3RunTarget(r, "/resume"))
}

func (s *server) handleAgent3RunCancel(w http.ResponseWriter, r *http.Request) {
	s.Worker.Forward(w, r, agent3RunTarget(r, "/cancel"))
}
