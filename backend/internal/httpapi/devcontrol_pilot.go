package httpapi

import (
	"net/http"
	"os"
)

const devControlPilotFlag = "KALIV_DEVCONTROL_PILOT"

// devControlPilotEnabled is intentionally stricter than legacy experimental
// switches: only the exact value "1" mounts the product candidate surface.
// Any unset, malformed, inherited or human-friendly alias remains off.
func devControlPilotEnabled() bool {
	return os.Getenv(devControlPilotFlag) == "1"
}

// handleDevControlPilotStatus exposes observation only. It neither imports nor
// invokes kaliv_dev_control and deliberately reports every execution/publication
// authority as false. A later, separately authorized slice must provide runtime
// preflight and any task registry or executor.
func (s *server) handleDevControlPilotStatus(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	writeJSON(w, http.StatusOK, map[string]any{
		"schema":                           "kaliv-devcontrol-pilot-status/v1",
		"feature_flag":                     devControlPilotFlag,
		"enabled":                          true,
		"operator_surface":                 "desktop.control-center",
		"route_scope":                      "read-only-status-only",
		"manual_refresh_only":              true,
		"automatic_polling":                false,
		"unattended_cadence":               false,
		"task_registry_ready":              false,
		"runtime_preflight_satisfied":      false,
		"pilot_start_authorized":           false,
		"product_pilot_started":            false,
		"local_commit_authorized":          false,
		"remote_transport_available":       false,
		"remote_write_authorized":          false,
		"push_authorized":                  false,
		"pr_mutation_authorized":           false,
		"merge_authorized":                 false,
		"release_authorized":               false,
		"deploy_authorized":                false,
		"production_activation_authorized": false,
		"authority":                        "dc-l16-product-status-observation-only",
	})
}
