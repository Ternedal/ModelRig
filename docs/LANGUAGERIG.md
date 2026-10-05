# LanguageRig — første softwareforløb

LanguageRig er en separat installerbar træningskomponent i ModelRig-repoets
languagerig-mappe. Den kan senere flyttes til et selvstændigt repo uden at ændre
ModelRigs runtime-kontrakter. Den første operatørflade er en CLI.

| Ansvar | Ejer |
| --- | --- |
| Bogimport, metadata, datasætsnapshots og træningsjob | LanguageRig |
| Grundmodellens weights/tokenizer/chat-template | Valgt modeludgivelse |
| Modelregistrering og inference | Lokal Ollama |
| Modelvalg, chat, værktøjer og eksisterende RAG-index | ModelRig |
| Vedvarende identitet/kognitiv tilstand | Eksisterende ModelRig-komponenter |

~~~mermaid
flowchart TD
    Books["EPUB og PDF"] --> Import["Import og kilde-ID"]
    Import --> Corpus["Værkbaserede datasæt"]
    Import --> Export["Kapitelbaseret RAG-eksport"]
    Corpus --> Train["QLoRA og checkpoints"]
    Train --> Merge["Merge og GGUF-konvertering"]
    Merge --> Ollama["Lokal Ollama-kandidat"]
    Export --> RAG["ModelRig RAG"]
    Ollama --> Eval["Baseline og kandidat"]
    Eval --> Review["Menneskelig kvalitetsvurdering"]
    Ollama --> MR["ModelRig modelvalg"]
    RAG --> MR
~~~

## Status og grænser

- Implementeret: EPUB spine/metadata, tekst-PDF, fejlrapport pr. fil,
  genimport/dubletter, genre/emne/work-id, tre værkbaserede splits,
  passage-deduplicering og checksum-bundne snapshots.
- Implementeret: valgfri Transformers/PEFT QLoRA-runner til én GPU,
  låst modelrevision, checkpoint-resume og sidste-assistentsvar-maskering
  ved instruktionsdata. Afhængigheder og CUDA kræves ved udførelse.
- Implementeret: adapter-merge, pakning af operatørkonverteret GGUF,
  eksplicit lokal Ollama-registrering og eksisterende RAG-API-handoff.
- Implementeret: direkte Ollama-sammenligning med modeldigests,
  formatkontroller og HTML til menneskelig vurdering.
- Afventer: faktisk GPU-træning, dansk/faglig modelgevinst, konverterings-
  kvalifikation på valgt arkitektur, rigtige værktøjskald og klienttest.
- Senere produktarbejde: grafisk bogvælger, kategoriforslag, OCR,
  kvalitetstjekket dialoggenerering og multi-GPU-profiler.

Trained, registered og completed comparison er forskellige tilstande.
Ingen af dem er i sig selv en modelkvalitetsdom eller en systemrelease.
ModelRig ændrer ikke standardmodel automatisk.

Munin Apertus 8B er kun pilotkonfigurationens kandidat. Dens arkitektur passer
til AutoModelForCausalLM; Munin Ministral 8B bruger derimod
Mistral3ForConditionalGeneration og kræver en særskilt integration.
Munin 1.0 har danske
gevinster i nogle opgavegrupper, men dens officielle evaluering viser også
tab på nogle engelske/agentiske opgaver. Udvælgelsen bør derfor sammenligne
dansk kvalitet, faglige svar, ressourceforbrug og ModelRig-relevante værktøjskald.
Mimir kræver HRM-Text/PrefixLM-understøttelse og er ikke kvalificeret af dette
generiske AutoModelForCausalLM-forløb.

## Kilder og reproduktion

- [Munin 1.0-udgivelse](https://www.foundationmodels.dk/da/news/2026/06/11/munin-10-udgivelsesnote.html)
- [Munin Apertus 8B-modelkort](https://huggingface.co/danish-foundation-models/munin-apertus-8b)
- [Munin Ministral 8B-modelkonfiguration](https://huggingface.co/danish-foundation-models/munin-ministral3-8B/blob/main/config.json)
- [PEFT: kvantisering og QLoRA](https://huggingface.co/docs/peft/developer_guides/quantization)
- [Transformers Trainer](https://huggingface.co/docs/transformers/main_classes/trainer)
- [Ollama-modelimport](https://docs.ollama.com/import)

Datasætmanifestet binder kildeinddeling og datafiler. Run-manifestet binder
konfiguration, datasæthash og præcis modelrevision. GGUF-handoff gemmer
weights/Modelfile-checksums og angiver eksplicit operator_supplied_gguf.
Sammenligningen binder cases og de faktisk observerede Ollama-modeldigests.

Alle brugerdata/modelvægte holdes uden for Git. Se
[LanguageRig README](../languagerig/README.md) for Windows/WSL-kommandoer.
