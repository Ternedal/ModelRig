# Kroppen i Kaliv — den indlejrede renderer

**Retning 29/9/2026:** BodyRig V1's reference-renderer er fortsat Unity/UniVRM
(VRM 1.0) med AR Foundation. Værtsvalget blev revideret 4/9: MVP er den
separate **Kaliv Body** Android-app (`dk.ternedal.kalivbody`) startet fra Kaliv
med package-pinnede intent-extras. **Unity as a Library** er fortsat V2-sporet,
hvis kroppen senere skal indlejres i selve Kaliv-appen.

## 1. Formål

Den valgte persons krop (Person Revision → `body`-kandidat → `.mrbody`) står i
brugerens rum på telefonen, bevæger sig og taler i takt med Kaliv, og skifter
når personen skifter — uden at brugeren forlader Kaliv-appen.

## 2. Hvad der findes (main + samlet kandidat #1964, afstemt 29/9)

| Lag | Status |
|---|---|
| `.mrbody`-format, profil-store, current-binding, digest-bound renderer-handoff | landet (M2.5–M2.8) |
| Runtime-tilstand (`BodyRigRuntime`), face-/motion-mixere, `render_frame` v0.1-wire | landet |
| Unity/VRM-renderer (blink, mund, visemer, emotion, gaze, breath, gesture-router) | landet (#830) |
| Person Profile-registry med atomisk aktivering; `active_bindings().body` | landet (#752) |
| **Live frame-feed fra Kalivs faktiske tur og tale** | **landet (#843)** — `/body/frames` SSE fra `BodyRigRuntime`, drevet af chat-faser og TTS |
| **Server assets + live frames over HTTP** | **landet i L1 (#842–#844)** — backend forwarder aktive assets og `/body/frames` |
| **Unity live-frame + remote avatar-klient** | **samlet i #1964** — authenticated SSE, digest-bundet aktiv avatar + BodyPrint scale |
| **Kaliv Body Android-host** | **samlet i #1964** — package-id, ARM64/minSdk, strict batch-build, RigLink og remote avatar |
| **AR Foundation / ARCore** | **samlet i #1964** — pinned packages, loader, runtime probe, plane/raycast placement |
| **Fysisk Android live-body gate** | **samlet i #1964** — build/install/launch, live body, detected-plane placement, human visual acceptance og independent gate |
| **Unity as a Library i Kaliv** | **V2 / ikke MVP-krav** |

## 3. Lagene, i rækkefølge

**L1 — riggen taler til klienten (Python + Go, verificerbart i CI).**
- `GET /api/v1/body/active` → manifest for den valgte persons krop (id, navn,
  avatar-digest, tilgængelige motions, thumbnail) — fra `active_bindings()`,
  aldrig fra en komponentliste.
- `GET /api/v1/body/active/avatar.vrm`, `.../thumbnail.png`,
  `.../motions/{name}.vrma` — kun de validerede arkiv-medlemmer, digest-bundet.
- `GET /api/v1/body/frames` (SSE) — `render_frame` v0.1 produceret af en
  BodyRig-runtime-session, der følger turen (idle/listening/thinking/speaking/
  interrupted) og VoiceRigs taletiming (`audio_envelope`, visemer). Kaliv
  sender mening (BodyCue) — aldrig knogler.
- Alt bag device-token, loopback-worker, lukket allowlist — som `/persons`.

**L2 — Unity-projektet bliver en rigtig netværksklient.**
- `BodyRigRemoteAvatarSource` henter den aktive avatar + bodyprint fra riggen
  med Bearer-token og verificerer body/package/member SHA-256 før load.
- `BodyRigFrameSource` abonnerer på authenticated `/api/v1/body/frames` SSE
  med redirect-refusal og monotone frame-timestamps.
- `BodyRigRigLink` tager authority fra environment eller Kalivs package-pinnede
  intent-extras; Kaliv Body har ingen selvstændig pairing/token-store.

**L3 — separat Kaliv Body Android-host (MVP).**
- Unity-projektet pinner `dk.ternedal.kalivbody`, ARM64, minSdk 28 og et strict
  `BuildAndroid()` entrypoint.
- AR Foundation + ARCore er versionspinnet; buildet aktiverer ARCoreLoader
  fail-closed og runtime bootstrapper ARSession, XROrigin, tracked camera,
  plane/raycast managers og BodyRig-placement.
- Unity as a Library er fortsat V2 og er ikke en blocker for MVP.

**L4 — fysisk bevis.**
- `run-kaliv-body-android-validation.ps1` bygger/installere/launcher på én
  autoriseret ADB-enhed og binder host, RigLink, avatar, live frames, ARCore og
  plane-placement til exact HEAD.
- `accept-kaliv-body-android-visual.ps1` registrerer eksplicit menneskelig
  visuel accept.
- `kaliv_body_android_physical_gate.py` gen-hasher APK/logcat/receipts og
  emitterer den content-addressede release-evidence-ref.

## 4. MVP → V1 → V2

- **MVP:** L1 + L2 (netværkskilde, ingen AR) + L3. Kroppen vises i Kaliv på
  neutral baggrund og bevæger mund/hoved i takt med Kalivs svar.
- **V1:** ARFoundation — kroppen i rummet, på gulvet, i rigtig størrelse.
  Personskift skifter kroppen.
- **V2:** Windows-desktop-indlejring; Quest-klient ad samme library-vej;
  ansigtsfidelity (BodyRig V1.1).

## 5. Ikke-mål

- Ingen web-renderer (three.js) som omvej — besluttet fra.
- Ingen cloning-logik i Kaliv; BodyRig ejer bygning af `.mrbody`.
- Ingen aktivering af krop uden om Person Revision — `active_bindings()` er
  eneste kilde, også for rendereren.

## 6. Risici og åbne spørgsmål

- Unity kan ikke bygges i CI uden licens; C#-ændringer verificeres på riggen
  gennem den fysiske proof. Python/Go-lagene (L1) verificeres i CI som alt
  andet.
- APK-størrelse med IL2CPP + UniVRM + ARFoundation: forventeligt +60–100 MB.
- ARFoundation kræver ARCore-understøttet enhed (Pixel 6a: ja).
- Frame-feedets latenstid over LAN vs. mesh-isolation — samme `adb reverse`-
  udvej som chatten, hvis nødvendigt.

## 7. Næste skridt

1. **L1: landet på main.**
2. **L2–L4 software:** land #1964, som samler live frames, RigLink, remote avatar,
   BodyPrint scale, Android-host, ARCore/runtime placement og de fysiske gate-værktøjer.
3. **Fysisk qualification:** kør exact-head Android live-body proof + human visual
   acceptance + independent physical gate på den samme kandidat.
4. **Release:** brug kun den content-addressede
   `kaliv-body-android-physical-gate:<sha>:<sha256>` evidence-ref i system release-gaten.
   UaaL forbliver V2 og er ikke nødvendig for denne gate.

## 8. Status 3/9 — afstemt med `UNITY_RENDERER_ROADMAP.md`

Denne plan og roadmappen (#832) blev skrevet parallelt af to sessioner 2/9
aften. De er enige om alt undtagen ét punkt, og det står nedenfor.

**L1 er landet på main, som beskrevet her:** `/api/v1/body/active` + assets
(#842), `/api/v1/body/frames` SSE fra `BodyRigRuntime` + `EmbodimentScheduler`
drevet af chat-faser og TTS-sætninger (#843), telefonens afspilningsrapporter
(#844), cues default fra (#848), cache mod re-validering pr. frame (#850),
ingen timeout på streamen (#851), klient-rapporterbare tilstande begrænset
til `listening`/`idle` (#852). `KALIV_BODY_STORE` i appliancens env.

**L2's netværkskilde er skrevet og restacket:** det historiske #846 blev lukket
uden merge; den nyttige kerne (`BodyRigFrameSource` + bootstrap + CI-kontrakt)
er genoprettet på current main som #1920. Samme `Apply` som fixturen, samme
værn og genforbindelse; bootstrappen vælger den kun med både
`BODYRIG_RIG_URL` og `BODYRIG_RIG_TOKEN` sat. Unity-kompilering/fysisk proof
mangler stadig. UaaL-eksportindstillingerne er ikke lavet.

**Valget om MVP-værten — taget 4/9, reversibelt:** separat **Kaliv Body**-app
først (Unity-projektet bygget til Android, pakkenavn `dk.ternedal.kalivbody`),
startet fra Kalivs ⋮ → **Krop** med riggen og Kalivs eget token som
intent-extras (`KalivBodyBridge`), så den aldrig parres selv. Unity as a
Library inde i Kaliv forbliver V2-vejen, hvis Anders vil have én app; alt
under værten (assets, frames, RigLink, AR-placering) er det samme. Begrundelse:
færrest bevægelige dele, ingen Gradle-integration i en app der bygges rent i
CI, og kroppen kan ses på telefonen, før man beslutter noget om indlejring.

**Det oprindelige åbne valg, til reference:** denne plan siger Unity as a Library inde i
Kaliv fra MVP; roadmappen siger separat "Kaliv Body"-app først og UaaL som
V2-spørgsmål (build-kompleksitet, APK +60–100 MB, én Gradle-integration mere
i en app der i dag bygges rent i CI). Begge veje bruger samme L1 og samme
Unity-kilde; kun L3 er forskellig. **Anders afgør**, når #720 er landet og
kroppen er set på Windows.

**Første krop og rig-dagen:** `docs/bodyrig/FIRST_LIVE_BODY.md` +
`scripts/bodyrig_demo_body.py` (#847).


## 9. Status 29/9 — samlet Android-kandidat

#1964 erstatter de gamle #1920/#1921–#1925/#1939–#1958 spor som den samlede
current-main Android-renderer-kandidat. Den er bevidst fladet ud på seneste
`main`, så releasebeviset kan bindes til én exact head. Den giver **ingen**
production authority; fysisk/human evidence skal stadig produceres særskilt.
