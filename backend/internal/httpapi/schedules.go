package httpapi

import (
	"net"
	"net/http"
	"net/url"
	"strings"
)

// Schedule administration is intentionally split across two trust boundaries:
// the backend authenticates paired devices, while the worker owns validation,
// standing-grant approval and execution policy. The backend must therefore stay
// a narrow proxy -- and it must only ever talk to the worker over loopback.
//
// The worker independently rejects non-loopback callers. Keeping the same rule
// here makes a bad MODELRIG_WORKER_URL fail before any schedule body is sent to
// an external host, rather than relying on the remote endpoint to be honest.
func scheduleWorkerIsLoopback(raw string) bool {
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

func validScheduleID(id string) bool {
	if len(id) != 12 {
		return false
	}
	for _, r := range id {
		if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f')) {
			return false
		}
	}
	return true
}

func (s *server) forwardSchedule(w http.ResponseWriter, r *http.Request, workerPath string) {
	if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		writeErr(w, http.StatusServiceUnavailable,
			"schedule administration requires a loopback worker upstream")
		return
	}
	s.Worker.Forward(w, r, workerPath)
}

func scheduleIDPath(r *http.Request, suffix string) (string, bool) {
	id := r.PathValue("id")
	if !validScheduleID(id) {
		return "", false
	}
	return "/schedules/" + id + suffix, true
}

func (s *server) handleSchedulesStatus(w http.ResponseWriter, r *http.Request) {
	s.forwardSchedule(w, r, "/schedules/status")
}

func (s *server) handleSchedulesPreview(w http.ResponseWriter, r *http.Request) {
	s.forwardSchedule(w, r, "/schedules/preview")
}

func (s *server) handleSchedulesCollection(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		s.handleScheduleCreate(w, r)
		return
	}
	s.forwardSchedule(w, r, "/schedules")
}

func (s *server) handleScheduleGet(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	s.forwardSchedule(w, r, path)
}

func (s *server) handleScheduleEnabled(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "/enabled")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	s.forwardSchedule(w, r, path)
}

func (s *server) handleScheduleRenewPreview(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "/renew/preview")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	s.forwardSchedule(w, r, path)
}

func (s *server) handleScheduleRenew(w http.ResponseWriter, r *http.Request) {
	path, ok := scheduleIDPath(r, "/renew")
	if !ok {
		writeErr(w, http.StatusBadRequest, "invalid schedule id")
		return
	}
	s.handleScheduleRenewCommit(w, r, path)
}
