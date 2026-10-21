// Package startup keeps the appliance's cold-start budgets in one place.
// The frozen voice worker unpacks native libraries before it binds its port.
// A live but not-yet-ready child has a bounded 4m30s grace, leaving 30s
// before the updater's 5m health deadline. Exited children restart immediately;
// already-ready children retain the normal unhealthy-poll restart threshold.
package startup

import "time"

const (
	GracePeriod   = 4*time.Minute + 30*time.Second
	HealthTimeout = 5 * time.Minute
)
