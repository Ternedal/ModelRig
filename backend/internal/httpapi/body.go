package httpapi

import (
	"net/http"
	"regexp"
	"strings"
)

// Body assets (Unity renderer roadmap, slice A). The worker serves the active
// body's validated avatar, thumbnail and motions; this is the remote boundary
// phones and headsets go through: Bearer-authenticated, loopback worker only,
// and a closed set of paths. Motion names are validated here so a request can
// never carry a path segment into the worker.

var bodyMotionRe = regexp.MustCompile(`^[a-z0-9_]{1,32}$`)

func (s *server) forwardBody(w http.ResponseWriter, r *http.Request, workerPath string) {
	if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		writeErr(w, http.StatusServiceUnavailable, "body assets require a loopback worker upstream")
		return
	}
	s.WorkerSlow.Forward(w, r, workerPath)
}

func (s *server) handleBodyActive(w http.ResponseWriter, r *http.Request) {
	s.forwardBody(w, r, "/body/active")
}

func (s *server) handleBodyAvatar(w http.ResponseWriter, r *http.Request) {
	s.forwardBody(w, r, "/body/active/avatar.vrm")
}

func (s *server) handleBodyThumbnail(w http.ResponseWriter, r *http.Request) {
	s.forwardBody(w, r, "/body/active/thumbnail.png")
}

func (s *server) handleBodyMotion(w http.ResponseWriter, r *http.Request) {
	file := r.PathValue("file")
	name, ok := strings.CutSuffix(file, ".vrma")
	if !ok || !bodyMotionRe.MatchString(name) {
		writeErr(w, http.StatusNotFound, "unknown motion")
		return
	}
	s.forwardBody(w, r, "/body/active/motions/"+name+".vrma")
}
