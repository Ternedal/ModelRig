# Unity/UniVRM-rendereren — vejen fra proof til produkt

**Beslutning 2/9/2026 (Anders):** den rigtige løsning er Unity/UniVRM-sporet
fra `BODYRIG_V1.md` — ikke en web-renderer. Kaliv skal kunne **vise,
afspille og afvikle** `.mrbody` på Windows, Android (AR) og Quest.

## Hvad der findes (main + #720)

| Lag | Status |
|---|---|
| `.mrbody` v1 (VRM 1.0 + VRMA + bodyprint) | landet, kontraktgatet |
| Profil-store, current-binding, digest-bound renderer-handoff (M2.6–M2.8) | landet |
| `BodyRigRuntime` tilstandsmaskine (idle/listening/thinking/speaking/waiting_for_tool/interrupted/error) | landet i core |
| Render-frame wire v0.1 (`bodyrig.render_frame`) | landet i core |
| Unity `6000.3.21f1` + UniVRM `v0.131.2` proof: VRM-load, blink, envelope-mund, visemes, emotion, gaze, breath, gesture-router, afbrydelse | **#720, draft — venter kun på fysisk gate** |
| Worker-udstilling af BodyRig (runtime, frames, assets) | **findes ikke** |
| Android/Quest-klient | **findes ikke** |

Unity-proofen afspiller en canned fixture (`bodyrig-demo.json`). Den har ingen
netværkskilde. Det er hullet mellem proof og produkt.

## MVP — proofen lander (BodyRig-spor, Anders på riggen)

1. Unity `6000.3.21f1` i Hub på standardstien; en rigtig VRM 1.0-avatar
   (VRoid Studio); `.mrbody` bygget, installeret og valgt i en profil-store.
2. `bodyrig_unity_physical_proof.ps1` → visuel accept → `bodyrig_unity_physical_gate.py`.
3. #720 ud af draft og ind på main. Ingen kode her — kun fysik.

## V1 — live krop på Windows og Android (ModelRig-spor, starter nu)

**Slice A — asset-levering (renderer-neutral). LANDET 3/9.** Worker: `GET /body/active`
(manifest: body id, navn, sha256, hvilke motions findes), `/body/active/avatar.vrm`,
`/body/active/motions/{navn}.vrma`, `/body/active/thumbnail.png` — læst gennem
M2.8-handoff'en (kun validerede bytes, digest-bundet), for den valgte persons
body-revision (#752) eller current-binding. Backend forwarder `/api/v1/body/*`
bag device-token, lukket allowlist. Det er det, telefon og Quest henter
kroppen fra; Windows-proofen kan blive ved fil-stien. Konfiguration:
`KALIV_BODY_STORE=<profil-store-mappe>` i appliancens env; uden den svarer
fladen 503 og siger hvilken variabel der mangler. Svar bærer
`X-BodyRig-Body-ID`, `X-BodyRig-Package-SHA256` og `X-BodyRig-Member-SHA256`,
som proxyen lader passere (præfiks-allowlist), så klienten kan verificere.

**Slice B — live frames. LANDET 3/9.** Worker: én `BodyRigRuntime`-session pr. valgt
person, drevet af det der allerede sker i chatten: turn-start → `thinking`,
tool-kald → `waiting_for_tool`, TTS-sætning → `speaking` med `audio_envelope`
fra voice-pipelinen (visemes når VoiceRig leverer timing), stop → `interrupted`
→ `listening`. Udstillet som `GET /body/frames` (SSE: én v0.1-frame pr. linje)
bag samme forwarding. BodyCue-mapning (emotion/gesture fra svaret) er en
separat, lille slice ovenpå — landet 3/9 som `body_cues.py`, **default fra**
(`KALIV_BODY_CUES=1`): `explain` for lange sætninger, `curious` under
thinking, `concerned` ved fejl, nulstilling ved idle/listening/interrupted.
Ingen sentiment-udledning fra ordene.
Som landet: `GET /body/state` (én frame), `GET /body/frames` (SSE, 20 fps,
valgfrit `?limit=N`), `POST /body/interrupt` (hård afbrydelse: alle
utterances annulleres, mund nulstilles, `interrupted`), `POST /body/state/{navn}`
(klienten melder kun det, kun den ved: `listening` når mic er åben, `idle`
når brugeren er gået — andre tilstande afvises med 422; de ejes af turen,
talen, afbrydelsen og fejlvejen). Uden aktiv
krop svarer alt 404, og hooks i chat/voice er no-ops. Talestart er
syntesetidspunkt på riggen som tilnærmelse; **telefonen melder
afspilning** (`POST /body/speech/{utterance}/started|ended`, utterance-id
følger med hvert `chunk`-event), så munden forankres til det, der faktisk
høres. Gamle klienter beholder tilnærmelsen; en rig uden krop svarer 404,
og appen holder op med at melde for resten af sessionen.

**Slice C — Unity frame-kilde. SKREVET 3/9 (#846, draft mod #720-grenen; kompilerer kun i Unity).** Rendereren får en `BodyRigFrameSource` der
kan læse frames fra fixturen (som nu) ELLER fra `/body/frames` (UnityWebRequest,
SSE). Fixturen bliver ved at være den deterministiske testkilde. C#-ændringen
er lille; den verificeres af den fysiske gate, ikke af CI.

**Slice D — Android-host + AR.** Kaliv Body som separat Unity Android-app
først (parring som enhver anden klient; asset + frames fra rig), ARFoundation
for kamera-passthrough og plan-forankring. Unity as a Library ind i Kaliv-appen
er V2-spørgsmålet — det koster build-kompleksitet, og en separat app beviser
alt det samme.

## V2 — Quest og fidelity

Quest-target (IL2CPP, OpenXR), ansigtsmixer (M2.9+), profil-egne `.vrma`-
gestures gennem gesture-routeren, BodyCue med emotion-klassifikation fra svaret.

## Hvad der IKKE flytter sig

`production_activation` er urørt. Ingen kloningslogik ind i Kaliv. Core
forbliver renderer-neutral: intet HumanBodyBones, ingen Unity-stier, ingen
VRM-expression-nøgler krydser grænsen — kun v0.1-frames og validerede assets.

## Rækkefølge

A og B kan bygges og testes uden Unity og lander i dev-kanalen. C kræver at
#720 er landet (ellers redigerer vi en draft). D kræver C og en Android-build
af Unity-projektet. MVP (den fysiske gate) er uafhængig og kan ske parallelt.

Rig-runbook for den første levende krop: `docs/bodyrig/FIRST_LIVE_BODY.md`.

**Parallel plan for den indlejrede vært (UaaL + ARFoundation):**
`docs/bodyrig/KALIV_EMBEDDED_RENDERER.md` — detaljerer L2–L4 og ét åbent valg om
MVP-værten (indlejret i Kaliv vs. separat app), som Anders afgør efter #720.
