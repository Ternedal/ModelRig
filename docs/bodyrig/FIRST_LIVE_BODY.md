# Den første levende krop — rig-runbook

Alt her forudsætter dev-kanalen (`DEV_APPLIANCE.md`): riggen kører fra
HEAD, telefonen fra CI's APK. Slice A/B og Unity-proofen (#720) er på main;
#846 (live frame-kilde) er draft mod main og lander, når den er kompileret i
Unity. Den fysiske gate er ikke kørt endnu — det er dét, afsnit 2 gør.

## 1. Forberedelse (én gang)

1. **Unity Hub** → installér `6000.3.21f1` på standardstien. UniVRM
   `v0.131.2` trækkes af projektet selv.
2. **En VRM 1.0-avatar** — VRoid Studio → eksportér som VRM 1.0. Gem fx som
   `C:\Users\admin\Desktop\Kaliv.vrm`.
3. **Kroppen i storen — én kommando.** `PREPARE_FIRST_BODY.cmd` gør trin 3–5
   under ét: bygger, installerer og vælger kroppen, sætter `KALIV_BODY_STORE`
   hvis den mangler, og **verificerer mod riggen** (parrer en engangsenhed,
   læser `/body/active` og tre frames), så et 503 fanges her og ikke i Unity:

       PREPARE_FIRST_BODY.cmd C:\Users\admin\Desktop\Kaliv.vrm Kaliv

   Blev env ændret, siger scriptet det: genstart dev-appliancen og kør igen.
   Til sidst udskriver det de to `BODYRIG_RIG_*`-linjer til afsnit 3.
   Resten af dette afsnit er de samme trin manuelt:

       cd C:\Users\admin\Desktop\ModelRig-git
       python scripts\bodyrig_demo_body.py --vrm C:\Users\admin\Desktop\Kaliv.vrm --name Kaliv --store C:\Users\admin\Desktop\ModelRig-appliance\bodyrig-profiles

4. **Appliancens env** — tilføj i `ModelRig-appliance\modelrig.env`:

       KALIV_BODY_STORE=C:\Users\admin\Desktop\ModelRig-appliance\bodyrig-profiles

   og start dev-appliancen igen (`START_DEV_APPLIANCE.cmd`).

5. **Tjek at riggen serverer kroppen** (device-token fra parring; samme
   fremgangsmåde som task-ui-valideringen):

       $p = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/pair/start"
       $c = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/pair/claim" -ContentType 'application/json' -Body (@{ device_name = "unity-$(Get-Random)"; code = $p.code } | ConvertTo-Json -Compress)
       $h = @{ Authorization = "Bearer $($c.token)" }
       Invoke-RestMethod -Headers $h "http://127.0.0.1:8080/api/v1/body/active"
       Invoke-RestMethod -Headers $h "http://127.0.0.1:8080/api/v1/body/frames?limit=3"

   Manifest med `name: Kaliv` og tre `data:`-linjer med `state: idle` = klar.

## 2. Den fysiske Unity-gate (mod main)

Fra `main`, ren working tree, telefon ikke nødvendig:

    git switch main; git pull --ff-only
    powershell -ExecutionPolicy Bypass -File .\scripts\bodyrig_unity_physical_proof.ps1 -Store C:\Users\admin\Desktop\ModelRig-appliance\bodyrig-profiles
    powershell -ExecutionPolicy Bypass -File .\scripts\bodyrig_unity_visual_acceptance.ps1 -StatesDistinct -GazeBlinkBreathVisible -ExplainGestureVisible -SpeechModesDiffer -InterruptionImmediateNeutral
    python scripts\bodyrig_unity_physical_gate.py --expected-sha (git rev-parse HEAD)

Grøn gate = rendereren på main er fysisk bevist. Derefter #846 (kræver at
den kompilerer i Unity — første import viser det).

## 3. Kroppen følger samtalen (#846)

Samme Unity-projekt fra #846-grenen (`git switch feat/unity-frame-source`),
nu med riggen navngivet — ingen fixture:

    $env:BODYRIG_VRM_PATH = "C:\Users\admin\Desktop\Kaliv.vrm"
    $env:BODYRIG_RIG_URL = "http://127.0.0.1:8080"
    $env:BODYRIG_RIG_TOKEN = $c.token
    & "C:\Program Files\Unity\Hub\Editor\6000.3.21f1\Editor\Unity.exe" -projectPath .\renderers\bodyrig-unity

Send en besked i Kaliv-appen: kroppen går i *thinking*, kører et tool →
*waiting_for_tool*, taler når telefonen afspiller sætningen (munden følger
lyden), står stille ved stop. `voice_bound` og `person` i svaret er
uafhængige af kroppen; den følger den valgte persons body-revision (#752),
hvis den navngiver en installeret bodyid, ellers current.

## 4. Kalivs stemme (VoiceRig → person)

Stemmen bygges i VoiceRigs UI (vælg 1–10 klip → navn → byg → installér), som
lægger en `.mrvoice` i VoiceRigs voices-mappe. Bind den til personen som en
**ny** reviewet revision — den aktive rettes aldrig:

    python scripts\person_bind.py --person person-5bc3e41093e058885fdd1e51a9fcef54 --voice kaliv.mrvoice --reviewed --reviewer Anders

Fra næste sætning sender workeren `voice_package=kaliv.mrvoice` til VoiceRig
og verificerer `X-VoiceRig-Package`; svaret bærer `voice_bound: true`.

## 5. Den rigtige krop (video → `.mrbody` → person)

Demo-kroppen fra afsnit 1 har en fixture-identitet. Den rigtige kommer fra
en video af personen, med MediaPipe-modellerne (`.task`-filer, absolutte
stier) og en samtykke-erklæring, som pipelinen kræver:

    python scripts\bodyrig_extract_video.py --source C:\path\kaliv.mov --pose-model C:\models\pose_landmarker.task --hand-model C:\models\hand_landmarker.task --face-model C:\models\face_landmarker.task --permission-assertion "Jeg har tilladelse til at behandle denne optagelse" --output C:\work\kaliv-tracking.json
    python scripts\bodyrig_build_identity_bundle.py C:\work\kaliv-tracking.json C:\work\kaliv-identity.json
    python scripts\bodyrig_build_mrbody.py C:\work\kaliv-identity.json C:\Users\admin\Desktop\Kaliv.vrm C:\work\thumb.png C:\work\kaliv.mrbody --name Kaliv
    python scripts\bodyrig_install_mrbody.py C:\work\kaliv.mrbody C:\Users\admin\Desktop\ModelRig-appliance\bodyrig-profiles
    python scripts\bodyrig_select_current_mrbody.py C:\Users\admin\Desktop\ModelRig-appliance\bodyrig-profiles <bodyid fra install-output>

Og bind den til personen (bodyid'et fra install-outputtet), gerne sammen
med stemmen i samme revision:

    python scripts\person_bind.py --person person-5bc3e41093e058885fdd1e51a9fcef54 --body bodyid-<hex> --voice kaliv.mrvoice --reviewed --reviewer Anders

`/body/active` svarer derefter med `source: person`, og rendereren viser
hendes krop, ikke demo-identitetens. MediaPipe-kravene står i
`bodyrig/requirements-tracking.txt` (`mediapipe==1.0.1`).

## Hvad der ikke virker endnu, og hvorfor

- **Emotion og gestik** er `neutral`/ingen som standard. Sæt
  `KALIV_BODY_CUES=1` i appliancens env for den lille, eksplicitte politik:
  lange sætninger får `explain`-gestik under tale, thinking er `curious`
  (lavt), fejl er `concerned`; idle/listening/interrupted nulstiller. Intet
  udledes af ordene selv — ingen sentiment-gætteri. Se `worker/app/body_cues.py`.
- **Telefon/Quest**: Unity-projektet bygger endnu ikke til Android; slice D.
- **Demo-identiteten** er en fixture. Den rigtige krop: afsnit 5.
