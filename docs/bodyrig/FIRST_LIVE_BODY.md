# Den første levende krop — rig-runbook

Alt her forudsætter dev-kanalen (`DEV_APPLIANCE.md`): riggen kører fra
HEAD, telefonen fra CI's APK. Slice A/B er på main; #720 (Unity-proof) og
#846 (live frame-kilde) er drafts, der lander via den fysiske gate.

## 1. Forberedelse (én gang)

1. **Unity Hub** → installér `6000.3.21f1` på standardstien. UniVRM
   `v0.131.2` trækkes af projektet selv.
2. **En VRM 1.0-avatar** — VRoid Studio → eksportér som VRM 1.0. Gem fx som
   `C:\Users\admin\Desktop\Kaliv.vrm`.
3. **Kroppen i storen**, fra kun VRM'en (demo-identitet — ikke en person):

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

## 2. Den fysiske Unity-gate (#720)

Fra `agent/bodyrig-unity-renderer`, ren working tree, telefon ikke nødvendig:

    git switch agent/bodyrig-unity-renderer; git pull --ff-only
    powershell -ExecutionPolicy Bypass -File .\scripts\bodyrig_unity_physical_proof.ps1 -Store C:\Users\admin\Desktop\ModelRig-appliance\bodyrig-profiles
    powershell -ExecutionPolicy Bypass -File .\scripts\bodyrig_unity_visual_acceptance.ps1 -StatesDistinct -GazeBlinkBreathVisible -ExplainGestureVisible -SpeechModesDiffer -InterruptionImmediateNeutral
    python scripts\bodyrig_unity_physical_gate.py --expected-sha (git rev-parse HEAD)

Grøn gate → #720 ud af draft og ind på main. Så merges #846 ind.

## 3. Kroppen følger samtalen (#846)

Samme Unity-projekt, nu med riggen navngivet — ingen fixture:

    $env:BODYRIG_VRM_PATH = "C:\Users\admin\Desktop\Kaliv.vrm"
    $env:BODYRIG_RIG_URL = "http://127.0.0.1:8080"
    $env:BODYRIG_RIG_TOKEN = $c.token
    & "C:\Program Files\Unity\Hub\Editor\6000.3.21f1\Editor\Unity.exe" -projectPath .\renderers\bodyrig-unity

Send en besked i Kaliv-appen: kroppen går i *thinking*, kører et tool →
*waiting_for_tool*, taler når telefonen afspiller sætningen (munden følger
lyden), står stille ved stop. `voice_bound` og `person` i svaret er
uafhængige af kroppen; den følger den valgte persons body-revision (#752),
hvis den navngiver en installeret bodyid, ellers current.

## Hvad der ikke virker endnu, og hvorfor

- **Emotion og gestik** er `neutral`/ingen: ingen cue-slice endnu. Rendereren
  forstår `explain` under tale og `happy/amused/curious/surprised/sad/…`.
- **Telefon/Quest**: Unity-projektet bygger endnu ikke til Android; slice D.
- **Demo-identiteten** er en fixture. Den rigtige krop kommer fra
  `bodyrig_extract_video.py` → `bodyrig_build_identity_bundle.py` →
  `bodyrig_build_mrbody.py`.
