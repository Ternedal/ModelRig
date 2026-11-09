package httpapi

import (
    "errors"
    "regexp"
    "strconv"
    "strings"
)

// Media API authorization is installation-scoped. A paired device authenticates
// through authMW; its device ID is for auditing, not media ownership.
const mediaInstallationOwner = "installation"

var mediaSafeID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,128}$`)

func validMediaID(id string) bool { return mediaSafeID.MatchString(id) }

// parseMediaLimit bounds a gallery page to the existing Android v1 contract.
func parseMediaLimit(raw string) (int, error) {
    if raw == "" { return 50, nil }
    if strings.TrimSpace(raw) != raw || strings.HasPrefix(raw, "+") || len(raw) > 3 {
        return 0, errors.New("invalid media limit")
    }
    n, err := strconv.Atoi(raw)
    if err != nil || n < 1 || n > 100 { return 0, errors.New("invalid media limit") }
    return n, nil
}

// validateMediaCursor bounds the opaque cursor before it reaches the catalog.
// Its meaning is owned by the catalog; this function does not decode it.
func validateMediaCursor(cursor string) error {
    if cursor == "" { return nil }
    if len(cursor) > 1024 { return errors.New("invalid media cursor") }
    for i := 0; i < len(cursor); i++ {
        if cursor[i] < 0x21 || cursor[i] > 0x7e {
            return errors.New("invalid media cursor")
        }
    }
    return nil
}
