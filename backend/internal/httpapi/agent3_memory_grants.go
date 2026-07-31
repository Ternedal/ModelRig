package httpapi

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

const (
	agent3MemoryStoreEnv               = "KALIV_AGENT3_MEMORY_STORE"
	agent3MemoryAPISecretEnv           = "KALIV_AGENT3_MEMORY_API_SECRET"
	agent3MemoryGrantHeader            = "X-Kaliv-Agent3-Memory-Grant"
	agent3MemoryStoreAttestationHeader = "X-Kaliv-Agent3-Memory-Store"
	agent3MemoryStoreAttestationValue  = "protected"
	agent3MemoryGrantSchema            = "kaliv-agent3-memory-grant/v1"
	agent3MemoryGrantTTL               = 30 * time.Second
	agent3MemoryGrantMaxFuture         = 5 * time.Second
	agent3MemoryRequestBodyMaxBytes    = 64 * 1024
)

var (
	errAgent3MemoryGrantUnavailable = errors.New("Agent 3 protected-memory grant secret is unavailable")
	errAgent3MemoryRouteUnsupported = errors.New("Agent 3 protected-memory route is unsupported")
)

type agent3MemoryGrantClaims struct {
	Schema     string `json:"schema"`
	Nonce      string `json:"nonce"`
	DeviceID   string `json:"device_id"`
	Action     string `json:"action"`
	RequestID  string `json:"request_id"`
	Method     string `json:"method"`
	Path       string `json:"path"`
	Query      string `json:"query"`
	BodySHA256 string `json:"body_sha256"`
	IssuedAt   int64  `json:"issued_at"`
	ExpiresAt  int64  `json:"expires_at"`
}

func agent3MemoryStoreMode() (string, error) {
	raw := os.Getenv(agent3MemoryStoreEnv)
	if raw == "" {
		return "legacy", nil
	}
	if strings.TrimSpace(raw) != raw {
		return "", fmt.Errorf("%s must be canonical", agent3MemoryStoreEnv)
	}
	if raw != "legacy" && raw != "protected" {
		return "", fmt.Errorf("%s must be legacy or protected", agent3MemoryStoreEnv)
	}
	return raw, nil
}

func agent3MemoryGrantSecret() ([]byte, error) {
	secret := []byte(os.Getenv(agent3MemoryAPISecretEnv))
	if len(secret) < 32 || len(secret) > 4_096 {
		return nil, errAgent3MemoryGrantUnavailable
	}
	return secret, nil
}

func cleanAgent3MemoryGrantText(name, value string, maximum int) (string, error) {
	cleaned := strings.TrimSpace(value)
	if cleaned == "" || cleaned != value || len(cleaned) > maximum || strings.ContainsAny(cleaned, "\r\n\x00") {
		return "", fmt.Errorf("Agent 3 protected-memory %s is invalid", name)
	}
	return cleaned, nil
}

func cleanAgent3MemoryGrantOptionalText(name, value string, maximum int) (string, error) {
	if len(value) > maximum || strings.ContainsAny(value, "\r\n\x00") {
		return "", fmt.Errorf("Agent 3 protected-memory %s is invalid", name)
	}
	return value, nil
}

func agent3MemoryGrantAction(method, path string) (string, error) {
	const prefix = "/experimental/agent3/memory"
	if !strings.HasPrefix(path, prefix) {
		return "", errAgent3MemoryRouteUnsupported
	}
	suffix := strings.TrimPrefix(path, prefix)
	segments := []string{}
	if suffix != "" {
		if !strings.HasPrefix(suffix, "/") || strings.HasSuffix(suffix, "/") {
			return "", errAgent3MemoryRouteUnsupported
		}
		for _, segment := range strings.Split(strings.TrimPrefix(suffix, "/"), "/") {
			if segment == "" {
				return "", errAgent3MemoryRouteUnsupported
			}
			segments = append(segments, segment)
		}
	}

	switch method {
	case http.MethodGet:
		if len(segments) == 1 && segments[0] == "status" {
			return "status", nil
		}
		if len(segments) == 0 ||
			(len(segments) == 1 && segments[0] != "status" && segments[0] != "context-preview") ||
			(len(segments) == 2 && segments[1] == "history") {
			return "read_metadata", nil
		}
	case http.MethodPost:
		if len(segments) == 0 || (len(segments) == 2 && segments[1] == "correct") {
			return "write_private", nil
		}
	case http.MethodDelete:
		if len(segments) == 1 && segments[0] != "status" && segments[0] != "search" && segments[0] != "context-preview" {
			return "write_private", nil
		}
	}
	return "", errAgent3MemoryRouteUnsupported
}

func bindAgent3MemoryRequestBody(r *http.Request) (string, error) {
	if r.Body == nil {
		digest := sha256.Sum256(nil)
		return hex.EncodeToString(digest[:]), nil
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, agent3MemoryRequestBodyMaxBytes+1))
	if err != nil {
		return "", fmt.Errorf("protected-memory request body: %w", err)
	}
	if len(raw) > agent3MemoryRequestBodyMaxBytes {
		return "", fmt.Errorf("protected-memory request body exceeds %d bytes", agent3MemoryRequestBodyMaxBytes)
	}
	r.Body = io.NopCloser(bytes.NewReader(raw))
	r.ContentLength = int64(len(raw))
	digest := sha256.Sum256(raw)
	return hex.EncodeToString(digest[:]), nil
}

func issueAgent3MemoryGrant(
	r *http.Request,
	workerPath string,
	bodySHA256 string,
	now time.Time,
) (string, agent3MemoryGrantClaims, error) {
	secret, err := agent3MemoryGrantSecret()
	if err != nil {
		return "", agent3MemoryGrantClaims{}, err
	}
	deviceID, ok := scheduleDeviceID(r)
	if !ok {
		return "", agent3MemoryGrantClaims{}, errors.New("protected memory is not bound to an authenticated device")
	}
	deviceID, err = cleanAgent3MemoryGrantText("device id", deviceID, 200)
	if err != nil {
		return "", agent3MemoryGrantClaims{}, err
	}
	requestID, err := cleanAgent3MemoryGrantText("request id", r.Header.Get("X-Request-ID"), 200)
	if err != nil {
		return "", agent3MemoryGrantClaims{}, err
	}
	path := workerPath
	if index := strings.IndexByte(path, '?'); index >= 0 {
		path = path[:index]
	}
	path, err = cleanAgent3MemoryGrantText("path", path, 1_000)
	if err != nil || !strings.HasPrefix(path, "/experimental/agent3/memory") {
		return "", agent3MemoryGrantClaims{}, errAgent3MemoryRouteUnsupported
	}
	query, err := cleanAgent3MemoryGrantOptionalText("query", r.URL.RawQuery, 4_096)
	if err != nil {
		return "", agent3MemoryGrantClaims{}, err
	}
	if len(bodySHA256) != sha256.Size*2 {
		return "", agent3MemoryGrantClaims{}, errors.New("protected-memory request body digest is invalid")
	}
	if _, err := hex.DecodeString(bodySHA256); err != nil || bodySHA256 != strings.ToLower(bodySHA256) {
		return "", agent3MemoryGrantClaims{}, errors.New("protected-memory request body digest is invalid")
	}
	method := strings.ToUpper(strings.TrimSpace(r.Method))
	action, err := agent3MemoryGrantAction(method, path)
	if err != nil {
		return "", agent3MemoryGrantClaims{}, err
	}

	nonceBytes := make([]byte, 32)
	if _, err := rand.Read(nonceBytes); err != nil {
		return "", agent3MemoryGrantClaims{}, fmt.Errorf("protected-memory grant nonce: %w", err)
	}
	claims := agent3MemoryGrantClaims{
		Schema:     agent3MemoryGrantSchema,
		Nonce:      base64.RawURLEncoding.EncodeToString(nonceBytes),
		DeviceID:   deviceID,
		Action:     action,
		RequestID:  requestID,
		Method:     method,
		Path:       path,
		Query:      query,
		BodySHA256: bodySHA256,
		IssuedAt:   now.Unix(),
		ExpiresAt:  now.Add(agent3MemoryGrantTTL).Unix(),
	}
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", agent3MemoryGrantClaims{}, fmt.Errorf("protected-memory grant payload: %w", err)
	}
	payloadPart := base64.RawURLEncoding.EncodeToString(payload)
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(agent3MemoryGrantSchema))
	_, _ = mac.Write([]byte{0})
	_, _ = mac.Write([]byte(payloadPart))
	signaturePart := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	return payloadPart + "." + signaturePart, claims, nil
}

// verifyAgent3MemoryGrant is intentionally kept in Go as a cross-language
// contract test oracle. Production verification happens independently in the
// loopback worker; sharing no implementation makes drift visible in CI.
func verifyAgent3MemoryGrant(
	token string,
	requestID string,
	method string,
	path string,
	query string,
	bodySHA256 string,
	now time.Time,
) (agent3MemoryGrantClaims, error) {
	secret, err := agent3MemoryGrantSecret()
	if err != nil {
		return agent3MemoryGrantClaims{}, err
	}
	parts := strings.Split(token, ".")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant is malformed")
	}
	signature, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil || len(signature) != sha256.Size || base64.RawURLEncoding.EncodeToString(signature) != parts[1] {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant is malformed")
	}
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write([]byte(agent3MemoryGrantSchema))
	_, _ = mac.Write([]byte{0})
	_, _ = mac.Write([]byte(parts[0]))
	if !hmac.Equal(mac.Sum(nil), signature) {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant signature is invalid")
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil || base64.RawURLEncoding.EncodeToString(payload) != parts[0] {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant is malformed")
	}
	var claims agent3MemoryGrantClaims
	dec := json.NewDecoder(bytes.NewReader(payload))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&claims); err != nil {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant payload is invalid")
	}
	if err := dec.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant payload is invalid")
	}
	if claims.Schema != agent3MemoryGrantSchema || claims.Nonce == "" || claims.DeviceID == "" ||
		claims.Action == "" || claims.RequestID == "" || claims.Method == "" || claims.Path == "" ||
		claims.BodySHA256 == "" {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant claims are invalid")
	}
	nonce, err := base64.RawURLEncoding.DecodeString(claims.Nonce)
	if err != nil || len(nonce) != 32 || base64.RawURLEncoding.EncodeToString(nonce) != claims.Nonce {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant nonce is invalid")
	}
	if _, err := cleanAgent3MemoryGrantText("device id", claims.DeviceID, 200); err != nil {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant device is invalid")
	}
	if _, err := cleanAgent3MemoryGrantText("request id", claims.RequestID, 200); err != nil {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant request is invalid")
	}
	if claims.RequestID != requestID || claims.Method != method || claims.Path != path ||
		claims.Query != query || claims.BodySHA256 != bodySHA256 {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant request binding is invalid")
	}
	action, err := agent3MemoryGrantAction(method, path)
	if err != nil || claims.Action != action {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant action binding is invalid")
	}
	if claims.IssuedAt > now.Add(agent3MemoryGrantMaxFuture).Unix() {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant is not valid yet")
	}
	if claims.IssuedAt < now.Add(-2*time.Minute).Unix() || claims.ExpiresAt <= now.Unix() {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant has expired")
	}
	if claims.ExpiresAt <= claims.IssuedAt || time.Duration(claims.ExpiresAt-claims.IssuedAt)*time.Second > 2*time.Minute {
		return agent3MemoryGrantClaims{}, errors.New("protected-memory grant lifetime is invalid")
	}
	return claims, nil
}
