# ISOLATION_DESIGN.md — sandboxing før computer-use (F-012)

> **Beslutning (Anders, 16/7-2026):** computer-use ER en del af pakken. Lokal
> PC-styring først, browser senere. Ligger EFTER Agent 3 + valideringsrunden.
> **Isolation løses FØRST** — før det første computer-use-tool.
>
> Dette dokument er designet for den isolation. Grundet i kodelæsning
> (tools.py), ikke i antagelser. Skelner Verificeret / Design / Åbent-kræver-rig.

## 1. Konklusion først

Der er **to isolationsklasser**, og det er vigtigt ikke at lyve om den anden:

- **Tier A — data/compute-tools** (fil-læs, kommando-kørsel, web-fetch): kan
  isoleres ægte. Separat proces, reduceret token, job object, scoped rod, ingen
  netværk pr. default, timeout, output-cap. **Her virker sandboxing.**
- **Tier B — desktop/computer-use** (screenshot, klik, tastetryk): **kan pr.
  definition IKKE indeholdes fra skrivebordet** — et tool der skal styre din PC
  skal have adgang til din session. En "sandbox" der forhindrer det, forhindrer
  også toolet i at virke.

For Tier B er svaret derfor ikke indeslutning, men **blast radius + bevisbyrde**:
lavere integritetsniveau (kan ikke styre elevated vinduer), mål-allowlist,
screenshot-bundne handlinger (kan ikke handle på forældet skærmbillede),
per-handling-bekræftelse med preview, rate limit, kill-switch, fuld audit.

**Den vigtigste enkeltbeslutning i hele designet:** et screenshot er egress af
det værste slags — din skærm kan vise alt. **Computer-use-tools må derfor være
lokale-model-only pr. default.** En cloud-model der "hjælper med at klikke"
betyder at dit skrivebord forlader huset. Det binder direkte til beslutning #6
og Agent 3's egress-klasser.

## 2. Verificeret nu-tilstand (main @ 1.58.47)

| Fund | Hvor | Betydning |
|---|---|---|
| `InProcessExecutor.execute()` kalder `tool.run(args)` direkte | tools.py:557–562 | Et tool kører I workerens proces, med workerens rettigheder og hukommelse |
| **Sømlinjen findes allerede** — kommentaren over klassen forudser præcis dette: *"Windows account slots in here without touching the gate above it"* | tools.py:555 | Isolation kan indføres UNDER gaten uden at røre gate-logikken. Arkitektonisk held |
| Ingen timeout eller output-cap på executor-niveau | tools.py | Et hængende tool binder en tråd; et snakkesagligt tool kan fylde kontekst/log. Enkelt-tools har egne timeouts (fx `subprocess.run(..., timeout=5)`), men det er tilfældigt, ikke en kontrakt |
| Risk-klasser er kun `read`/`write` | tools.py:84 (`return tool.risk == "write"`) | Der findes ingen `secret`/`desktop`-klasse — computer-use ville i dag arve write-semantik, hvilket er utilstrækkeligt |
| Worker kører som almindelig bruger (Windows: din egen session) | deploy/run-windows.ps1 | Et tool har i dag dine rettigheder |

**Konsekvens:** gaten (parkerede writes, immutable args, TTL, kill-switch) er
stærk om *beslutningen*, men der er intet om *eksekveringen*. Det er præcis
F-012, og det er derfor rækkefølgen "isolation først" er rigtig.

## 3. Trusselsmodel — hvad ændrer sig når tools rører OS'et

| # | Trussel | I dag | Efter design |
|---|---|---|---|
| T1 | Tool hænger (netværk, fil-lås, dialog) | Tråd bundet i workeren; riggen ser sund ud men svarer ikke | ToolHost dræbes ved timeout; job → `failed` med årsag |
| T2 | Tool crasher processen | Worker dør → supervisor genstarter → alle igangværende ture tabt | Kun ToolHost dør; workeren rapporterer fejl |
| T3 | Tool læser filer uden for opgaven | Kan læse alt din bruger kan | Scoped rod + reduceret token |
| T4 | Tool spawner processer/netværk | Frit | Job object (procesloft) + netværk fra pr. default |
| T5 | Model foreslår klik på forkert sted | — (ingen computer-use endnu) | Screenshot-bundet handling + allowlist + preview-bekræftelse |
| T6 | Model driver en elevated app (UAC/admin) | — | Lav integritet → UIPI blokerer input til højere integritet |
| T7 | **Screenshot sendes til cloud-model** | — | **Lokale modeller pr. default; cloud kræver eksplicit, separat samtykke pr. session** |
| T8 | Kompromitteret/hallucinerende model i loop | Gate stopper writes | Gate + rate limit + kill-switch + audit m. screenshots |

## 4. Design

### 4.1 ToolHost — en separat proces

```
worker (FastAPI, :8099)
   │  narrow typed IPC (named pipe på Windows; loopback fallback)
   │  submit(action, args, timeout, caps) → {status, output_capped, duration}
   ▼
modelrig-toolhost.exe   ← reduceret token · Job Object · kill-on-close
   ├── Tier A: fil-læs (scoped rod), run_command (ingen net), web_fetch (egress-klasset)
   └── Tier B: desktop-handlinger (kun i brugerens session, lav integritet)
```

**Hvorfor proces og ikke tråd:** kun en procesgrænse giver dræbbarhed (T1),
crash-isolation (T2) og rettighedsreduktion (T3/T4). Det er også den eneste
måde at få en ægte timeout i Python uden at slås med GIL og ikke-afbrydelige
kald.

**Windows-primitiver (pragmatisk, ingen Docker):**
- **Job Object** med `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` + hukommelses-,
  proces- og CPU-lofter → hele trædet dør med ToolHost, altid.
- **Reduceret token** (`CreateRestrictedToken`) eller separat lokal konto for
  Tier A → filsystem-rod håndhæves af OS'et, ikke af Python-strengtjek.
- **Lav integritet** for Tier B → UIPI forhindrer input til elevated vinduer
  (T6). Det er en ægte grænse, og den er gratis.
- **Ikke AppContainer** for Tier B: det bryder desktop-adgang, som er selve
  formålet. Ikke Docker/WSL for Tier B: der er intet skrivebord derinde.
  (Docker er derimod et fornuftigt V2-valg for Tier A run_command, hvis
  behovet vokser — men en reduceret proces er nok til én rig.)

**Integration med det der findes:** ToolHost-kald bliver et **JobStore-job**
(1.58.47) når det er langvarigt → progress, terminal-sandhed, cancel og
restart-ærlighed er allerede løst. Kortvarige Tier A-kald svarer synkront.

### 4.2 Nye risk-klasser (udvidelse af gaten, ikke omskrivning)

| Klasse | Betydning | Gate-adfærd |
|---|---|---|
| `read` | Uændret | Ingen bekræftelse (interim; #6/Agent 3 afgør egress) |
| `write` | Uændret | Parkeres, bekræftelseskort, TTL, immutable args |
| **`desktop`** | Rører brugerens session | Som `write` **+** preview-kort m. screenshot **+** screenshot-binding **+** allowlist-tjek **+** rate limit **+** kun lokal model uden eksplicit egress-samtykke |
| **`secret`** | Må aldrig forlade huset | Aldrig cloud-origin, uanset samtykke |

### 4.3 Screenshot-bundne handlinger (kernemekanismen for Tier B)

Gatens eksisterende princip — *argumenter kan ikke ændres efter kortet er vist*
— udvides til skærmtilstand:

1. `screenshot` (klasse `desktop`, read-agtig) returnerer et billede **+ et
   `screen_id`** (hash af billedet + tidsstempel).
2. Enhver klik/tast-handling **skal** referere det `screen_id` den blev
   planlagt fra.
3. ToolHost tager et nyt screenshot lige før handlingen og afviser hvis
   skærmen har ændret sig materielt (perceptuel hash uden for tolerance) eller
   `screen_id` er ældre end N sekunder.

**Hvad det køber:** en model kan ikke handle på en forældet skærm (vinduet
flyttede sig, en dialog poppede op) — den fejlklasse er den mest sandsynlige
årsag til reel skade, og den er mekanisk lukkelig. Det er samme invariant som
INV-12/immutable confirmation, anvendt på pixels.

### 4.4 Mål-allowlist

Handlinger må kun ramme vinduer hvis proces/titel matcher en **eksplicit
allowlist** (fx `notepad.exe`, `chrome.exe` med titelmønster). Tomt = ingen
computer-use. Konfigureres af dig, ikke af modellen. Enhver handling mod et
ikke-allowlisted vindue = fejl + audit-post.

## 5. Faseplan (efter Agent 3 + valideringsrunden)

| Fase | Indhold | Acceptance |
|---|---|---|
| **I0a — portabelt substrat** ✅ **LEVERET (1.58.48)** | `toolhost.ProcessExecutor` + `tool_child`: per-kald child-proces, håndhævet timeout m. kill, output-cap, fejl/afvisning krydser grænsen korrekt, credential-fri child-env (allowlist), frozen-exe child-mode. **Dormant**: `KALIV_TOOL_ISOLATION=process` + `Tool.isolate` — ingen tools sætter det endnu | ✅ 13/13 nye tests inkl. ægte child-proces der kører et rigtigt registry-tool; alle eksisterende suiter grønne BÅDE med og uden isolation slået til (delegation bevist sikker) |
| **I0b — Windows-rettighedslaget** 🔶 UDESTÅR (kræver rig) | Job Object (kill-on-close, hukommelses-/proces-lofter), reduceret token, lav integritet. **Grandchildren dækkes ikke af `subprocess`-kill på Windows uden Job Object** — kendt hul, markeret i koden | Hængende procestræ dør helt; tool kan ikke læse uden for scoped rod (OS-nægtet); nedgraderet ToolHost bryder ikke voice/eksisterende tools |
| **I1 — Tier A: fil-læs** | `read_file` (scoped rod, reduceret token, størrelsesloft) | Sti uden for roden = OS-nægtet, ikke Python-tjekket; audit viser sti + bytes |
| **I2 — Tier A: run_command** | Ingen netværk, scoped cwd, timeout, output-cap, `write`-klasse | Netværkskald indefra fejler; 30s-loop dræbes; output afkortet med markering |
| **I0c — Tier B policy** ✅ **LEVERET (1.58.52)** | `desktop_policy.py`: screenshot-binding (`ScreenRegistry`), mål-allowlist (fail-closed), rate limit, cloud-origin-reglen. `desktop`-risikoklassen kender gaten nu (kræver altid bekræftelse). **Dormant** — ingen tools bruger den | ✅ 23 tests på alle kanter: forældet plan nægtes, ukendt `screen_id` nægtes, tom allowlist tillader intet, samme proces nægtes på forkert titel, cloud-origin nægtes uden separat samtykke |
| **I3 — Tier B: se** | `screenshot` (`desktop`, lokal-model-only, `screen_id`, audit m. thumbnail) — policy findes, mangler capture + perceptuel hash | Cloud-origin nægtes uden eksplicit samtykke; hvert screenshot i audit; **tolerance kalibreret på rig** (§6.2) |
| **I4 — Tier B: handle** | `click`/`type` bundet til `screen_id`, allowlist, lav integritet, preview-kort, rate limit | Forældet `screen_id` afvises; ikke-allowlisted vindue afvises; elevated app kan ikke drives (UIPI-bevis) |
| **I5 — browser** | Dedikeret browserprofil (ingen adgang til dine rigtige cookies) + CDP; Tier A-agtig | Din normale profil er urørt; egress-klasset pr. domæne |

**Hver fase = én release + rig-verifikation.** I3/I4 kan kun bevises på din
Windows-maskine (UIPI, integritet, allowlist er OS-adfærd).

## 6. Åbne spørgsmål (kræver rig-data / din beslutning)

1. **Separat lokal konto vs. reduceret token** for Tier A: kontoen er stærkere
   (rigtig filsystem-isolation), men kræver opsætning i appliance-installeren.
   Anbefaling: reduceret token i I1, konto som V2 hvis behovet viser sig.
2. **Perceptuel hash-tolerance** i §4.3: for stram = handlinger afvises på en
   blinkende markør; for løs = forældet skærm slipper igennem. **Kalibreres på
   rig med rigtige apps.**
3. **Lav integritet + din session:** virker Piper/voice og de eksisterende
   tools stadig når ToolHost kører nedgraderet? (Skal testes i I0.)
4. Skal `run_command` (I2) overhovedet med, eller er fil-læs + computer-use
   nok? Kommando-kørsel er den største enkelt-risiko i Tier A.

## 7. Ikke-mål
Cloud-styret computer-use (T7) · fjernstyring af andre maskiner · fuld
VM/hypervisor-isolation (ude af proportion for én personlig rig) ·
AppContainer for Tier B (bryder formålet) · at gøre computer-use "sikkert" —
det bliver **gated, observerbart og begrænset i blast radius**, ikke sikkert.
