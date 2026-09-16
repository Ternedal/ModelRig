package httpapi

import (
	"crypto/sha256"
	"encoding/hex"
	"io"
	"os"
	"runtime/debug"
	"strings"
	"sync"

	"modelrig/internal/config"
)

// serverBuildIdentity is deliberately read-only evidence. The commit comes
// from Go's build metadata embedded in the running executable; the artifact
// digest is calculated from that executable itself and cached for process life.
type serverBuildIdentity struct {
	Version          string `json:"version"`
	CommitSHA        string `json:"commit_sha"`
	CommitObservable bool   `json:"commit_observable"`
	VCSModified      bool   `json:"vcs_modified"`
	ExecutableSHA256 string `json:"executable_sha256"`
	GoVersion        string `json:"go_version"`
	ModulePath       string `json:"module_path"`
}

var (
	serverBuildIdentityOnce  sync.Once
	serverBuildIdentityValue serverBuildIdentity
	serverBuildIdentityErr   error
)

func currentServerBuildIdentity() (serverBuildIdentity, error) {
	serverBuildIdentityOnce.Do(func() {
		identity := serverBuildIdentity{Version: config.Version}
		if info, ok := debug.ReadBuildInfo(); ok {
			identity.GoVersion = info.GoVersion
			identity.ModulePath = info.Main.Path
			for _, setting := range info.Settings {
				switch setting.Key {
				case "vcs.revision":
					value := strings.ToLower(strings.TrimSpace(setting.Value))
					if len(value) == 40 {
						if _, err := hex.DecodeString(value); err == nil {
							identity.CommitSHA = value
							identity.CommitObservable = true
						}
					}
				case "vcs.modified":
					identity.VCSModified = setting.Value == "true"
				}
			}
		}

		executable, err := os.Executable()
		if err != nil {
			serverBuildIdentityErr = err
			return
		}
		file, err := os.Open(executable)
		if err != nil {
			serverBuildIdentityErr = err
			return
		}
		defer file.Close()
		h := sha256.New()
		if _, err := io.Copy(h, file); err != nil {
			serverBuildIdentityErr = err
			return
		}
		identity.ExecutableSHA256 = hex.EncodeToString(h.Sum(nil))
		serverBuildIdentityValue = identity
	})
	return serverBuildIdentityValue, serverBuildIdentityErr
}
