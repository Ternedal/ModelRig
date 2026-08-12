package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

const defaultBackendURL = "http://127.0.0.1:8080"

type grantResponse struct {
	DeviceID string `json:"device_id"`
	Grant    string `json:"grant"`
	Enabled  bool   `json:"enabled"`
	Changed  bool   `json:"changed"`
	Error    string `json:"error"`
}

func main() {
	grantDevice := flag.String("grant", "", "paired device ID to grant agent4:read")
	revokeDevice := flag.String("revoke", "", "paired device ID to revoke agent4:read")
	backendURL := flag.String("url", defaultBackendURL, "loopback ModelRig backend URL")
	flag.Parse()

	deviceID, method, err := requestedMutation(*grantDevice, *revokeDevice)
	if err != nil {
		fatal(err)
	}
	base, err := parseLoopbackBackendURL(*backendURL)
	if err != nil {
		fatal(err)
	}
	adminKey := os.Getenv("MODELRIG_ADMIN_KEY")
	if adminKey == "" {
		fatal(errors.New("MODELRIG_ADMIN_KEY is required"))
	}

	result, err := mutateGrant(base, deviceID, method, adminKey)
	if err != nil {
		fatal(err)
	}
	fmt.Printf(
		"device=%s grant=%s enabled=%t changed=%t\n",
		result.DeviceID,
		result.Grant,
		result.Enabled,
		result.Changed,
	)
}

func requestedMutation(grantDevice, revokeDevice string) (string, string, error) {
	grantDevice = strings.TrimSpace(grantDevice)
	revokeDevice = strings.TrimSpace(revokeDevice)
	if (grantDevice == "") == (revokeDevice == "") {
		return "", "", errors.New("specify exactly one of -grant DEVICE_ID or -revoke DEVICE_ID")
	}
	if grantDevice != "" {
		return grantDevice, http.MethodPut, nil
	}
	return revokeDevice, http.MethodDelete, nil
}

func parseLoopbackBackendURL(raw string) (*url.URL, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return nil, fmt.Errorf("invalid backend URL: %w", err)
	}
	if parsed.Scheme != "http" {
		return nil, errors.New("backend URL must use http on loopback")
	}
	if parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, errors.New("backend URL must not contain credentials, query or fragment")
	}
	host := parsed.Hostname()
	if !isLoopbackHost(host) {
		return nil, fmt.Errorf("backend URL must be loopback, got %q", host)
	}
	parsed.Path = strings.TrimRight(parsed.Path, "/")
	return parsed, nil
}

func isLoopbackHost(host string) bool {
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func mutateGrant(
	base *url.URL,
	deviceID string,
	method string,
	adminKey string,
) (grantResponse, error) {
	endpoint := *base
	endpoint.Path = strings.TrimRight(base.Path, "/") +
		"/api/v1/admin/devices/" + url.PathEscape(deviceID) +
		"/grants/agent4-read"

	request, err := http.NewRequest(method, endpoint.String(), nil)
	if err != nil {
		return grantResponse{}, err
	}
	request.Header.Set("X-Admin-Key", adminKey)
	request.Header.Set("Accept", "application/json")

	client := &http.Client{
		Timeout: 5 * time.Second,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return errors.New("redirects are not allowed")
		},
	}
	response, err := client.Do(request)
	if err != nil {
		return grantResponse{}, fmt.Errorf("grant request failed: %w", err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 1<<20))
	if err != nil {
		return grantResponse{}, fmt.Errorf("read response: %w", err)
	}

	var result grantResponse
	if err := json.Unmarshal(body, &result); err != nil {
		return grantResponse{}, fmt.Errorf("backend returned invalid JSON (HTTP %d)", response.StatusCode)
	}
	if response.StatusCode != http.StatusOK {
		if result.Error == "" {
			result.Error = http.StatusText(response.StatusCode)
		}
		return grantResponse{}, fmt.Errorf("backend refused grant change (HTTP %d): %s", response.StatusCode, result.Error)
	}
	if result.DeviceID != deviceID || result.Grant != "agent4:read" {
		return grantResponse{}, errors.New("backend response identity did not match the requested fixed grant")
	}
	return result, nil
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "ERROR:", err)
	os.Exit(1)
}
