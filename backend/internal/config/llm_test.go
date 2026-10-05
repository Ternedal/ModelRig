package config

import "testing"

func TestLLMProviderDefaultsToOllama(t *testing.T) {
	t.Setenv("MODELRIG_CONFIG", "")
	t.Setenv("MODELRIG_LLM_PROVIDER", "")
	t.Setenv("MODELRIG_LLM_URL", "")
	c, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.LLMProvider != "ollama" {
		t.Fatalf("LLMProvider = %q, want ollama", c.LLMProvider)
	}
}

func TestLLMProviderEnvironmentSelectsJan(t *testing.T) {
	t.Setenv("MODELRIG_CONFIG", "")
	t.Setenv("MODELRIG_LLM_PROVIDER", " JAN ")
	t.Setenv("MODELRIG_LLM_URL", "http://127.0.0.1:1337/v1/")
	t.Setenv("MODELRIG_LLM_KEY", "secret")
	c, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if c.LLMProvider != "jan" {
		t.Fatalf("LLMProvider = %q, want jan", c.LLMProvider)
	}
	if c.LLMBaseURL != "http://127.0.0.1:1337/v1" {
		t.Fatalf("LLMBaseURL = %q", c.LLMBaseURL)
	}
	if c.LLMKey != "secret" {
		t.Fatal("LLMKey was not loaded")
	}
}
