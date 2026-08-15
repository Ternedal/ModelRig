package httpapi

import (
	"net/http"
	"time"
)

// Frigør VRAM: POST /api/v1/models/unload
//
// Ollama holder en model i VRAM indtil dens keep_alive udløber. Et kald til
// /api/generate med keep_alive=0 beder Ollama slippe modellen MED DET SAMME.
// Vi bruger altså Ollamas egen mekanisme — ingen processer dræbes, intet
// genstartes, og næste prompt indlæser modellen igen af sig selv. Den eneste
// pris er, at det næste svar bliver langsommere.
//
// BEVIDST IKKE BYGGET: "Genstart model-server". At dræbe og starte Ollama
// udefra kræver en supervisor-kontrakt på riggen; fejler genstarten, står
// telefonen tilbage uden nogen vej til at rette op. Unload giver den samme
// VRAM-gevinst uden den fælde.

type unloadedModel struct {
	Name string `json:"name"`
	// Bytes er hvad Ollama rapporterede FØR unloaden — altså hvad der blev
	// frigjort, ikke et estimat.
	Bytes int64 `json:"size_vram_bytes"`
}

func (s *server) handleModelsUnload(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	// Fail-closed frem for panik: er der ingen Ollama-upstream konfigureret,
	// er der heller ingen VRAM at frigøre — sig det som en fejl, ikke som
	// en tom succes.
	if s.Ollama == nil {
		writeErr(w, http.StatusBadGateway, "ingen model-server konfigureret")
		return
	}

	var ps struct {
		Models []struct {
			Name     string `json:"name"`
			Model    string `json:"model"`
			SizeVRAM int64  `json:"size_vram"`
		} `json:"models"`
	}
	if err := s.Ollama.GetJSON(ctx, "/api/ps", &ps); err != nil {
		writeErr(w, http.StatusBadGateway, "kunne ikke læse indlæste modeller")
		return
	}

	unloaded := make([]unloadedModel, 0, len(ps.Models))
	var failed []string
	for _, m := range ps.Models {
		name := m.Name
		if name == "" {
			name = m.Model
		}
		if name == "" {
			continue
		}
		// keep_alive=0 => slip modellen nu. Tom prompt betyder at Ollama ikke
		// genererer noget; kaldet er kun en livstids-direktiv.
		body := map[string]any{"model": name, "prompt": "", "keep_alive": 0}
		if err := s.Ollama.PostJSON(ctx, "/api/generate", body); err != nil {
			failed = append(failed, name)
			continue
		}
		unloaded = append(unloaded, unloadedModel{Name: name, Bytes: m.SizeVRAM})
	}

	var freed int64
	for _, u := range unloaded {
		freed += u.Bytes
	}
	// Delvis succes rapporteres som delvis: klienten skal kunne sige sandheden.
	writeJSON(w, http.StatusOK, map[string]any{
		"schema":      "kaliv-models-unload/v1",
		"unloaded":    unloaded,
		"freed_bytes": freed,
		"failed":      failed,
		"at":          time.Now().UTC().Format(time.RFC3339),
	})
}
