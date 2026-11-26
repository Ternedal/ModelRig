# RIGDAG — billeder og video i chatten (#2419)

Én køreplan for rig-testen af medie-sporet: `image_generate` / `video_generate`
i chat-turen, boblerne i Android og desktop, og billede-til-video. Trin for trin
og i den rækkefølge, der afslører mest tidligst. Udskiftede værdier står som `<…>`.

> **Status:** samlet 20/11-2026, landet på `main` 22/11-2026 gennem #2462
> (merge-commit `30b95e6a494c0606ccc276cb76b3d56189b67b95`). Køreplanen køres
> derfor fra `main`; grenen `integration/media-chat` er afløst. Hvad der faktisk
> er kørt på riggen 21/11, står i `docs/MEDIA_VIDEO_RIG_QUALIFICATION.md` §7.
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
4. **Trin 6, video med lyd** (LTX-2.3) bygger oven på trin 4–5 og har sine egne
   vægte (41 GB) og sit eget RAM-loft.
5. **Trin 7, acceptforløbet**, er det eneste, der må kaldes fysisk accept: succes,
   fejl og genstart på én kandidat-SHA, på telefon og desktop.

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
   **Målt 20/11 (integration @ `076b9addf4`, dev-kanal):** `qwen3:14b` indlæses med
   context 40960 som 17 GB delt over begge kort (GPU 0 9,8 GB, GPU 1 8,1 GB). Job blev
   *ikke* udskudt: GPU 1 stod på 11,8–11,9 af 12,3 GB før og under hvert job, job
   startede med det samme og tog 15–20 s (17/11 alene på kortet: ca. 21 s varm).
   Prisen faldt på chatten: en tur med værktøj tog 13–16 s uden resident billedmodel
   og 37–59 s med (kontrol uden værktøj: 5–6 s). Hvorfor executoren lod jobbet starte
   med ca. 4 GB ledigt, er ikke forklaret — gem dens output (1.2), så det kan læses.
   **Forklaret 21/11:** `gpu_budget:admitted,cuda1,free_mib=11255,…total_mib=12287`,
   mens `nvidia-smi` viste 8149 MiB brugt på samme kort. Adgangsproben
   (`torch.cuda.mem_get_info`) ser ikke Ollamas forbrug under Windows' WDDM-model, så
   "chat først"-reglen er reelt ude af kraft på riggen. Jobbene tog i virkeligheden
   49–66 s (executorens egen tid); de 15–20 s ovenfor var probens ventetid efter turen.
   Mulighederne står i 1.7. Med #2470 (i integrationsgrenen) skriver executoren, hvad
   adgangsproben målte: efter første job, læs
   `Select-String 'gpu_budget|vram_short' "$env:TEMP\media-executor.log"`. Linjen har
   både probens `free_mib` og NVML's `nvml_used_mib` fra samme øjeblik (mangler feltet, så brug probens `vram_before_mib` for første job). Giver de
   to ikke tilsammen cirka `total_mib`, ser proben ikke Ollamas forbrug, og det er
   forklaringen.
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

**0.1 Worktree på `main`** [repo]

```powershell
$Main = "C:\Users\an001\Desktop\ModelRig-git"; $Repo = "C:\Users\an001\Desktop\ModelRig-media"
git -C $Main fetch origin
git -C $Main worktree add --detach $Repo origin/main
git -C $Repo log --oneline -1
```

Findes worktree'et allerede: `git -C $Repo fetch origin; git -C $Repo checkout --detach origin/main`.

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

Vent på "Dev-appliancen koerer". Starter workeren ikke: kopiér fejlen og stop —
installér ikke pakker om i riggens Python, før V1 er færdig (kandidaten bruger samme installation).

**1.2 Vindue B: executoren** [kørt 17/11] — samme ikke-elevated vindue som 0.1

```powershell
$GenPy = "C:\Kaliv\media-venv\Scripts\python.exe"; $Repo = "C:\Users\an001\Desktop\ModelRig-media"; $EnvFile = "C:\Rig\ModelRig\modelrig.env"
Get-Content $EnvFile | Where-Object { $_ -match '^(KALIV_MEDIA|KALIV_GPU|KALIV_COMFY|CUDA_)' } | ForEach-Object { $k,$v = (($_ -split '#')[0]) -split '=',2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process') }
$env:KALIV_MEDIA_EXECUTOR = "1"; $env:HF_HUB_OFFLINE = "1"; $env:TRANSFORMERS_OFFLINE = "1"
Push-Location "$Repo\worker"; & $GenPy -u -m app.media_executor_main --device cuda:1 2>&1 | Tee-Object "$env:TEMP\media-executor.log"; "exit=$LASTEXITCODE"; Pop-Location
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
$r.answer; $r.media_jobs | Format-List; $r.media_refusals | Format-Table
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

**1.5 Mål det i stedet for at tage tid i hånden** [repo] — samme vindue C (tokenet står i miljøet):

```powershell
cd C:\Users\an001\Desktop\ModelRig-media
python scripts\media_chat_probe.py --suite image --rounds 2 --report "$env:TEMP\media-chat-image.json"
```

Proben sender planens fire billedbeskeder to gange plus kontrolbeskeden gennem
`/api/v1/tools/chat`, følger hvert job til det er færdigt, og skriver én tabel:
blev værktøjet kaldt, sekunder for turen, sekunder for jobbet. Med `nvidia-smi`
på maskinen noterer den også VRAM pr. kort før hvert job og toppen under det —
det er risiko 1 i tal. Den laver otte rigtige billeder (regn med 8–12 minutter)
og taler kun med loopback. Rapporten indeholder hverken token eller modellens tekst.
Exit 0 = alt som forventet, 1 = mindst ét tilfælde afveg.

**1.5b Samme beskeder som én samtale** [repo] — det er sådan, telefonen sender dem:

```powershell
python scripts\media_chat_probe.py --suite conversation --stream --rounds 2 --report "$env:TEMP\media-chat-conversation.json"
```

`--stream` sender turen gennem `/tools/chat/stream`, som telefonen og desktop-appen gør
[repo: `ModelRigClient.toolsChatStream`]. Har du en systemprompt på telefonen
(Indstillinger → rig), så gem den i en tekstfil og tilføj `--system-file <fil>`:
appen sender den med hver tur, og proben uden den er ikke den samme samtale.
Rapporten gemmer kun promptens længde.

De fire billedbeskeder og kontrollen sendes med historikken fra de foregående ture.
20/11 gik 19 af 19 igennem uden historik, mens telefonen fik "der er tekniske problemer
med billedgenerering" midt i en samtale. Afviser riggen et kald, står koden nu i
tabellen (`afvist:<kode>`), i turens `media_refusals` (1.4) og som én linje i
konsolvinduet **Kaliv DEV worker**: `media_tool=refused modality=… code=…`.
Dev-appliancen skriver ingen logfil [repo: `scripts/start-dev-appliance.ps1` starter
workeren i et `cmd /k`-vindue], så kopiér linjen derfra, hvis den skal med hjem.

| Kode | Betyder |
|---|---|
| `invalid_arguments` | modellen sendte et felt, værktøjet ikke har, eller et tal som tekst |
| `invalid_request` | en størrelse, profilen ikke tillader |
| `profile_not_enabled` | et `profile_id`, riggen ikke kender |
| `owner_limit` / `queue_full` | tre job er allerede i gang / køen er fuld |

**1.6 Kontrol: slukket værktøj** [repo] — valgfri. Sæt `KALIV_IMAGE_TOOL_ENABLED=0`
i env-filen, genstart vindue A, gentag 1.3: `image_generate` må ikke stå på
listen, og 1.4 skal give et rent tekstsvar. Sæt den tilbage til 1 bagefter.

**1.7 Chat og billeder på hvert sit kort** — **din afgørelse**: det ændrer riggens
Ollama-opsætning, ikke repoet, og dermed hvad V1-kandidaten kører på.

**Målt 21/11** (integration @ `dc31b9a8`, `--suite conversation --stream`, Ollama 0.40.16):

| | Delt (riggens opsætning) | Adskilt |
|---|---|---|
| `qwen3:14b` | 17 GB over begge kort, context 40960 | 10 GB på GPU 0, context 8192, 100 % GPU |
| GPU 1 før første job | 8149 MiB | 128 MiB |
| Tur med værktøj (median) | 42,3 s | 11,1 s |
| Besked → færdigt billede, ca. | 60 s | 30 s |

Tre ting, målingen viste, og som en tidligere udgave af dette trin havde forkert:

- Riggen har `OLLAMA_SCHED_SPREAD=true`: det er derfor, modellen ligger over begge kort.
- `CUDA_VISIBLE_DEVICES` alene er ikke nok. Med `OLLAMA_VULKAN=true` ser Ollama stadig
  det andet kort via Vulkan.
- Context 16384 kan ikke være på GPU 0 alene (13 % CPU; skærmen bruger ca. 1,4 GB).
  8192 kan.

Variablerne sættes **kun for ét Ollama-vindue**, aldrig på brugerniveau:
`CUDA_VISIBLE_DEVICES` på brugerniveau ville også ramme executoren, som skal bruge GPU 1.

```powershell
Get-Process ollama* -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 3
$env:CUDA_VISIBLE_DEVICES = ((nvidia-smi --query-gpu=index,uuid --format=csv,noheader | Where-Object { $_ -match '^0,' }) -replace '^0,\s*','').Trim()
$env:OLLAMA_SCHED_SPREAD = "false"; $env:OLLAMA_VULKAN = "false"; $env:OLLAMA_CONTEXT_LENGTH = "8192"; ollama serve
```

Bestået opstart: kun ét `inference compute` (CUDA0) og `total_vram="12.0 GiB"` i
loggen. Derefter `ollama ps` (skal vise `100% GPU`) og proben som i 1.5b. Tilbage til
før: Ctrl+C, luk vinduet, start Ollama fra Start-menuen.

Prisen er en femtedel af konteksten (lange samtaler, dokumenttunge RAG-ture), og at
modeller, der kræver begge kort, ikke kan indlæses, mens Ollama er bundet til ét. Det
er en produktafgørelse, ikke en teknisk detalje.

## 2. Android

**2.1 APK fra CI** [repo; samme vej som 19/8 og 20/8]

```powershell
gh workflow run candidate-apk.yml -R Ternedal/ModelRig --ref main
Start-Sleep 10; gh run watch (gh run list -R Ternedal/ModelRig --workflow candidate-apk.yml -L 1 --json databaseId --jq '.[0].databaseId') -R Ternedal/ModelRig --exit-status
```

`--ref main` bygger `main`s hoved. Bygget tager ca. 4 minutter.

Blokken henter kun en APK, der er bygget fra `main`s nuværende hoved og er
afsluttet grønt; ellers stopper den med en fejl og henter ingenting (20/11 gav
`-L 1` en kørsel fra 14/11, fordi den nye ikke var startet endnu — derfor vælges
kørslen på SHA, ikke på rækkefølge):

```powershell
& {
    $main = (git ls-remote https://github.com/Ternedal/ModelRig refs/heads/main) -split '\s+' | Select-Object -First 1
    if ($main -notmatch '^[0-9a-f]{40}$') { throw "kunne ikke aflaese main's hoved" }
    $runs = gh run list -R Ternedal/ModelRig --workflow candidate-apk.yml -L 20 --json databaseId,status,conclusion,headSha | ConvertFrom-Json
    $run = $runs | Where-Object { $_.headSha -eq $main -and $_.status -eq 'completed' -and $_.conclusion -eq 'success' } | Select-Object -First 1
    if (-not $run) {
        $runs | Select-Object -First 5 | Format-Table databaseId, status, conclusion, headSha | Out-Host
        throw "ingen afsluttet, groen candidate-apk-koersel for main $main - APK'en hentes ikke"
    }
    "APK fra koersel $($run.databaseId), bygget fra $($run.headSha)"
    Remove-Item "$env:TEMP\kaliv-apk" -Recurse -Force -ErrorAction SilentlyContinue
    gh run download $run.databaseId -R Ternedal/ModelRig -D "$env:TEMP\kaliv-apk"
    if ($LASTEXITCODE -ne 0) { throw "download fejlede" }
    $apk = Get-ChildItem "$env:TEMP\kaliv-apk" -Recurse -Filter app-debug.apk | Select-Object -First 1
    if (-not $apk) { throw "ingen app-debug.apk i det hentede artefakt" }
    $apk.FullName
    (Get-NetIPAddress -AddressFamily IPv4 | Where-Object PrefixOrigin -eq Dhcp).IPAddress
    python -m http.server 8000 --directory $apk.DirectoryName
}
```

Blokken er én samlet kommando (`& { … }`), så en `throw` stopper alt efter den —
også når den indsættes linje for linje i et vindue.

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
- [ ] Wi-Fi fra under "Genererer …", og lad den være fra, til boblen siger "Riggen svarer ikke …" og viser **Prøv igen** (1½–3 minutter: seks forsøg med stigende pause); Wi-Fi til, tryk → billedet kommer (#2464).
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

- [ ] Terminal: `python scripts\media_chat_probe.py --suite video --job-timeout 3600 --report "$env:TEMP\media-chat-video.json"` (beskeden er `lav en video af en papirbåd der driver over en dam`) → værktøj kaldt, ét job, `completed`. Tiden står i tabellen.
- [ ] En længde, brugeren nævner: `python scripts\media_chat_probe.py --suite video-length --job-timeout 3600` (beskeden er `lav en video på 5 sekunder af en papirbåd der driver over en dam`) → `video_generate`, `completed`. Tabellen kan ikke se klippets længde: afspil det, og sammenlign jobtiden med den almindelige video-kørsel (et klip på det halve tager omtrent det halve at rendere).
- [ ] Android: boblen viser status og derefter en afspiller; klippet spiller i boblen.
- [ ] Android: "Fuld skærm" → viser; **Gem** → klippet ligger under `Film/Kaliv`; **Del** → delingsark.
- [ ] Desktop: "Klippet er færdigt" → "Gem klip …" → "Åbn" starter systemets afspiller.

## 5. Billede til video — kræver §6 i kvalificeringen

Forudsætning: en billede-til-video-profil med sin egen template og port
(kvalificeringens §6). Ingen ny kontakt: `video_generate` vælger profilen efter opgaven.

- [ ] **Før** der findes et færdigt billede i dag: `lav en video af det billede` → svaret siger, at der ikke er noget færdigt billede. Intet job.
- [ ] Lav et billede (besked 1), vent til det er færdigt, og skriv så `lav en video af det billede` som næste besked → videoboble; klippet **starter fra det billede**.
- [ ] Tre gange i træk, målt: `python scripts\media_chat_probe.py --suite i2v --rounds 3 --job-timeout 3600 --report "$env:TEMP\media-chat-i2v.json"`. Hver runde laver et billede og beder derefter om `lav en video af det billede` som næste tur. Tabellen viser klippets profil i kantet parentes: står der tekst-til-video-profilen, sendte modellen **ikke** kilden med, og klippet ligner ikke billedet.
- [ ] **To samtaler** (review 6004675603 — det er den måling, reviewet beder om før noget kan kaldes korrekt): `python scripts\media_chat_probe.py --suite two-conversations --stream --rounds 2 --job-timeout 3600 --report "$env:TEMP\media-chat-two-conversations.json"`. Proben laver et billede i samtale A, et i samtale B (som bliver færdigt senere), og beder så om `lav en video af det billede` tilbage i A. Klippets reference siger, hvilket billedjob det starter fra (`source_job_id`). **Bestået** kun, hvis det er A's billede. `wrong_source` = klippet startede fra B's billede; `source_not_reported` = workeren er ældre end #2466.

## 6. Video med lyd (LTX-2.3) — kørt 22/11

Forudsætning: [MEDIA_VIDEO_RIG_QUALIFICATION.md](MEDIA_VIDEO_RIG_QUALIFICATION.md) §8
(vægte hentet, begge grafer kørt direkte mod ComfyUI, profilerne
`ltx23-t2v-av-gpu1` og `ltx23-i2v-av-gpu1` skrevet af `scripts\media_comfy_ltx23_setup.py`).
Blokkene her er dem, der blev kørt på riggen 22/11 [kørt 22/11]; tallene står i §8.1–8.2.

**6.1 Env** — LTX som standard for video, Wan stadig slået til. Kommalisten giver
én standardprofil pr. opgave; RAM-loftet stopper ComfyUI, før Windows løber tør
(40 passer til 64 GB RAM; 22/11 formiddag kørte 98 GB med 64).

Filen omskrives ikke fra skallen: `scripts\media_env_set.py` fjerner kun de
nævnte nøgler og tilføjer dem igen, lader alle andre linjer stå byte for byte
(også æ/ø/å, uanset filens tegnsæt), tager først en backup under et nyt navn
(`modelrig.env.bak-<UTC-tid>`, aldrig oven i en ældre) og bytter først filen ud,
når den nye er skrevet og kontrolleret. [repo; 22/11 blev nøglerne sat ved at
omskrive hele filen fra skallen, som denne blok afløser — selve værktøjet er
ikke kørt på riggen]

```powershell
cd C:\Users\an001\Desktop\ModelRig-media
python scripts\media_env_set.py --file C:\Rig\ModelRig\modelrig.env `
  "KALIV_MEDIA_PROFILES_ENABLED=sdxl-base-1-0,realvisxl-4-0,wan21-t2v-1p3b-gpu1,wan22-ti2v-5b-gpu1,ltx23-t2v-av-gpu1,ltx23-i2v-av-gpu1" `
  "KALIV_VIDEO_TOOL_PROFILE=ltx23-t2v-av-gpu1,ltx23-i2v-av-gpu1" `
  "KALIV_COMFY_HOST_MEMORY_GIB=40"
```

Den skriver de tre linjer og `BACKUP <sti>`. Tilbage til før: kopiér netop den
backup oven i `modelrig.env`. `AFVIST` eller `FEJL` betyder, at filen ikke er rørt.

**6.2 Start** — fire vinduer, i denne rækkefølge. Hver blok er selvstændig: et nyt
vindue kender hverken `$Repo`, `$GenPy` eller tokenet (det kostede tre fejlkørsler 22/11).
En manuel ComfyUI på port 8188 skal være stoppet først — den holder kort 1.

Ollama på kort 0 (lad stå; uden dette deles chatmodellen over begge kort):

```powershell
Get-Process ollama* -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 3
$env:CUDA_VISIBLE_DEVICES = ((nvidia-smi --query-gpu=index,uuid --format=csv,noheader | Where-Object { $_ -match '^0,' }) -replace '^0,\s*','').Trim()
$env:OLLAMA_SCHED_SPREAD = "false"; $env:OLLAMA_VULKAN = "false"; $env:OLLAMA_CONTEXT_LENGTH = "8192"; ollama serve
```

Dev-appliancen (beder om administrator):

```powershell
& "C:\Users\an001\Desktop\ModelRig-media\START_DEV_APPLIANCE.cmd" -ApplianceDir C:\Rig\ModelRig -SkipVisionRig
```

Executoren (ikke administrator, lad stå; `exit=73` = en gammel executor lever endnu,
`exit=78` = `KALIV_MEDIA_EXECUTOR=1` mangler):

```powershell
$GenPy = "C:\Kaliv\media-venv\Scripts\python.exe"; $Repo = "C:\Users\an001\Desktop\ModelRig-media"; $EnvFile = "C:\Rig\ModelRig\modelrig.env"
Get-Content $EnvFile | Where-Object { $_ -match '^(KALIV_MEDIA|KALIV_GPU|KALIV_COMFY|CUDA_)' } | ForEach-Object { $k,$v = (($_ -split '#')[0]) -split '=',2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process') }
$env:KALIV_MEDIA_EXECUTOR = "1"; $env:HF_HUB_OFFLINE = "1"; $env:TRANSFORMERS_OFFLINE = "1"
Push-Location "$Repo\worker"; try { & $GenPy -u -m app.media_executor_main --device cuda:1 2>&1 | Tee-Object "$env:TEMP\media-executor.log" -Append; "exit=$LASTEXITCODE" } finally { Pop-Location }
```

`-Append` er med vilje: uden den overskriver hver genstart loggen fra den forrige
kørsel, og så kan hverken fejlsøgning eller 7.3 se, hvad der skete før genstarten.

Probe (token og mappe sættes i samme blok):

```powershell
cd C:\Users\an001\Desktop\ModelRig-media
$B = "http://127.0.0.1:8080"
$code = (Invoke-RestMethod "$B/api/v1/pair/start" -Method Post -ContentType 'application/json' -Body '{}').code
$env:MODELRIG_TOKEN = (Invoke-RestMethod "$B/api/v1/pair/claim" -Method Post -ContentType 'application/json' -Body (@{ device_name = 'rig-terminal'; code = $code } | ConvertTo-Json)).token
python scripts\media_chat_probe.py --suite video --rounds 2 --job-timeout 3600 --report "$env:TEMP\media-chat-ltx-video.json"
python scripts\media_chat_probe.py --suite i2v --rounds 2 --job-timeout 3600 --report "$env:TEMP\media-chat-ltx-i2v.json"
```

**6.3 Hvad du skal se**

- [ ] `video`: begge runder `completed` på `ltx23-t2v-av-gpu1`. Første job efter en genstart er koldt (22/11, 64 GB: 351 s for 10 s klip), det næste varmt (199 s). Allerførste job nogensinde hasher 41 GB vægte oveni.
- [ ] `i2v`: billede `completed` på `realvisxl-4-0`, klip `completed` på `ltx23-i2v-av-gpu1` (22/11, 64 GB: 115 s + 234 s). Ingen `gpu_busy` — det var fejlen før #2478.
- [ ] Et job, der ender med `output_has_no_sound`, er lydkravet, der slår til: profilen lover lyd, og klippet har intet lydspor. Det er en fejl i grafen eller vægtene, ikke i tjekket — send executor-loggen.
- [ ] Telefon: bed om en video og **hør** den. Standardlængden er profilens loft (241 billeder ≈ 10 s fra tekst, 121 ≈ 5 s fra billede), så regn med godt tre minutter.
- [ ] Skift af kliplængde: `scripts\media_comfy_ltx23_setup.py run --frames N` (8n+1) mod en manuel ComfyUI skriver den målte længde som profilens loft. Stop executoren først, og genstart den bagefter.

Executor-loggens sidste linjer, når noget fejler: `Get-Content "$env:TEMP\media-executor.log" -Tail 30`.

## 7. Acceptforløb på én kandidat-SHA — succes, fejl og genstart

Spor A, slice A1 (#2264). Afsnit 1–6 viser, at kæden **kan** virke. Dette afsnit er
det, der kan kaldes accepteret: ét forløb på **én** commit, hvor også det, der går
galt, er set. **Intet her er kørt** [repo: hver forventet tekst er læst i koden på
`main`, ikke set på riggen]. Grøn CI er ikke en fysisk PASS, og et forløb på en
anden commit end kandidaten tæller ikke.

**7.0 Før du starter — skriv det ned**

| | |
|---|---|
| Kandidat-SHA (worktree: `git log --oneline -1`) | |
| APK: `candidate-apk`-kørslens `headSha` (skal være samme SHA, se 2.1) | |
| Desktop bygget fra samme SHA | |
| Profiler slået til (`KALIV_MEDIA_PROFILES_ENABLED`) | |
| Dato, hvem | |

Læg først en eventuel gammel executor-log til side, så forløbets log kun er
forløbets (executoren skal være stoppet):

```powershell
if (Test-Path "$env:TEMP\media-executor.log") { Move-Item "$env:TEMP\media-executor.log" "$env:TEMP\media-executor-foer-$(Get-Date -Format yyyyMMdd-HHmmss).log" }
```

Start som i 6.2. Hav executor-vinduet synligt hele vejen. F1 og F5 genstarter
executoren; 6.2's blok skriver videre i samme log (`-Append`), så alt fra S1 til
F8 står i én fil, når 7.3 søger i den.

**7.1 Succes** — hver på telefonen **og** på desktop:

| # | Gør | Forventet | Tlf. | Desktop |
|---|---|---|---|---|
| S1 | `lav et billede af en rød cykel ved en sø` | boble "I kø på riggen" → "Genererer …" → billedet | | |
| S2 | `lav en video af en papirbåd der driver over en dam` | videoboble → klip, **med lyd** når standardprofilen er LTX | | |
| S3 | efter S1: `lav en video af det billede` | klippet starter fra S1's billede | | |
| S4 | `lav en video på 5 sekunder af en papirbåd der driver over en dam` | klip på ca. 5 s (afspil det; jobtiden er omtrent det halve af S2) | | |
| S5 | Vent, til S2's boble **står i samtalen**. Luk så appen helt, mens klippet renderer, og åbn samtalen igen | boblen er der stadig og følger jobbet til klippet | | |
| S6 | Åbn galleriet | S1–S4 ligger der | | |

S5 dækker **kun** en klient, der allerede har gemt jobbet (boblen var synlig, før
appen blev lukket). Vinduet, hvor klienten dør, efter riggen har svaret, men før
klienten har gemt jobbet lokalt, er **ikke** med: der mister klienten pegepinden,
og ingen klient henter i dag jobbet tilbage (#2475 — riggen har listen
`GET /api/v1/media/jobs/recent`, klienterne bruger den ikke endnu). Et bestået S5
siger derfor ikke, at et job overlever et klientnedbrud i almindelighed.

**7.2 Fejl — hver skal ende i en besked, et menneske kan forstå, og aldrig i en boble, der hænger**

| # | Sådan fremkaldes den | Forventet på riggen | Forventet i chatten |
|---|---|---|---|
| F1 Executor nede | Stop executoren (Ctrl+C). Bed om et billede. | Jobbet bliver stående `queued`; intet i executor-loggen | Boble "I kø på riggen" — og den bliver der. Start executoren: jobbet køres. (Uden start: "Udløbet: riggen nåede ikke at starte jobbet inden for et døgn" efter 24 timer — **vent ikke på det**, notér kun at boblen står i kø.) |
| F2 For mange på én gang | Blokken **F2** under tabellen: executoren stoppet, præcis tre job lagt i kø via API'et, derefter ét forsøg via API og ét i chatten | API: fjerde indsendelse giver HTTP 429 `active_limit`. Worker-log: `media_tool=refused modality=image code=owner_limit` | Svaret siger, at riggen er optaget, og at man kan bede igen, når et er færdigt. **Ingen** ny boble. |
| F3 Afvist argument | `lav et billede i 4000 gange 4000 pixels af en rød cykel` | `media_tool=refused … code=invalid_request optional=width,height` i worker-loggen, eller modellen prøver igen uden størrelsen og får et job | Enten et billede i riggens størrelse eller et svar om, at det ikke kunne lade sig gøre. Aldrig en boble uden job. |
| F4 Intet billede at animere | I en **ny** samtale: `lav en video af det billede` | intet job (`no_source_image`) | Svaret siger, at der ikke er noget færdigt billede |
| F5 Executor dræbt midt i et job | Bed om en video; når executor-loggen viser `loaded`, luk executor-vinduet. Start executoren igen. | Ved start: `recovered` med 1; jobbet er `failed` med `interrupted_by_restart` | Boblen: "Afbrudt: riggen genstartede". Indtil executoren er startet igen, står der "Genererer …" — det er forventet. |
| F6 Worker genstartet midt i et job | Bed om en video; genstart dev-appliancen (vindue A), mens den renderer | Jobbet fortsætter i executoren og bliver `completed` | Boblen kan vise "Riggen svarer ikke; klippet ligger i galleriet, når det er klar" med **Prøv igen**; efter Prøv igen kommer klippet |
| F7 Uden parring | På riggen: `Invoke-WebRequest http://127.0.0.1:8080/api/v1/media/jobs/recent -SkipHttpErrorCheck` (uden token) | HTTP 401, `Cache-Control: private, no-store` | — |
| F8 Værktøj slukket | `KALIV_VIDEO_TOOL_ENABLED=0`, genstart vindue A, bed om en video | `video_generate` står ikke i 1.3's liste | Et tekstsvar; ingen boble, ingen påstand om et klip |

**F2 — sådan stilles den op.** Kvoten er tre aktive job pr. installation
(`max_owner_active=3` i `image_job_store.submit`; der er ingen indstilling for
den). At skrive fire beskeder hurtigt afhænger af, hvor hurtigt riggen bliver
færdig, og tæller ikke. Stop executoren (Ctrl+C) — så bliver job stående i kø —
og kør i vindue C (`$B` og `$H` fra 1.3). Blokken er **én** sætning (`& { … }`):
stopper et tjek den, bliver resten ikke kørt. `$ids` rummer de job, der faktisk
blev lagt i kø, også hvis blokken stopper undervejs, og en kørsel, der stopper
på "allerede aktive", rører ikke `$ids` fra en tidligere kørsel:

```powershell
& {
    $img = ((Invoke-RestMethod "$B/api/v1/media/jobs/profiles" -Headers $H).profiles | Where-Object modality -eq 'image' | Select-Object -First 1).profile_id
    if (-not $img) { throw 'F2 IKKE KØRT: ingen billedprofil er slået til' }
    $before = @((Invoke-RestMethod "$B/api/v1/media/jobs/recent" -Headers $H).jobs | Where-Object state -in 'queued','running','publishing')
    if ($before.Count -ne 0) { throw "F2 IKKE KØRT: $($before.Count) job er allerede aktive - vent eller annullér dem først" }
    $global:ids = @()
    $body = @{ profile_id = $img; prompt = 'en rød cykel ved en sø' } | ConvertTo-Json
    1..3 | ForEach-Object { $global:ids += (Invoke-RestMethod "$B/api/v1/media/jobs" -Method Post -Headers $H -ContentType 'application/json' -Body $body).id }
    $queued = @((Invoke-RestMethod "$B/api/v1/media/jobs/recent" -Headers $H).jobs | Where-Object { $_.id -in $ids -and $_.state -eq 'queued' })
    if ($queued.Count -ne 3) { throw "F2 IKKE KØRT: $($queued.Count) af 3 står i kø (kører executoren?)" }
    $r = Invoke-WebRequest "$B/api/v1/media/jobs" -Method Post -Headers $H -ContentType 'application/json' -Body $body -SkipHttpErrorCheck
    "fjerde: HTTP $($r.StatusCode) $($r.Content)"
}
```

Forventet sidste linje: `fjerde: HTTP 429` med `active_limit`. Bed **nu** — mens de
tre står i kø — om et billede i chatten (telefon og desktop) og notér svaret.
Ryd derefter op, **før** executoren startes, så de tre ikke bliver renderet:

```powershell
$ids | ForEach-Object { (Invoke-RestMethod "$B/api/v1/media/jobs/$_/cancel" -Method Post -Headers $H).result }
```

Forventet: `cancelled` tre gange (færre eller ingen linjer, hvis blokken stoppede,
før alle tre lå i kø). Start executoren igen som i 6.2. Stoppede blokken
med `F2 IKKE KØRT`, er F2 **ikke kørt** — det er ikke en fejl i kæden; ryd op, og
stil den op igen. Fik den fjerde indsendelse andet end 429 `active_limit`, mens de
tre stod i kø, er F2 **fejlet**.

`output_has_no_sound` (en lydprofil, hvis klip mangler lydspor) kan ikke fremkaldes
uden at ændre en profil eller en graf; den er dækket af
`tests/worker_comfy_video_adapter.py` og regnes **ikke** som fysisk set.

**7.3 Loggene må ikke indeholde det, brugeren skrev** — efter 7.1 og 7.2, i executor-vinduet:

```powershell
$needles = 'rød cykel', 'red bicycle', 'papirbåd', 'paper boat'
$logs = "$env:TEMP\media-executor.log", "C:\Kaliv\media-work\comfy\cuda1\comfyui.log"
foreach ($log in $logs) { foreach ($n in $needles) { $hits = @(Select-String -Path $log -SimpleMatch $n -ErrorAction SilentlyContinue); "{0,-60} {1,-14} {2} linjer" -f $log, $n, $hits.Count } }
```

Tjek først, at loggen dækker hele forløbet — den skal indeholde lige så mange
`recovered`-linjer, som executoren er startet (mindst fire: start, efter F1, efter F2, efter F5):

```powershell
@(Select-String -Path "$env:TEMP\media-executor.log" -SimpleMatch '"event": "recovered"').Count
```

Viser den færre, er en del af forløbet ikke i loggen, og 7.3 kan ikke bestås på den.

Forventet: 0 linjer i `media-executor.log` (den skriver job-id, profil og koder).
`comfyui.log` er ComfyUI's egen log; finder blokken prompten dér, så notér det
som et fund med linjen — det er ikke afgjort, hvad den log må indeholde.
Kør samme søgning mod dev-appliancens worker-log, hvis den skrives til en fil.

**7.4 Dommen**

Hvert tilfælde får præcis én af tre:

- **PASS** — set på kandidat-SHA'en, og resultatet er det, der står under "Forventet".
- **FAIL** — kørt, og resultatet var noget andet. Skriv, hvad der faktisk skete.
- **IKKE KØRT** — ikke forsøgt, eller opstillingen blev ikke etableret (fx `F2 IKKE KØRT`).

En noteret afvigelse er **FAIL**, ikke PASS: at den er skrevet ned, gør den ikke
bestået. Hvor "Forventet" selv nævner to udfald (F3, F6), er begge PASS — alt
andet er FAIL.

| Tilfælde | Tlf. | Desktop | Afvigelse (hvad skete der faktisk) |
|---|---|---|---|
| S1 | | | |
| S2 | | | |
| S3 | | | |
| S4 | | | |
| S5 | | | |
| S6 | | | |
| F1 | | | |
| F2 (API-delen: én kolonne er nok) | | | |
| F3 | | | |
| F4 | | | |
| F5 | | | |
| F6 | | | |
| F7 (kun riggen) | — | — | |
| F8 | | | |
| 7.3: ingen prompt i executor-loggen, og loggen dækker forløbet | — | — | |

F7 og 7.3 har ét resultat; skriv det i afvigelseskolonnen som PASS/FAIL/IKKE KØRT.

| | |
|---|---|
| Rapporter gemt: `media-chat-*.json`, executor-log, F2-blokkens output, skærmbilleder af F2, F5 og F6 | |
| **Samlet** | |

Medie-i-chat er **fysisk accepteret på den SHA** kun, når **hver** række ovenfor er
PASS på både telefon og desktop (hvor rækken har begge), og rapporterne er gemt.
Én FAIL eller én IKKE KØRT giver samlet **IKKE ACCEPTERET** — der er ingen
valgfrie tilfælde. Accepten gælder det, tilfældene dækker: ikke det tabte-pegepind-
vindue under S5 (#2475) og ikke `output_has_no_sound`. Det er en accept af denne
kæde på udviklingskanalen — ikke en V1-gate og ikke en kvalificering af
profilerne, som fortsat er `candidate`.

## 8. Medie fra en udgivet appliance — tjek før du sætter tid af

Alt ovenfor er kørt fra kildekoden med executoren startet i hånden. I en release
er tre ting anderledes, og ingen af dem er set på riggen:

- **Supervisoren starter executoren** ud fra fire nøgler i env-filen
  (`KALIV_MEDIA_EXECUTOR`, `_DEVICES`, `_PYTHON`, `_APP_DIR`).
- **Executoren kører stadig fra et kilde-checkout** (`_APP_DIR`), fordi torch ikke
  er i den pakkede worker. Det checkout skal stå på releasens egen commit.
- **Alle kontakter læses fra env-filen**, ikke fra et PowerShell-vindue.

En fejl i en af dem viser sig som "der sker ingenting". `scripts\media_release_preflight.py`
stiller de samme spørgsmål på forhånd, på få sekunder, og skriver hvad der skal
rettes. Den læser kun: env-filen, de filer den peger på, `nvidia-smi`,
medie-miljøets `import torch`, Ollamas modelliste og appliancens `/healthz`. Den
skriver intet, starter intet og viser ikke værdien af en hemmelighed.

Linjen `executor cuda:N: egen startkontrol` er den, der afgør: den kører executorens
egen kontrol (`check_start` — alt den ser på, før den rører jobdatabasen) mod
env-filen og gengiver dens afvisning ordret. Det fanger også det, der hidtil kun
har været sat i et PowerShell-vindue, fx `CUDA_DEVICE_ORDER=PCI_BUS_ID`,
lease-mappen og ComfyUI-mapperne pr. kort. Scriptet kører i en almindelig Python
3.11; det kræver hverken FastAPI eller torch.

Fra et checkout, der har scriptet (her kandidat-checkouten):

```powershell
cd C:\Users\an001\Desktop\ModelRig-git
py -3.11 scripts\media_release_preflight.py --env-file C:\Rig\ModelRig\modelrig.env --planner-model qwen3:14b 2>&1 | Tee-Object $env:TEMP\media-release-preflight.txt
```

Når tagget findes, bindes executorens kilde til det (blokken stopper, hvis tagget
ikke er hentet):

```powershell
cd C:\Users\an001\Desktop\ModelRig-git
$tag = 'v2.0.21'
$sha = (git rev-parse "$tag^{commit}").Trim()
if ($sha -notmatch '^[0-9a-f]{40}$') { throw "$tag er ikke hentet: git fetch --force origin tag $tag" }
py -3.11 scripts\media_release_preflight.py --env-file C:\Rig\ModelRig\modelrig.env --planner-model qwen3:14b --expect-version $tag.TrimStart('v') --expect-sha $sha 2>&1 | Tee-Object $env:TEMP\media-release-preflight.txt
```

| Linje | Betyder |
|---|---|
| `OK` | som en release kræver det |
| `WARN` | virker, men er værd at se på (fx hukommelse i brug på executorens kort) |
| `FAIL` | releasen laver ikke billede/video sådan; linjen under (`->`) siger hvad der skal ændres |
| `INFO` | oplysning, ikke en dom (fx at appliancen ikke kører lige nu) |

Sidste linje tæller dem. **Ingen FAIL er ikke en kvalifikation og ikke et job** —
første billede og første klip fra den udgivne appliance er stadig prøven (§7).
Tjekket læser kun env-filen: en nøgle, der kun er sat i supervisorens eget miljø,
meldes som manglende, selv om appliancen ville se den.

## Hvad der skal med hjem

Skriv det som én kommentar på #2419:

1. Tallene fra 0.4 (GPU 0 / GPU 1 med chatmodellen indlæst).
2. Probens tabel fra 1.5 (og JSON-filen som bilag), og om executoren udskød et job.
3. Tabellen fra 2.2 og afkrydsningerne fra 2.3 og 3.
4. Alt, der så forkert ud, med skærmbillede — også småting i boblerne.
5. For trin 4–5: probens tabeller for `video` og `i2v`.

## Stopregler

- Værktøjet kaldes 0 af 3 gange i 1.4 → stop; resten måler ikke noget. Kaldes det i under halvdelen af probens tilfælde (1.5), så kør stadig trin 2–3 for boblernes skyld, men notér raten først: den er det vigtigste tal fra aftenen.
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
