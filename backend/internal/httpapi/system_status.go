package httpapi

import (
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// B3a (fase 0-beslutning, DDR-001): lille GET /api/v1/system/status i
// Go-backenden til GPU-temp/CPU — grundlaget for Rig-status-skaermen (18)
// og Modeller-skaermens "VRAM fri"-tal. Fail-soft kontrakt: endpointet
// svarer ALTID 200; gpu/cpu er null naar de ikke kan maales (fx nvidia-smi
// fravaerende paa dev/CI), saa klienten kan vise "ukendt" aerligt i stedet
// for at hele kaldet fejler.

// execOutput og readProcStat er soemme for tests.
var execOutput = func(name string, args ...string) ([]byte, error) {
	return exec.Command(name, args...).Output()
}

var readProcStat = func() ([]byte, error) { return os.ReadFile("/proc/stat") }

// cpuSampleInterval er afstanden mellem de to /proc/stat-maalinger.
var cpuSampleInterval = 150 * time.Millisecond

// processStart saettes naar pakken indlaeses, altsaa naar backenden starter.
// Oppetiden er DERFOR backend-processens levetid — ikke maskinens og ikke
// modelserverens. Skaermen skal sige det samme, saa tallet ikke overfortolkes.
var processStart = time.Now()

// nowFunc er et soem for tests.
var nowFunc = time.Now

func (s *server) handleSystemStatus(w http.ResponseWriter, r *http.Request) {
	uptime := nowFunc().Sub(processStart).Seconds()
	if uptime < 0 {
		uptime = 0
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"schema":         "kaliv-system-status/v1",
		"os":             runtime.GOOS,
		"uptime_seconds": int64(uptime),
		"gpu":            collectGPUStatus(),
		"cpu":            collectCPUStatus(),
	})
}

// collectGPUStatus sporger nvidia-smi; nil hvis vaerktoejet mangler/fejler.
func collectGPUStatus() map[string]any {
	out, err := execOutput(
		"nvidia-smi",
		"--query-gpu=name,temperature.gpu,utilization.gpu,memory.total,memory.used,memory.free",
		"--format=csv,noheader,nounits",
	)
	if err != nil {
		return nil
	}
	line := firstNonEmptyLine(string(out))
	if line == "" {
		return nil
	}
	return parseNvidiaSmiLine(line)
}

func firstNonEmptyLine(s string) string {
	for _, l := range strings.Split(s, "\n") {
		if t := strings.TrimSpace(l); t != "" {
			return t
		}
	}
	return ""
}

// parseNvidiaSmiLine parser een CSV-linje fra query-gpu-kaldet ovenfor.
// "[N/A]"-felter bliver null; vram_free_mb falder tilbage til total-used.
func parseNvidiaSmiLine(line string) map[string]any {
	f := strings.Split(line, ",")
	if len(f) < 6 {
		return nil
	}
	for i := range f {
		f[i] = strings.TrimSpace(f[i])
	}
	temp := intOrNil(f[1])
	util := intOrNil(f[2])
	total := intOrNil(f[3])
	used := intOrNil(f[4])
	free := intOrNil(f[5])
	if free == nil && total != nil && used != nil {
		v := *total - *used
		free = &v
	}
	return map[string]any{
		"name":            f[0],
		"temperature_c":   intPtrOrNil(temp),
		"utilization_pct": intPtrOrNil(util),
		"vram_total_mb":   intPtrOrNil(total),
		"vram_used_mb":    intPtrOrNil(used),
		"vram_free_mb":    intPtrOrNil(free),
	}
}

func intOrNil(s string) *int {
	if s == "" || strings.EqualFold(s, "[N/A]") || strings.EqualFold(s, "N/A") {
		return nil
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return nil
	}
	return &n
}

// intPtrOrNil goer *int JSON-venlig: nil-pointer -> JSON null, ellers tallet.
func intPtrOrNil(p *int) any {
	if p == nil {
		return nil
	}
	return *p
}

// collectCPUStatus maaler CPU-belastning pr. OS; nil naar den ikke kan maales.
func collectCPUStatus() map[string]any {
	switch runtime.GOOS {
	case "windows":
		out, err := execOutput("typeperf", `\Processor(_Total)\% Processor Time`, "-sc", "1")
		if err != nil {
			return nil
		}
		pct := parseTyperfPercent(string(out))
		if pct == nil {
			return nil
		}
		return map[string]any{"utilization_pct": *pct}
	case "linux":
		a, err := readProcStat()
		if err != nil {
			return nil
		}
		time.Sleep(cpuSampleInterval)
		b, err := readProcStat()
		if err != nil {
			return nil
		}
		pct := cpuPercentFromProcStat(string(a), string(b))
		if pct == nil {
			return nil
		}
		return map[string]any{"utilization_pct": *pct}
	default:
		return nil
	}
}

// parseTyperfPercent finder sidste data-linje i typeperf-CSV'en og laeser
// procenttallet. Dansk Windows skriver decimal-KOMMA inde i det quotede
// felt ("12,34"), saa kommaet normaliseres til punktum foer parsning.
func parseTyperfPercent(out string) *float64 {
	var last string
	for _, l := range strings.Split(out, "\n") {
		l = strings.TrimSpace(l)
		if !strings.HasPrefix(l, `"`) {
			continue
		}
		parts := strings.Split(l, `","`)
		if len(parts) < 2 {
			continue
		}
		last = strings.Trim(parts[len(parts)-1], `" `)
	}
	if last == "" {
		return nil
	}
	last = strings.ReplaceAll(last, ",", ".")
	v, err := strconv.ParseFloat(last, 64)
	if err != nil {
		return nil
	}
	v = float64(int(v*10+0.5)) / 10
	return &v
}

// cpuPercentFromProcStat regner belastning af to cpu-aggregatlinjer.
func cpuPercentFromProcStat(a, b string) *float64 {
	ua, ta, ok := procStatBusyTotal(a)
	if !ok {
		return nil
	}
	ub, tb, ok := procStatBusyTotal(b)
	if !ok {
		return nil
	}
	dTotal := tb - ta
	if dTotal <= 0 {
		return nil
	}
	v := 100 * float64(ub-ua) / float64(dTotal)
	if v < 0 {
		v = 0
	}
	if v > 100 {
		v = 100
	}
	v = float64(int(v*10+0.5)) / 10
	return &v
}

func procStatBusyTotal(stat string) (busy, total int64, ok bool) {
	for _, l := range strings.Split(stat, "\n") {
		if !strings.HasPrefix(l, "cpu ") {
			continue
		}
		fields := strings.Fields(l)[1:]
		if len(fields) < 5 {
			return 0, 0, false
		}
		var vals []int64
		for _, f := range fields {
			n, err := strconv.ParseInt(f, 10, 64)
			if err != nil {
				return 0, 0, false
			}
			vals = append(vals, n)
		}
		for _, v := range vals {
			total += v
		}
		idle := vals[3]
		if len(vals) > 4 {
			idle += vals[4] // iowait
		}
		return total - idle, total, true
	}
	return 0, 0, false
}
