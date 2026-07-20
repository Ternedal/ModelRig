package capabilityschema

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"sort"
	"strings"
)

const Schema = "kaliv-capability/v2"

var (
	accessValues      = set("read", "write", "desktop")
	impactValues      = set("read", "write", "desktop", "destructive", "admin")
	dataClassValues   = set("public", "operational", "private", "secret")
	confirmationModes = set("none", "required")
	isolationModes    = set("in_process", "process")
	networkModes      = set("none", "loopback", "configured_service", "public", "undeclared")
	terminationModes  = set("none", "cooperative", "forceable")
	capabilityID      = regexp.MustCompile(`^tool:[A-Za-z0-9._:-]{1,155}$`)
)

type Isolation struct {
	Mode     string   `json:"mode"`
	EnvAllow []string `json:"env_allow"`
}

type Scheduling struct {
	Allowed bool   `json:"allowed"`
	Reason  string `json:"reason"`
}

type Confirmation struct {
	Mode string `json:"mode"`
}

type Network struct {
	Mode         string   `json:"mode"`
	Destinations []string `json:"destinations"`
}

type Termination struct {
	Mode string `json:"mode"`
}

type Replay struct {
	Idempotent bool `json:"idempotent"`
}

type Descriptor struct {
	Schema               string         `json:"schema"`
	CapabilityID         string         `json:"capability_id"`
	Kind                 string         `json:"kind"`
	Description          string         `json:"description"`
	Access               string         `json:"access"`
	Impact               string         `json:"impact"`
	DataClass            string         `json:"data_class"`
	Parameters           map[string]any `json:"parameters"`
	Isolation            Isolation      `json:"isolation"`
	Scheduling           Scheduling     `json:"scheduling"`
	Confirmation         Confirmation   `json:"confirmation"`
	Network              Network        `json:"network"`
	Termination          Termination    `json:"termination"`
	Replay               Replay         `json:"replay"`
	ProductionActivation bool           `json:"production_activation"`
}

func Parse(raw []byte) (Descriptor, error) {
	if err := validateObjectShape(raw); err != nil {
		return Descriptor{}, err
	}

	var descriptor Descriptor
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&descriptor); err != nil {
		return Descriptor{}, fmt.Errorf("decode capability descriptor: %w", err)
	}
	if err := requireEOF(decoder); err != nil {
		return Descriptor{}, err
	}
	if err := descriptor.Validate(); err != nil {
		return Descriptor{}, err
	}
	return descriptor, nil
}

func validateObjectShape(raw []byte) error {
	var top map[string]json.RawMessage
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if err := decoder.Decode(&top); err != nil {
		return fmt.Errorf("decode capability object: %w", err)
	}
	if top == nil {
		return errors.New("capability descriptor must be an object")
	}
	if err := requireEOF(decoder); err != nil {
		return err
	}

	if err := exactKeys(top, "capability descriptor", []string{
		"schema", "capability_id", "kind", "description", "access",
		"impact", "data_class", "parameters", "isolation", "scheduling",
		"confirmation", "network", "termination", "replay",
		"production_activation",
	}); err != nil {
		return err
	}
	for name, keys := range map[string][]string{
		"isolation":    {"mode", "env_allow"},
		"scheduling":   {"allowed", "reason"},
		"confirmation": {"mode"},
		"network":      {"mode", "destinations"},
		"termination":  {"mode"},
		"replay":       {"idempotent"},
	} {
		var nested map[string]json.RawMessage
		if err := json.Unmarshal(top[name], &nested); err != nil {
			return fmt.Errorf("%s must be an object: %w", name, err)
		}
		if nested == nil {
			return fmt.Errorf("%s must be an object", name)
		}
		if err := exactKeys(nested, name, keys); err != nil {
			return err
		}
	}
	return nil
}

func (d Descriptor) Validate() error {
	if d.Schema != Schema {
		return fmt.Errorf("unsupported schema %q", d.Schema)
	}
	if !capabilityID.MatchString(d.CapabilityID) {
		return errors.New("capability_id must be a stable tool:<name> id")
	}
	if d.Kind != "tool" || strings.TrimSpace(d.Description) == "" {
		return errors.New("kind must be tool and description must be non-empty")
	}
	if err := allowed(d.Access, accessValues, "access"); err != nil {
		return err
	}
	if err := allowed(d.Impact, impactValues, "impact"); err != nil {
		return err
	}
	if err := allowed(d.DataClass, dataClassValues, "data_class"); err != nil {
		return err
	}
	if d.Parameters == nil {
		return errors.New("parameters must be an object")
	}
	if err := allowed(d.Isolation.Mode, isolationModes, "isolation.mode"); err != nil {
		return err
	}
	if d.Isolation.EnvAllow == nil {
		return errors.New("isolation.env_allow must be an array")
	}
	if err := uniqueNonEmpty(d.Isolation.EnvAllow, "isolation.env_allow"); err != nil {
		return err
	}
	if d.Scheduling.Allowed && d.Scheduling.Reason != "" {
		return errors.New("schedulable capability must not carry a refusal reason")
	}
	if !d.Scheduling.Allowed && strings.TrimSpace(d.Scheduling.Reason) == "" {
		return errors.New("unschedulable capability requires a reason")
	}
	if err := allowed(d.Confirmation.Mode, confirmationModes, "confirmation.mode"); err != nil {
		return err
	}
	expected := "none"
	if d.Access == "write" || d.Access == "desktop" {
		expected = "required"
	}
	if d.Confirmation.Mode != expected {
		return errors.New("confirmation mode contradicts access")
	}
	if err := allowed(d.Network.Mode, networkModes, "network.mode"); err != nil {
		return err
	}
	if d.Network.Destinations == nil {
		return errors.New("network.destinations must be an array")
	}
	if err := uniqueNonEmpty(d.Network.Destinations, "network.destinations"); err != nil {
		return err
	}
	if (d.Network.Mode == "none" || d.Network.Mode == "undeclared") && len(d.Network.Destinations) != 0 {
		return errors.New("network destinations require loopback, configured_service or public mode")
	}
	if (d.Network.Mode == "loopback" || d.Network.Mode == "configured_service" || d.Network.Mode == "public") && len(d.Network.Destinations) == 0 {
		return errors.New("networked mode requires a destination")
	}
	if err := allowed(d.Termination.Mode, terminationModes, "termination.mode"); err != nil {
		return err
	}
	if d.ProductionActivation {
		return errors.New("capability schema must never activate production")
	}
	return nil
}

func (d Descriptor) CanonicalJSON() ([]byte, error) {
	if err := d.Validate(); err != nil {
		return nil, err
	}
	payload := map[string]any{
		"schema":        d.Schema,
		"capability_id": d.CapabilityID,
		"kind":          d.Kind,
		"description":   d.Description,
		"access":        d.Access,
		"impact":        d.Impact,
		"data_class":    d.DataClass,
		"parameters":    d.Parameters,
		"isolation": map[string]any{
			"mode":      d.Isolation.Mode,
			"env_allow": d.Isolation.EnvAllow,
		},
		"scheduling": map[string]any{
			"allowed": d.Scheduling.Allowed,
			"reason":  d.Scheduling.Reason,
		},
		"confirmation": map[string]any{"mode": d.Confirmation.Mode},
		"network": map[string]any{
			"mode":         d.Network.Mode,
			"destinations": d.Network.Destinations,
		},
		"termination":           map[string]any{"mode": d.Termination.Mode},
		"replay":                map[string]any{"idempotent": d.Replay.Idempotent},
		"production_activation": false,
	}
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(payload); err != nil {
		return nil, fmt.Errorf("encode canonical capability descriptor: %w", err)
	}
	return bytes.TrimSuffix(buffer.Bytes(), []byte("\n")), nil
}

func SortedIDs(descriptors []Descriptor) ([]string, error) {
	ids := make([]string, 0, len(descriptors))
	seen := make(map[string]struct{}, len(descriptors))
	for _, descriptor := range descriptors {
		if err := descriptor.Validate(); err != nil {
			return nil, err
		}
		if _, ok := seen[descriptor.CapabilityID]; ok {
			return nil, fmt.Errorf(
				"duplicate capability id %q", descriptor.CapabilityID,
			)
		}
		seen[descriptor.CapabilityID] = struct{}{}
		ids = append(ids, descriptor.CapabilityID)
	}
	sort.Strings(ids)
	return ids, nil
}

func exactKeys(
	object map[string]json.RawMessage,
	name string,
	expected []string,
) error {
	want := make(map[string]struct{}, len(expected))
	for _, key := range expected {
		want[key] = struct{}{}
	}
	for key := range object {
		if _, ok := want[key]; !ok {
			return fmt.Errorf("%s contains unknown field %q", name, key)
		}
	}
	for _, key := range expected {
		if _, ok := object[key]; !ok {
			return fmt.Errorf("%s is missing required field %q", name, key)
		}
	}
	return nil
}

func requireEOF(decoder *json.Decoder) error {
	var trailing any
	if err := decoder.Decode(&trailing); err == io.EOF {
		return nil
	} else if err != nil {
		return fmt.Errorf("decode trailing capability data: %w", err)
	}
	return errors.New("capability descriptor contains trailing JSON values")
}

func allowed(value string, values map[string]struct{}, field string) error {
	if _, ok := values[value]; !ok {
		return fmt.Errorf("%s has unsupported value %q", field, value)
	}
	return nil
}

func uniqueNonEmpty(values []string, field string) error {
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("%s contains an empty value", field)
		}
		if _, ok := seen[value]; ok {
			return fmt.Errorf("%s contains duplicates", field)
		}
		seen[value] = struct{}{}
	}
	return nil
}

func set(values ...string) map[string]struct{} {
	result := make(map[string]struct{}, len(values))
	for _, value := range values {
		result[value] = struct{}{}
	}
	return result
}
