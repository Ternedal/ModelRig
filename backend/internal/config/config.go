package config

import (
	"encoding/json"
	"os"
	"strconv"
	"time"
)

// Version is the ModelRig backend version.
const Version = "0.12.0"

// Config holds the effective runtime configuration.
type Config struct {
	ServerHost     string
	ServerPort     int
	OllamaBaseURL  string
	OllamaKey      string // Ollama API key; set for Ollama Cloud, empty for local
	WorkerBaseURL  string
	PairingTTL     time.Duration
	DataPath       string
	RequestTimeout time.Duration
	ClaimMax       int // max pairing-claim attempts per IP per 5 min
}

type fileConfig struct {
	Server struct {
		Host string `json:"host"`
		Port int    `json:"port"`
	} `json:"server"`
	Ollama struct {
		BaseURL string `json:"base_url"`
		APIKey  string `json:"api_key"`
	} `json:"ollama"`
	Worker struct {
		BaseURL string `json:"base_url"`
	} `json:"worker"`
	Pairing struct {
		TTLSeconds int `json:"ttl_seconds"`
	} `json:"pairing"`
	Data struct {
		Path string `json:"path"`
	} `json:"data"`
}

// Default returns the baseline configuration.
//
// NOTE: ServerHost defaults to 127.0.0.1 (loopback). Android and other LAN
// clients CANNOT reach a loopback-bound server. Set MODELRIG_HOST=0.0.0.0 or a
// Tailscale IP before pairing a phone. This is the single most common ModelRig
// operational mistake.
func Default() Config {
	return Config{
		ServerHost:     "127.0.0.1",
		ServerPort:     8080,
		OllamaBaseURL:  "http://127.0.0.1:11434",
		WorkerBaseURL:  "http://127.0.0.1:8099",
		PairingTTL:     5 * time.Minute,
		DataPath:       "./modelrig-data.json",
		RequestTimeout: 120 * time.Second,
		ClaimMax:       10,
	}
}

// Load builds config from defaults, then an optional JSON file
// (path in MODELRIG_CONFIG), then environment overrides.
func Load() (Config, error) {
	c := Default()
	if p := os.Getenv("MODELRIG_CONFIG"); p != "" {
		if err := applyFile(&c, p); err != nil {
			return c, err
		}
	}
	applyEnv(&c)
	return c, nil
}

func applyFile(c *Config, path string) error {
	b, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var fc fileConfig
	if err := json.Unmarshal(b, &fc); err != nil {
		return err
	}
	if fc.Server.Host != "" {
		c.ServerHost = fc.Server.Host
	}
	if fc.Server.Port != 0 {
		c.ServerPort = fc.Server.Port
	}
	if fc.Ollama.BaseURL != "" {
		c.OllamaBaseURL = fc.Ollama.BaseURL
	}
	if fc.Ollama.APIKey != "" {
		c.OllamaKey = fc.Ollama.APIKey
	}
	if fc.Worker.BaseURL != "" {
		c.WorkerBaseURL = fc.Worker.BaseURL
	}
	if fc.Pairing.TTLSeconds > 0 {
		c.PairingTTL = time.Duration(fc.Pairing.TTLSeconds) * time.Second
	}
	if fc.Data.Path != "" {
		c.DataPath = fc.Data.Path
	}
	return nil
}

func applyEnv(c *Config) {
	if v := os.Getenv("MODELRIG_HOST"); v != "" {
		c.ServerHost = v
	}
	if v := os.Getenv("MODELRIG_PORT"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			c.ServerPort = n
		}
	}
	if v := os.Getenv("MODELRIG_OLLAMA_URL"); v != "" {
		c.OllamaBaseURL = v
	}
	if v := os.Getenv("MODELRIG_OLLAMA_KEY"); v != "" {
		c.OllamaKey = v
	}
	if v := os.Getenv("MODELRIG_WORKER_URL"); v != "" {
		c.WorkerBaseURL = v
	}
	if v := os.Getenv("MODELRIG_DATA"); v != "" {
		c.DataPath = v
	}
	if v := os.Getenv("MODELRIG_PAIRING_TTL"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.PairingTTL = time.Duration(n) * time.Second
		}
	}
	if v := os.Getenv("MODELRIG_CLAIM_MAX"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			c.ClaimMax = n
		}
	}
}

// Addr returns host:port for ListenAndServe.
func (c Config) Addr() string {
	return c.ServerHost + ":" + strconv.Itoa(c.ServerPort)
}

// IsLoopback reports whether the bind host is loopback (a LAN footgun).
func (c Config) IsLoopback() bool {
	return c.ServerHost == "127.0.0.1" || c.ServerHost == "localhost" || c.ServerHost == "::1"
}
