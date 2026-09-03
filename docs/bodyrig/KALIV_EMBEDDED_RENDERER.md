# Kroppen i Kaliv — den indlejrede renderer

**Besluttet 2/9/2026:** `.mrbody` skal vises, afspilles og afvikles *som en del af
Kaliv* — ikke som en separat app — og "AR-agtigt". Den rigtige løsning er
BodyRig V1's reference-renderer (Unity/UniVRM, VRM 1.0) indlejret i Kaliv via
**Unity as a Library**, med **ARFoundation** til kameraet og rummet.

## 1. Formål

Den valgte persons krop (Person Revision → `body`-kandidat → `.mrbody`) står i
brugerens rum på telefonen, bevæger sig og taler i takt med Kaliv, og skifter
når personen skifter — uden at brugeren forlader Kaliv-appen.

## 2. Hvad der findes (main, 2/9)

| Lag | Status |
|---|---|
| `.mrbody`-format, profil-store, current-binding, digest-bound renderer-handoff | landet (M2.5–M2.8) |
| Runtime-tilstand (`BodyRigRuntime`), face-/motion-mixere, `render_frame` v0.1-wire | landet |
| Unity/VRM-renderer (blink, mund, visemer, emotion, gaze, breath, gesture-router) | landet (#830) |
| Person Profile-registry med atomisk aktivering; `active_bindings().body` | landet (#752) |
| **Live frame-feed fra Kalivs faktiske tur og tale** | **mangler** — Unity afspiller en fixture |
| **Aktiver over HTTP til telefonen** | **mangler** — handoff er fil-sti på riggen |
| **Unity som library i Kaliv Android** | **mangler** — projektet er en Windows-batch-build |
| **ARFoundation** | **mangler** |

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

**L2 — Unity-projektet bliver en klient.**
- `BodyRigNetworkSource`: henter avatar og motions over HTTP med token,
  abonnerer på frame-feedet; erstatter fixture-afspilleren i runtime.
- Eksport som **Unity as a Library** (Android: `unityLibrary`-Gradle-modul,
  IL2CPP, arm64). Windows-desktop senere ad samme vej.
- ARFoundation: kamera-passthrough, plane-detektion, kroppen placeret på gulvet,
  skaleret efter bodyprintens højde.

**L3 — Kaliv Android bærer den.**
- `Krop`-skærm (⋮ → Krop, `kaliv://body`) der hoster `UnityPlayer` i en
  fragment; token og rig-URL gives til Unity-siden ved start.
- `unityLibrary` inkluderes bag et Gradle-flag (`-PkalivUnity=true`), så CI
  uden Unity stadig bygger appen; uden library viser skærmen ærligt
  "renderer ikke bygget ind i dette build" frem for at crashe.

**L4 — bevis.** `bodyrig_unity_physical_proof.ps1` (findes) udvides med
Android-buildet; visuel accept på Pixel: kroppen står i rummet, blinker,
taler med Kaliv, skifter ved personskift.

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

1. L1: frame-feed + aktiver-endpoints i workeren, Go-forwarding, kontrakttests.
2. L2: `BodyRigNetworkSource` i Unity-projektet + UaaL-eksportindstillinger.
3. L3: `Krop`-skærm og Gradle-flag i Kaliv Android.
4. L4: Android-build i den fysiske proof; visuel accept.

## 8. Status 3/9 — afstemt med `UNITY_RENDERER_ROADMAP.md`

Denne plan og roadmappen (#832) blev skrevet parallelt af to sessioner 2/9
aften. De er enige om alt undtagen ét punkt, og det står nedenfor.

**L1 er landet på main, som beskrevet her:** `/api/v1/body/active` + assets
(#842), `/api/v1/body/frames` SSE fra `BodyRigRuntime` + `EmbodimentScheduler`
drevet af chat-faser og TTS-sætninger (#843), telefonens afspilningsrapporter
(#844), cues default fra (#848), cache mod re-validering pr. frame (#850),
ingen timeout på streamen (#851), klient-rapporterbare tilstande begrænset
til `listening`/`idle` (#852). `KALIV_BODY_STORE` i appliancens env.

**L2's netværkskilde er skrevet:** `BodyRigFrameSource` (#846, draft mod
#720-grenen) — samme `Apply` som fixturen, samme værn, genforbindelse;
bootstrappen vælger den kun med `BODYRIG_RIG_URL`/`_TOKEN` sat. Kompilerer kun
i Unity; verificeres af #720's fysiske gate. UaaL-eksportindstillingerne er
IKKE lavet.

**Det åbne valg — MVP-værten:** denne plan siger Unity as a Library inde i
Kaliv fra MVP; roadmappen siger separat "Kaliv Body"-app først og UaaL som
V2-spørgsmål (build-kompleksitet, APK +60–100 MB, én Gradle-integration mere
i en app der i dag bygges rent i CI). Begge veje bruger samme L1 og samme
Unity-kilde; kun L3 er forskellig. **Anders afgør**, når #720 er landet og
kroppen er set på Windows.

**Første krop og rig-dagen:** `docs/bodyrig/FIRST_LIVE_BODY.md` +
`scripts/bodyrig_demo_body.py` (#847).
