# ModelRig / Kaliv — Roadmap

> **Gældende version:** se `VERSION` · **Dato:** 2026-07-13 · **Ejer:** Anders
> **Status:** Gul. Backend er sikkerhedshærdet, versionsdrift mekanisk lukket, og
> **apparatdriften er bygget** (supervisor med autostart + crash-restart, updater med
> rollback, ressource-varsling — 1.58.8–1.58.14). Fokus nu er **integration + hardening**,
> ikke nye capabilities: to eksterne audits peger på klient-integrationsfejl (chained-writes
> og RAG→cloud-toggle virker ikke i appen endnu), en åben auto-cloud-fallback (privacy), og
> executable-supply-chain uden checksums. Det resterende er i høj grad **validering på
> hardware** + klient-fixes — ikke backend-kode.
>
> Kompakt Now/Next/Later. **Vedtaget 13/7-2026**; afløser den gamle sprawlende roadmap,
> hvis fulde V1–V15-historik nu ligger i `HISTORY.md` (intet slettet). Autoritativ version
> er altid `VERSION`; sikkerhedsbaseline + accepterede risici i `SECURITY.md`.

---

## Vision

Lokal AI-platform der giver en Claude-lignende oplevelse med lokale open source-modeller
via Ollama. **Backend er eneste gateway** — klienter taler aldrig direkte med en
model-runtime. Slutbilledet er et **apparat**, ikke et evigt projekt: Kaliv starter,
overvåges og gendanner sig selv, og featuretoget stopper bevidst.

## Produktprincipper / invarianter

- Lyd forlader aldrig huset (ASR + TTS lokalt; cloud kun til LLM, eksplicit valgt).
- **Alle *model-initierede* writes går gennem workerens confirmation gate.**
  (IKKE "alle writes på platformen" — modelsletning m.m. er klient-bekræftet. Se D3.)
- Alt lokalt og sletbart. Ingen automatisk cloud-fallback (beskytter "100% lokal").
- Tailscale (WireGuard) er eneste sanktionerede remote-transport; rå LAN = accepteret
  risiko (`SECURITY.md`).
- Kun Windows + Android. CI bygger ikke Linux/macOS-desktop.

---

## NOW — Stabilisér & sikker baseline (1.58.x)

**Mål:** Seneste main er dokumenteret, versions-konsistent, sikker som baseline, og de
kendte on-device-tests har et registreret resultat.

| # | Leverance | Status / Acceptkriterium |
|---|---|---|
| N1 | Én VERSION-kilde + CI-gate | ✅ **Gjort.** `VERSION` + `version_tool.py` (sync/check); CI `version-check` gater build på tag- og site-match. |
| N2 | Committet signeringsnøgle | ✅ **Risiko accepteret** (`SECURITY.md`): solo/sideload, ingen store, appen taler kun mod egen backend. Ingen rotation nu; revurderes hvis appen distribueres bredt. |
| N3 | Synk docs → 1.58.2 | Delvist ✅: `VERSION`/`ROADMAP`/Notion aktuelle; `STATUS`/`HANDOFF` har banner der peger på autoritativ tilstand (historiske logs bevaret). |
| N4 | Security baseline | ✅ **Gjort.** `SECURITY.md`: trust boundaries, credentials, accepterede risici, defaults, rotation/incident. |
| N5 | De 5 on-device-tests | ⏳ **Afventer (Anders tester i dag):** streaming-voice S1–S4, desktop 1.58 mod designguide, samtale-eksport/import. |
| N6 | Bevist backup/restore | ⏳ Afventer rig. (CI kører allerede `worker_backup.py` round-trip pr. release — men ikke bevist på selve riggen.) |
| N7 | Model-eval baseline | ⏳ Afventer rig: `qwen3:14b` + baseline via eval-harness (MODELS.md har kommando + kriterier). |

**Exit:** CI grøn · versionskilder matcher (gaten håndhæver) · ingen P0/P1 uden dokumenteret
risikoaccept ✅ · de 5 device-tests har resultat · recovery bevist på riggen.

---

## NEXT → I HØJ GRAD BYGGET — "Kaliv som apparat" (1.58.8–1.58.14)

**Mål:** Kaliv starter, overvåges og gendannes uden manuel terminaldans.

Bygget: `modelrig-supervisor` (autostart ved logon via Task Scheduler · genstart ved crash/
unhealth · logrotation · egen supervisor-log · indlæser `modelrig.env` til børnene) ·
`modelrig-updater` (backup + swap + **auto-rollback**, verificerer BÅDE backend og worker) ·
disk/VRAM-varsling (off watchdog-path, med timeout). Auto-backup fandtes i forvejen.

**Udestår:** (a) **on-device-validering** af hele matricen (reboot→brugbar · kill-proc→genstart ·
korrupt release→rollback); (b) **executable-supply-chain** — SHA-256-verificeret (1.58.15: release publicerer
`SHA256SUMS.txt`, updateren tjekker før swap); næste niveau = signeret manifest; (c) diskchecket måler
kun supervisorens drev; (d) TLS/reverse-proxy-politik.

**Exit:** *Sluk strømmen, tænd igen → Kaliv er brugbar uden manuel processtart. En dårlig
opdatering kan rulles tilbage.* — kode findes; **mangler on-device-bevis + supply-chain-integritet.**

---

## NEXT — Voice & agent-pålidelighed

**Mål:** Stabil samtaleassistent *før* hun bliver "ambient".

Leverancer: afslut streamende voice-validering (**mål TTFA**, ikke "føles hurtigere") ·
streaming-ASR · voice-tools m. eksplicit mundtlig bekræftelse · eval-baseline for lokal
model · cloud-agent-test · **beslut privacy-regel for RAG + auto-cloud** (D4) før evt.
automatisk routing.

**Exit:** voice-turn stabil 10× i træk · stop/barge-in efterlader intet hængende · agent
slår baseline på tool-disciplin · cloud-routing er synlig + følger skreven privacyregel.

**Kendt åbent issue:** voice 501 / Piper-TTS (diagnose kører på riggen).

---

## LATER — Udvidelser med konkret brugerbehov

- **Knowledge/vision:** visionmodel på riggen · dansk foto-chat · samtaler som valgfri
  RAG-kilde · dedup + embedding-versionering · skaleringstest før vector-DB.
  *(Foto→RAG-plumbing er færdig; resten er primært model-/hardwarevalidering.)*
- **Integrationer:** Home Assistant read-only → writes m. confirmation gate · scheduler for
  read-only jobs · eksternt API m. scoped credentials + transportbeskyttelse.

---

## NOT NOW — betingede horisonter (aktiveres kun ved målt behov)

- **Multi-device** ≠ **multi-user.** Flere enheder til dig er lille (store'et har allerede
  device-liste + token-hashes + revocation → mangler mest 2-klient-test + delt/separat
  historik-beslutning). Flere *personer* m. isolerede data er et stort nyt sikkerheds-/
  datamodelspor — betinget af faktisk husstandsbehov.
- Egen finjusteret model (kun ved målt modelproblem + grund til ikke at bruge cloud).
- Føderation/split-rig, dedikeret Kaliv-station, e-ink-display — betinget af målt
  strøm-/availability-behov.

---

## Tværgående kvalitetsporte (gælder hver leverance)

Funktion bevist (ikke bare implementeret) · nye fejlklasser har regressionstest · trust
boundary/credentials/writes vurderet · health/logs/recovery beskrevet · migration/backup/
rollback vurderet · relevant latency/ressource **målt** · hardware-test ved UI/device-
ændringer · kun aktuelle docs opdateres · artefakter findes + versioner matcher (CI-gate) ·
ikke-verificerede dele mærkes eksplicit.

**Mål med tal (erstat "virker"):** tekst-TTFT · voice-TTFA · RAG p95 @ 1k/10k chunks ·
koldstartstid · maks RAM/VRAM · succesrate over 10–20 gentagelser · restore-tid · antal
manuelle trin efter genstart.

---

## Åbne beslutninger (kræver Anders)

- **D3 — Write-invariant:** skal modelsletning m.m. også bag en server-side gate, eller
  forbliver det klient-bekræftet? (Præcisér invarianten uanset.)
- **D4 — Cloud-voice privacy:** regel for RAG-kontekst + auto-cloud før nogen automatisk routing.

*Afgjort 13/7-2026: **D1** keystore = risiko accepteret (`SECURITY.md`) · **D2** VERSION-kilde
+ CI-gate = leveret · **D5** dokumentstruktur = lean (denne fil + `STATUS.md` + `SECURITY.md`)
· ROADMAP_V2 vedtaget.*

---

## Afhængighedsrækkefølge

```
Sikker baseline (NOW)
  → Apparatdrift (NEXT)
    → Voice/agent-pålidelighed (NEXT)
      → Ambient/proaktiv + integrationer (LATER)
        → betingede horisonter (NOT NOW)
```

Faser navngives ved **navn** (Baseline, Apparat, Voice, Agent, Integrationer) — ikke
V-numre — så de ikke forveksles med SemVer (`v1.58.2`). Softwareversion forbliver SemVer.
