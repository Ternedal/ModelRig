// Package startup keeps the appliance's cold-start budgets in one place.
// The frozen voice worker unpacks native libraries before it binds its port.
package startup

import "time"

const (
	GracePeriod   = 4*time.Minute + 30*time.Second
	HealthTimeout = 5 * time.Minute
)
