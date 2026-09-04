package httpapi

import (
	"net/http"
	"regexp"
)

// Person Profile registry (#752). The worker owns the registry and its one
// invariant -- body, voice and personality are only ever activated together,
// through an approved Person Revision. This file is the remote boundary:
// Bearer-authenticated, loopback-worker only, ids validated, and the set of
// forwarded sub-routes is a closed allowlist. There is deliberately no
// backend route that could be used to activate a single component, so even
// a worker change could not open one to the LAN without a matching change
// here.

var personIDRe = regexp.MustCompile(`^person-[0-9a-f]{32}$`)

// personSubRoutes is the closed set of per-person actions the backend
// forwards. Adding an entry here is an API decision, not a refactor.
var personSubRoutes = map[string]bool{
	"body-revisions":        true,
	"voice-revisions":       true,
	"personality-revisions": true,
	"person-revisions":      true,
	"activate":              true,
}

func (s *server) forwardPersons(w http.ResponseWriter, r *http.Request, workerPath string) {
	if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		writeErr(w, http.StatusServiceUnavailable,
			"person registry requires a loopback worker upstream")
		return
	}
	s.Worker.Forward(w, r, workerPath)
}

func (s *server) handlePersonsCollection(w http.ResponseWriter, r *http.Request) {
	s.forwardPersons(w, r, "/persons")
}

func (s *server) handlePersonsActive(w http.ResponseWriter, r *http.Request) {
	s.forwardPersons(w, r, "/persons/active")
}

func (s *server) handlePersonsSelect(w http.ResponseWriter, r *http.Request) {
	s.forwardPersons(w, r, "/persons/select")
}

func (s *server) handlePersonGet(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if !personIDRe.MatchString(id) {
		writeErr(w, http.StatusNotFound, "unknown person")
		return
	}
	s.forwardPersons(w, r, "/persons/"+id)
}

func (s *server) handlePersonAction(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	action := r.PathValue("action")
	if !personIDRe.MatchString(id) {
		writeErr(w, http.StatusNotFound, "unknown person")
		return
	}
	if !personSubRoutes[action] {
		writeErr(w, http.StatusNotFound, "unknown person action")
		return
	}
	s.forwardPersons(w, r, "/persons/"+id+"/"+action)
}
