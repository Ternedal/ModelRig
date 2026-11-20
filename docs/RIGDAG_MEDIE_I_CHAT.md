# RIGDAG — billeder og video i chatten (#2419)

Én køreplan for rig-testen af medie-sporet: `image_generate` / `video_generate`
i chat-turen, boblerne i Android og desktop, og billede-til-video. Trin for trin
og i den rækkefølge, der afslører mest tidligst. Udskiftede værdier står som `<…>`.

> **Status:** samlet 20/11-2026. **Intet her er kørt på riggen.** Koden ligger
> som drafts (#2448, #2449, #2457–#2461) og er samlet i grenen
> `integration/media-chat` (#2462, må ikke merges), hvor CI kører på helheden.
> Udviklingskanalen er **ikke evidens**: ingen gate læser noget herfra.

Hver kommandoblok er mærket med, hvad den hviler på:

- **[kørt 17/11]** — blokken virkede på riggen den dag (billed-rigaftenen), kun stien er ny;
- **[repo]** — udledt af koden, ikke kørt på riggen;
- **[antagelse]** — noget om riggen eller telefonen, som første kommando skal bekræfte.

## Rækkefølgen og hvorfor

1. **Trin 1, worker alene.** Én tur fra terminalen viser, om modellen kalder
   værktøjet, og om jobbet bliver til et billede. Fejler det, er telefon og
   desktop ligegyldige.
2. **Trin 2, Android** og **trin 3, desktop** — samme rig, samme job-API.
3. **Trin 4, video** og **trin 5, billede-til-video** kræver ComfyUI, vægte og
   templates på riggen. Det er et selvstændigt forløb
   ([MEDIA_VIDEO_RIG_QUALIFICATION.md](MEDIA_VIDEO_RIG_QUALIFICATION.md) §5 og §6)
   og kan ikke klares på samme aften som trin 1–3.

**Hvornår:** ikke mens en V1-gate eller soaken kører — dev-appliancen bruger
samme porte (8080/8099). Kandidat-checkoutet til V1 røres ikke: testen kører fra
sit eget worktree.

## Kendte risici, før du starter

1. **VRAM: chatmodel og billedmodel samtidig.** Den 17/11 blev billeder lavet fra
   Medier-skærmen, uden en stor chatmodel indlæst. Nu ligger `qwen3:14b` i Ollama,
   mens SDXL renderer (målt peak 11,0 GB på `cuda:1`). Lægger Ollama en del af
   modellen på GPU 1, udskyder executoren jobbet, til der er plads — i værste fald
   til Ollama har sluppet modellen (5 min som standard) eller `gpu_unavailable` efter 10 min.
   **Mål det i trin 0.4, før noget andet.** Hvad der gøres ved det, er din afgørelse.
2. **Kalder modellen værktøjet?** Om `qwen3:14b` pålideligt vælger
   `image_generate` på en dansk bøn, er en egenskab ved modellen og systemreglen,
   ikke noget der kan rettes på riggen. Mål raten; justér ikke undervejs.
3. **APK oven på den installerede app.** Debug og release har samme
   signeringskonfiguration i Gradle [repo], men om CI's nøgle er den samme som
   din installerede apps, er ikke bekræftet. **Nægter Android opdateringen: stop,
   afinstallér ikke** (det sletter dine samtaler), og skriv fejlen på #2419.
   Den anden vej er sikret i koden: samtaledatabasen bliver på skemaversion 3, så
   2.0.21-appen kan åbne den igen bagefter (testet i Robolectric, ikke på telefon).

## 0. Før alt

Nyt, **ikke-elevated** PowerShell 7-vindue.

**0.1 Worktree på integrationsgrenen** [repo]

```powershell
$Main = "C:\Users\an001\Desktop\ModelRig-git"; $Repo = "C:\Users\an001\Desktop\ModelRig-media"
git -C $Main fetch origin
git -C $Main worktree add $Repo origin/integration/media-chat
git -C $Repo log --oneline -1
```

Findes worktree'et allerede: `git -C $Repo fetch origin; git -C $Repo checkout --detach origin/integration/media-chat`.

**0.2 Hvad står der i env-filen?** [antagelse: `KALIV_MEDIA_JOBS_API=1` og de to billedprofiler står der fra 17/11]

```powershell
Select-String -Path C:\Rig\ModelRig\modelrig.env -Pattern '^KALIV_(TOOLS_ENABLED|MEDIA_JOBS_API|MEDIA_PROFILES_ENABLED|IMAGE_TOOL|VIDEO_TOOL|MEDIA_VIDEO)' | ForEach-Object Line
```

**0.3 Tilføj det, der mangler** [repo] — tilføjer kun, omskriver aldrig filen:

```powershell
$EnvFile = "C:\Rig\ModelRig\modelrig.env"
Copy-Item $EnvFile "$EnvFile.bak-$(Get-Date -Format yyyyMMdd-HHmm)"
function Add-EnvLine($k, $v) { if (Select-String -Path $EnvFile -Pattern "^$k=" -Quiet) { "findes: " + (Select-String -Path $EnvFile -Pattern "^$k=").Line } else { Add-Content $EnvFile "$k=$v" -Encoding ascii; "tilføjet: $k=$v" } }
Add-EnvLine KALIV_TOOLS_ENABLED 1
Add-EnvLine KALIV_MEDIA_JOBS_API 1
Add-EnvLine KALIV_IMAGE_TOOL_ENABLED 1
Add-EnvLine KALIV_IMAGE_TOOL_PROFILE realvisxl-4-0
```

`KALIV_IMAGE_TOOL_PROFILE` er nødvendig, fordi riggen har to billedprofiler slået
til: uden den svarer værktøjet `profile_required` [repo].

**0.4 Hvor lægger Ollama chatmodellen?** [antagelse: den bliver på GPU 0]

```powershell
ollama run qwen3:14b "hej" | Out-Null; nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader
```

Forventet: GPU 1 under ca. 1,5 GB. **Står der flere GB på GPU 1, er modellen
delt over begge kort** — notér tallene; trin 1 viser så, hvad det koster i ventetid.

## 1. Billede i chatten — worker alene

**1.1 Vindue A: dev-appliancen** [kørt 17/11] (beder selv om administrator)

```powershell
& "C:\Users\an001\Desktop\ModelRig-media\START_DEV_APPLIANCE.cmd" -ApplianceDir C:\Rig\ModelRig -SkipVisionRig
```

Vent på "Dev-appliancen koerer".

**1.2 Vindue B: executoren** [kørt 17/11] — samme ikke-elevated vindue som 0.1

```powershell
$GenPy = "C:\Kaliv\media-venv\Scripts\python.exe"; $Repo = "C:\Users\an001\Desktop\ModelRig-media"; $EnvFile = "C:\Rig\ModelRig\modelrig.env"
Get-Content $EnvFile | Where-Object { $_ -match '^(KALIV_MEDIA|KALIV_GPU|CUDA_)' } | ForEach-Object { $k,$v = (($_ -split '#')[0]) -split '=',2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process') }
$env:KALIV_MEDIA_EXECUTOR = "1"; $env:HF_HUB_OFFLINE = "1"; $env:TRANSFORMERS_OFFLINE = "1"
Push-Location "$Repo\worker"; & $GenPy -u -m app.media_executor_main --device cuda:1; "exit=$LASTEXITCODE"; Pop-Location
```

Exit 73 = en gammel executor lever stadig; 78 = konfiguration (teksten siger hvad); 75 = mediavolumen.

**1.3 Vindue C: token og værktøjsliste** [repo; `pair/start` på loopback virkede 17/11]

```powershell
$B = "http://127.0.0.1:8080"
$code = (Invoke-RestMethod "$B/api/v1/pair/start" -Method Post -ContentType 'application/json' -Body '{}').code
$env:MODELRIG_TOKEN = (Invoke-RestMethod "$B/api/v1/pair/claim" -Method Post -ContentType 'application/json' -Body (@{ device_name = 'rig-terminal'; code = $code } | ConvertTo-Json)).token
$H = @{ Authorization = "Bearer $env:MODELRIG_TOKEN" }
(Invoke-RestMethod "$B/api/v1/tools" -Headers $H).tools | Where-Object name -like '*_generate' | Select-Object name, enabled
```

Forventet: `image_generate  True`. Mangler den: workeren har ikke set
`KALIV_IMAGE_TOOL_ENABLED=1` — tjek 0.2 og genstart vindue A.

**1.4 Én tur, og følg jobbet** [repo]

```powershell
$body = @{ message = 'lav et billede af en rød cykel ved en sø'; model = 'qwen3:14b' } | ConvertTo-Json
$t0 = Get-Date
$r = Invoke-RestMethod "$B/api/v1/tools/chat" -Method Post -Headers $H -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
"tur: {0:n1} s  status={1}  tools={2}" -f ((Get-Date) - $t0).TotalSeconds, $r.status, ($r.tools_used -join ',')
$r.answer; $r.media_jobs | Format-List
```

```powershell
$id = $r.media_jobs[0].job_id
do { Start-Sleep 2; $j = Invoke-RestMethod "$B/api/v1/media/jobs/$id" -Headers $H; "{0:HH:mm:ss} {1} {2}" -f (Get-Date), $j.state, $j.error } until ($j.state -in 'completed','failed','cancelled','expired')
"i alt: {0:n1} s" -f ((Get-Date) - $t0).TotalSeconds; $j | Format-List
```

Bestået, når: `tools` er `image_generate`, `media_jobs` har ét job, jobbet ender
`completed` med et `asset_id`, og svaret siger, at billedet er på vej — ikke at
det er færdigt. Billedet ligger i `D:\kaliv-media\gallery`.

- **`media_jobs` tom, `tools` tom:** modellen kaldte ikke værktøjet. Prøv
  sætningen to gange mere, notér 0–3 af 3, og **stop her**, hvis det er 0.
- **Jobbet står i `queued` i minutter:** se vindue B for udskydelser (VRAM, risiko 1).

**1.5 Kontrol: slukket værktøj** [repo] — valgfri. Sæt `KALIV_IMAGE_TOOL_ENABLED=0`
i env-filen, genstart vindue A, gentag 1.3: `image_generate` må ikke stå på
listen, og 1.4 skal give et rent tekstsvar. Sæt den tilbage til 1 bagefter.

## 2. Android

**2.1 APK fra CI** [repo; samme vej som 19/8 og 20/8]

```powershell
gh workflow run candidate-apk.yml -R Ternedal/ModelRig -f ref=integration/media-chat
```

Når kørslen er grøn:

```powershell
$run = gh run list -R Ternedal/ModelRig --workflow candidate-apk.yml -L 1 --json databaseId,conclusion,headSha | ConvertFrom-Json; $run
gh run download $run[0].databaseId -R Ternedal/ModelRig -D "$env:TEMP\kaliv-apk"
$apk = Get-ChildItem "$env:TEMP\kaliv-apk" -Recurse -Filter app-debug.apk | Select-Object -First 1; $apk.FullName
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object PrefixOrigin -eq Dhcp).IPAddress
python -m http.server 8000 --directory $apk.DirectoryName
```

Telefon, Chrome: `http://<rig-ip>:8000/app-debug.apk` → installér (se risiko 3).
Par mod dev-appliancen som 17/11 (parringen fra release-appliancen gælder ikke).

**2.2 Fem beskeder, værktøjer slået til, model `qwen3:14b`**

| # | Besked | Værktøj kaldt? | s til boble | s til billede | OK? |
|---|---|---|---|---|---|
| 1 | lav et billede af en rød cykel ved en sø | | | | |
| 2 | tegn en kat der sover i en vindueskarm | | | | |
| 3 | kan du lave et fotorealistisk billede af et fyrtårn i tåge? | | | | |
| 4 | generér et billede af et gammelt bibliotek | | | | |
| 5 | hvad er hovedstaden i Frankrig? *(kontrol: ingen boble)* | | | | |

Forventet: boblen går "I kø på riggen" → "Genererer …" → "Gemmer billedet …" →
billede; 20–30 s pr. billede, hvis kortet er ledigt (17/11-tal fra Medier-skærmen).

**2.3 Boblen og viseren** — sæt ✔/✘:

- [ ] Tryk på billedet åbner det i fuld skærm; knib zoomer, træk panorerer, dobbelttryk skifter.
- [ ] **Gem** → billedet ligger i telefonens galleri under `Kaliv`.
- [ ] **Del** → Androids delingsark åbner med billedet.
- [ ] Luk appen helt, åbn samtalen igen → billedet kommer tilbage af sig selv.
- [ ] Wi-Fi fra i 30 s under "Genererer …", til igen → boblen ender alligevel med billedet.
- [ ] Stop executoren (Ctrl+C i vindue B), bed om et billede → boblen bliver på "I kø på riggen"; start executoren igen → billedet kommer.

## 3. Desktop

[antagelse: JDK 21 findes, hvor du kører den — riggen eller en anden PC på LAN'et]

```powershell
java -version
cd "C:\Users\an001\Desktop\ModelRig-media\desktop"; .\gradlew.bat run
```

Indstillinger: lokal URL `http://127.0.0.1:8080` (eller `http://<rig-ip>:8080`),
sti `/api/v1/chat`, par for at få et enhedstoken, **Tools: Til**.

- [ ] Samme besked 1 → statuslinje under svaret, derefter billedet.
- [ ] Klik på billedet → eget vindue; musehjul zoomer, træk panorerer, "Tilpas" nulstiller.
- [ ] "Gem som …" → filen findes og åbner i en billedviser.
- [ ] Luk appen, åbn samtalen igen → billedet kommer tilbage.
- [ ] Besked 5 (kontrol) → ingen boble.

Desktop-UI'et har ingen automatisk test. Det, du ser her, er første gang, det kører.

## 4. Video (tekst til video) — kræver kvalificeringen først

Forudsætning: [MEDIA_VIDEO_RIG_QUALIFICATION.md](MEDIA_VIDEO_RIG_QUALIFICATION.md)
§5 trin 1–8 er gennemført (ComfyUI, vægte, template, profil pr. GPU,
`KALIV_COMFY_*`, `KALIV_MEDIA_VIDEO=1`). Derefter:

```powershell
$EnvFile = "C:\Rig\ModelRig\modelrig.env"; if (-not (Select-String -Path $EnvFile -Pattern '^KALIV_VIDEO_TOOL_ENABLED=' -Quiet)) { Add-Content $EnvFile 'KALIV_VIDEO_TOOL_ENABLED=1' -Encoding ascii }
```

Genstart vindue A og executoren. 1.3 skal nu også vise `video_generate  True`.

- [ ] Terminal som 1.4 med `lav en video af en papirbåd der driver over en dam` → `tools=video_generate`, ét job med `kind=video`, ender `completed`. Notér tiden.
- [ ] Android: boblen viser status og derefter en afspiller; klippet spiller i boblen.
- [ ] Android: "Fuld skærm" → viser; **Gem** → klippet ligger under `Film/Kaliv`; **Del** → delingsark.
- [ ] Desktop: "Klippet er færdigt" → "Gem klip …" → "Åbn" starter systemets afspiller.

## 5. Billede til video — kræver §6 i kvalificeringen

Forudsætning: en billede-til-video-profil med sin egen template og port
(kvalificeringens §6). Ingen ny kontakt: `video_generate` vælger profilen efter opgaven.

- [ ] **Før** der findes et færdigt billede i dag: `lav en video af det billede` → svaret siger, at der ikke er noget færdigt billede. Intet job.
- [ ] Lav et billede (besked 1), vent til det er færdigt, og skriv så `lav en video af det billede` som næste besked → videoboble; klippet **starter fra det billede**.
- [ ] Gentag tre gange med nye billeder. Notér, hvor mange gange modellen sendte kilden med (ellers bliver det en ren tekst-video, der ikke ligner billedet).

## Hvad der skal med hjem

Skriv det som én kommentar på #2419:

1. Tallene fra 0.4 (GPU 0 / GPU 1 med chatmodellen indlæst).
2. 1.4: turens sekunder, jobbets sekunder, og om executoren udskød jobbet.
3. Tabellen fra 2.2 og afkrydsningerne fra 2.3 og 3.
4. Alt, der så forkert ud, med skærmbillede — også småting i boblerne.
5. For trin 4–5: tider, VRAM-peak og de tre billede-til-video-forsøg.

## Stopregler

- Værktøjet kaldes 0 af 3 gange i 1.4 → stop; resten måler ikke noget.
- Android nægter at installere APK'en → stop, afinstallér ikke.
- Et job fejler `gpu_unavailable` to gange i træk → stop; det er risiko 1, og løsningen er en afgørelse, ikke et forsøg mere.
- Appen eller desktop-klienten går ned → notér hvad du gjorde, og gå videre til næste trin.

## Bagefter

```powershell
& "C:\Users\an001\Desktop\ModelRig-media\START_DEV_APPLIANCE.cmd" -Stop
```

- Executoren: Ctrl+C i vindue B.
- Env-filen: de tilføjede linjer gør ingenting for 2.0.21, men tænder værktøjet
  den dag koden er landet. Vil du ikke det: `Copy-Item <backup fra 0.3> C:\Rig\ModelRig\modelrig.env`.
- Worktree: `git -C C:\Users\an001\Desktop\ModelRig-git worktree remove C:\Users\an001\Desktop\ModelRig-media`.
- Telefonen: skal V1-kandidatens app tilbage, så installér den oven på igen (samme vej som 2.1).
