package httpapi

import (
	"crypto/sha256"
	"crypto/subtle"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

const agent4GrantAdminFlag = "KALIV_AGENT4_GRANT_ADMIN"

func (s *server) handleAgent4ReadGrantAdmin(w http.ResponseWriter, r *http.Request) {
	deviceID := strings.TrimSpace(r.PathValue("id"))
	action := "grant"
	enabled := true
	if r.Method == http.MethodDelete {
		action = "revoke"
		enabled = false
	}

	if !isLoopbackRemote(r) {
		s.auditAgent4Grant(deviceID, action, "denied_non_loopback")
		writeErr(w, http.StatusForbidden, "agent4 grant administration requires loopback")
		return
	}

	configuredKey := os.Getenv("MODELRIG_ADMIN_KEY")
	if configuredKey == "" {
		s.auditAgent4Grant(deviceID, action, "denied_unconfigured")
		writeErr(w, http.StatusServiceUnavailable, "agent4 grant administration is not configured")
		return
	}
	if !constantTimeSecretEqual(r.Header.Get("X-Admin-Key"), configuredKey) {
		s.auditAgent4Grant(deviceID, action, "denied_admin_key")
		writeErr(w, http.StatusUnauthorized, "admin key required")
		return
	}
	if deviceID == "" {
		s.auditAgent4Grant(deviceID, action, "rejected_missing_device")
		writeErr(w, http.StatusBadRequest, "missing device id")
		return
	}

	device, found, changed, err := s.Store.SetAgent4ReadGrant(deviceID, enabled)
	if err != nil {
		s.auditAgent4Grant(deviceID, action, "persistence_failed")
		writeErr(w, http.StatusServiceUnavailable, "agent4 grant change could not be persisted")
		return
	}
	if !found {
		s.auditAgent4Grant(deviceID, action, "device_not_found")
		writeErr(w, http.StatusNotFound, "device not found")
		return
	}

	s.auditAgent4Grant(deviceID, action, "success")
	writeJSON(w, http.StatusOK, map[string]any{
		"device_id": device.ID,
		"grant":     agent4ReadGrant,
		"enabled":   device.HasGrant(agent4ReadGrant),
		"changed":   changed,
	})
}

func constantTimeSecretEqual(provided, configured string) bool {
	providedHash := sha256.Sum256([]byte(provided))
	configuredHash := sha256.Sum256([]byte(configured))
	return subtle.ConstantTimeCompare(providedHash[:], configuredHash[:]) == 1
}

func isLoopbackRemote(r *http.Request) bool {
	host, _, err := net.SplitHostPort(strings.TrimSpace(r.RemoteAddr))
	if err != nil {
		host = strings.TrimSpace(r.RemoteAddr)
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func (s *server) auditAgent4Grant(deviceID, action, result string) {
	log.Printf(
		"level=info audit=agent4_grant actor=loopback_admin device=%q grant=%q action=%q result=%q utc=%q",
		deviceID,
		agent4ReadGrant,
		action,
		result,
		time.Now().UTC().Format(time.RFC3339Nano),
	)
}
