# Kaliv — start riggen og installér appen

To ting for at gøre test og installation lettere.

## Start hele riggen med ét dobbeltklik

Kør `scripts\start-kaliv.bat`. Den:

1. starter **Ollama** (kun hvis den ikke allerede kører),
2. starter **workeren** fra netop denne repo-kopi (så du ikke debugger den
   forkerte kopi — den bruger sin egen placering),
3. starter **serveren** med `MODELRIG_HOST=0.0.0.0` sat — det er den ene ting
   man glemmer, og uden den kan telefonen ikke nå riggen,
4. kalder `/health/full` og skriver en samlet status, så du **ved riggen er
   grøn før du tager telefonen op**.

Tre vinduer kører bagefter (Ollama, worker, server). Luk dem for at stoppe.

Kræver Python på PATH og at `modelrig-server-windows-x64.exe` ligger enten ved
siden af scriptet, i repo-roden, eller på skrivebordet.

## Installér den nyeste app med ét permanent link

Hver release ligger som `modelrig-vX.Y.Z.apk` — versionen skifter hver gang, så
du skal lede efter den nye fil. CI uploader nu **også** samme APK under et fast
navn, så dette link altid peger på den nyeste build:

```
https://github.com/Ternedal/ModelRig/releases/latest/download/kaliv-latest.apk
```

Bogmærk det på Pixel'en. Så er det ét tryk hver gang — ingen navigation i
GitHub-releases. (Første gang skal du tillade "installér ukendte apps" for din
browser/Files-app; derefter er det bare tryk → installér.)
