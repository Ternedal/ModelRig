// Package startup keeps the appliance's cold-start budgets in one place.
// The frozen voice worker unpacks native libraries before it binds its port.
package startup

import "time"

const (
	GracePeriod   = 3 * time.Minute
	HealthTimeout = 5 * time.Minute
)
