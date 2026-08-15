package httpapi

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"modelrig/internal/auth"
	"modelrig/internal/config"
	"modelrig/internal/proxy"
	"modelrig/internal/store"
)

// newAuthedTestHandler bygger den fulde router m. auth-middleware og een
// parret enhed — samme moenster som control-center-bearer-testen.
func newAuthedTestHandler(t *testing.T) (http.Handler, string) {
	t.Helper()
	st, err := store.Open(t.TempDir() + "/devices.json")
	if err != nil {
		t.Fatal(err)
	}
	const token = "system-status-token"
	if err := st.AddDevice(store.Device{
		ID:        "system-status-device",
		Name:      "test phone",
		TokenHash: auth.Hash(token),
		CreatedAt: time.Now(),
		LastSeen:  time.Now(),
	}); err != nil {
		t.Fatal(err)
	}
	return New(Deps{
		Cfg:    config.Default(),
		Store:  st,
		Worker: proxy.New("http://127.0.0.1:9", time.Second),
	}), token
}

func TestParseNvidiaSmiLineFullRow(t *testing.T) {
	m := parseNvidiaSmiLine("NVIDIA GeForce RTX 3060, 62, 34, 12288, 8100, 4188")
	if m == nil {
		t.Fatal("nil for gyldig linje")
	}
	if m["name"] != "NVIDIA GeForce RTX 3060" {
		t.Errorf("name = %v", m["name"])
	}
	for k, want := range map[string]int{
		"temperature_c": 62, "utilization_pct": 34,
		"vram_total_mb": 12288, "vram_used_mb": 8100, "vram_free_mb": 4188,
	} {
		if got, _ := m[k].(int); got != want {
			t.Errorf("%s = %v, want %d", k, m[k], want)
		}
	}
}

func TestParseNvidiaSmiLineNATolereresOgFreeBeregnes(t *testing.T) {
	m := parseNvidiaSmiLine("RTX 3060, [N/A], 34, 12288, 8100, [N/A]")
	if m["temperature_c"] != nil {
		t.Errorf("temperature_c = %v, want nil", m["temperature_c"])
	}
	if got, _ := m["vram_free_mb"].(int); got != 4188 {
		t.Errorf("vram_free_mb fallback = %v, want 4188", m["vram_free_mb"])
	}
}

func TestCollectGPUStatusNilNaarVaerktoejMangler(t *testing.T) {
	old := execOutput
	defer func() { execOutput = old }()
	execOutput = func(string, ...string) ([]byte, error) { return nil, errors.New("mangler") }
	if got := collectGPUStatus(); got != nil {
		t.Errorf("gpu = %v, want nil", got)
	}
}

func TestParseTyperfPercentInklDanskDecimalkomma(t *testing.T) {
	out := "\"(PDH-CSV 4.0)\",\"\\\\RIG\\Processor(_Total)\\% Processor Time\"\r\n" +
		"\"08/15/2026 10:00:01.000\",\"12,345678\"\r\n" +
		"Exiting, please wait...\r\n"
	pct := parseTyperfPercent(out)
	if pct == nil || *pct != 12.3 {
		t.Fatalf("pct = %v, want 12.3", pct)
	}
}

func TestCpuPercentFromProcStat(t *testing.T) {
	a := "cpu  100 0 100 700 100 0 0 0 0 0\nandet\n"
	b := "cpu  200 0 200 1200 200 0 0 0 0 0\nandet\n"
	// busy: (a)=200, (b)=400 -> d=200; total: a=1000, b=1800 -> d=800; 25%
	pct := cpuPercentFromProcStat(a, b)
	if pct == nil || *pct != 25.0 {
		t.Fatalf("pct = %v, want 25.0", pct)
	}
	if got := cpuPercentFromProcStat(a, a); got != nil {
		t.Errorf("nul-delta skal give nil, fik %v", got)
	}
	if got := cpuPercentFromProcStat("snavs", b); got != nil {
		t.Errorf("snavs skal give nil, fik %v", got)
	}
}

func TestHandleSystemStatusFailSoftJSON(t *testing.T) {
	oldExec, oldProc, oldInt := execOutput, readProcStat, cpuSampleInterval
	defer func() { execOutput, readProcStat, cpuSampleInterval = oldExec, oldProc, oldInt }()
	cpuSampleInterval = time.Millisecond
	execOutput = func(name string, _ ...string) ([]byte, error) {
		if name == "nvidia-smi" {
			return []byte("RTX 3060, 61, 12, 12288, 2048, 10240\n"), nil
		}
		return nil, errors.New("ukendt kommando")
	}
	calls := 0
	readProcStat = func() ([]byte, error) {
		calls++
		if calls == 1 {
			return []byte("cpu  100 0 100 700 100 0 0 0 0 0\n"), nil
		}
		return []byte("cpu  200 0 200 1200 200 0 0 0 0 0\n"), nil
	}

	s := &server{}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/system/status", nil)
	rec := httptest.NewRecorder()
	s.handleSystemStatus(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	var body struct {
		Schema string         `json:"schema"`
		OS     string         `json:"os"`
		GPU    map[string]any `json:"gpu"`
		CPU    map[string]any `json:"cpu"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Schema != "kaliv-system-status/v1" {
		t.Errorf("schema = %q", body.Schema)
	}
	if body.GPU == nil {
		t.Fatal("gpu mangler")
	}
	if got := body.GPU["temperature_c"].(float64); got != 61 {
		t.Errorf("temperature_c = %v", got)
	}
	if got := body.GPU["vram_free_mb"].(float64); got != 10240 {
		t.Errorf("vram_free_mb = %v", got)
	}
	// cpu: linux-sti i CI; paa andre OS accepteres null (fail-soft)
	if body.CPU != nil {
		if _, ok := body.CPU["utilization_pct"].(float64); !ok {
			t.Errorf("utilization_pct mangler i %v", body.CPU)
		}
	}
}

func TestSystemStatusReportsBackendUptime(t *testing.T) {
	oldExec, oldProc, oldInt, oldNow, oldStart := execOutput, readProcStat, cpuSampleInterval, nowFunc, processStart
	defer func() {
		execOutput, readProcStat, cpuSampleInterval, nowFunc, processStart = oldExec, oldProc, oldInt, oldNow, oldStart
	}()
	cpuSampleInterval = time.Millisecond
	execOutput = func(string, ...string) ([]byte, error) { return nil, errors.New("ingen gpu i test") }
	readProcStat = func() ([]byte, error) { return nil, errors.New("ingen proc i test") }
	processStart = time.Unix(1_700_000_000, 0)
	nowFunc = func() time.Time { return processStart.Add(6*time.Hour + 12*time.Minute + 30*time.Second) }

	s := &server{}
	rec := httptest.NewRecorder()
	s.handleSystemStatus(rec, httptest.NewRequest(http.MethodGet, "/api/v1/system/status", nil))

	var body struct {
		Uptime int64 `json:"uptime_seconds"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Uptime != 22350 {
		t.Errorf("uptime_seconds = %d, want 22350", body.Uptime)
	}

	// En baglaens klokke maa aldrig give negativ oppetid.
	nowFunc = func() time.Time { return processStart.Add(-time.Hour) }
	rec = httptest.NewRecorder()
	s.handleSystemStatus(rec, httptest.NewRequest(http.MethodGet, "/api/v1/system/status", nil))
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body.Uptime != 0 {
		t.Errorf("negativ oppetid = %d, want 0", body.Uptime)
	}
}

func TestSystemStatusRouteRequiresBearerToken(t *testing.T) {
	oldExec, oldProc, oldInt := execOutput, readProcStat, cpuSampleInterval
	defer func() { execOutput, readProcStat, cpuSampleInterval = oldExec, oldProc, oldInt }()
	cpuSampleInterval = time.Millisecond
	execOutput = func(string, ...string) ([]byte, error) { return nil, errors.New("ingen gpu i test") }
	readProcStat = func() ([]byte, error) { return nil, errors.New("ingen proc i test") }

	handler, token := newAuthedTestHandler(t)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/system/status", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("uden token: status = %d, want 401", rec.Code)
	}

	req = httptest.NewRequest(http.MethodGet, "/api/v1/system/status", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("med token: status = %d, want 200", rec.Code)
	}
}
