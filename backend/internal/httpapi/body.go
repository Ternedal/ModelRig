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

// Live frames (slice B). /frames is a server-sent event stream the renderer
// holds open; it rides the slow worker client, which flushes per chunk and
// carries the long timeout. Interrupt and state reports are POSTs the
// client makes about what only it knows (mic open, user gone, barge-in).

var bodyStateRe = regexp.MustCompile(`^[a-z_]{1,32}$`)

func (s *server) handleBodyState(w http.ResponseWriter, r *http.Request) {
	s.forwardBody(w, r, "/body/state")
}

func (s *server) handleBodyFrames(w http.ResponseWriter, r *http.Request) {
	// An intentionally unbounded stream. http.Client.Timeout covers the
	// whole exchange including the body, so the slow client's ten minutes
	// would cut every stream on the clock and freeze the avatar for the
	// reconnect delay. No timeout here: the upstream request carries the
	// client's context, so a renderer that disconnects ends the stream on
	// the rig -- the client, not a timer, decides how long a body is watched.
	if s.Worker == nil || !scheduleWorkerIsLoopback(s.Worker.BaseURL) {
		writeErr(w, http.StatusServiceUnavailable, "body assets require a loopback worker upstream")
		return
	}
	s.WorkerSlow.WithTimeout(0).Forward(w, r, "/body/frames")
}

func (s *server) handleBodyInterrupt(w http.ResponseWriter, r *http.Request) {
	s.forwardBody(w, r, "/body/interrupt")
}

func (s *server) handleBodySetState(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	if !bodyStateRe.MatchString(name) {
		writeErr(w, http.StatusNotFound, "unknown body state")
		return
	}
	s.forwardBody(w, r, "/body/state/"+name)
}

// Playback reports (slice B, sync). The phone tells the rig when a sentence
// actually starts and stops playing, so the mouth follows the speaker rather
// than the synthesizer. Utterance ids are the worker's own "voice-<hex>-<n>".

var bodyUtteranceRe = regexp.MustCompile(`^[A-Za-z0-9._:-]{1,80}$`)

func (s *server) handleBodySpeech(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("utterance")
	event := r.PathValue("event")
	if !bodyUtteranceRe.MatchString(id) || (event != "started" && event != "ended") {
		writeErr(w, http.StatusNotFound, "unknown speech event")
		return
	}
	s.forwardBody(w, r, "/body/speech/"+id+"/"+event)
}
