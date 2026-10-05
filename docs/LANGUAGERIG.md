# LanguageRig og ModelRig

[LanguageRig](https://github.com/Ternedal/LanguageRig) er det selvstændige repo
til dansk bogimport og modeltræning. Kode, tests, modelkonfiguration, CI og
Windows/WSL-vejledning ligger der. ModelRig har ingen Python-afhængighed på
LanguageRig og fortsætter med sine eksisterende Ollama- og RAG-grænseflader.

| Ansvar | Projekt eller tjeneste |
| --- | --- |
| EPUB/tekst-PDF, metadata, udvælgelse og datasæt | LanguageRig |
| QLoRA, checkpoints, adapter-merge og modelsammenligning | LanguageRig |
| GGUF-konvertering | Operatør med kompatibel llama.cpp-version |
| Lokal modelregistrering og inference | Ollama |
| Modelvalg, chat, værktøjer og bogopslag | ModelRig |

## Modelkandidater

LanguageRig registrerer en pakket kandidat i samme lokale Ollama-instans,
som ModelRig bruger. Adressen skal svare til MODELRIG_OLLAMA_URL. Derefter
kan kandidatnavnet vælges gennem ModelRigs eksisterende modeloversigt.
Standardmodellen ændres ikke automatisk.

Trained og registered er tekniske tilstande. De dokumenterer ikke bedre
sprogkvalitet, fungerende værktøjskald eller en færdig systemrelease.
GPU-træning, konvertering og afprøvning på rigtige klienter afventer riggen.

## Bogopslag

LanguageRig eksporterer accepteret bogtekst med stabile kapitel-/sidekilder.
Publish bruger den eksisterende POST /api/v1/rag/ingest-kontrakt med
documents, chunk_size og chunk_overlap og et allerede parret enhedstoken
fra MODELRIG_DEVICE_TOKEN. Det følger samme kontrakt som tools/modelrig-cli.py.
Der tilføjes ingen ny API, parring eller runtime-komponent i ModelRig.

Den direkte baseline/kandidat-sammenligning i LanguageRig bruger lokal Ollama.
Den evaluerer ikke ModelRigs RAG eller rigtige værktøjskald; disse kræver
særskilte afprøvninger med ens dokumentadgang for modellerne.

## Vejledninger

- [Installation, bogimport og pilotjob](https://github.com/Ternedal/LanguageRig/blob/main/README.md)
- [Arkitektur og status](https://github.com/Ternedal/LanguageRig/blob/main/docs/ARCHITECTURE.md)
- [ModelRig-kontrakter og miljøvariabler](https://github.com/Ternedal/LanguageRig/blob/main/docs/MODELRIG.md)

Den oprindelige pilot i PR #2091 er flyttet til LanguageRig. Denne PR indeholder
nu kun ModelRigs dokumentation og henvisninger til det selvstændige projekt.
