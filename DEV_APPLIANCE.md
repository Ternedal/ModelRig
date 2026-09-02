# Udviklingskanalen — appliancen kører fra checkouten

**Besluttet 02/09/2026:** så længe intet er i produktion, udvikles der så
hurtigt som muligt. Koden på riggen er det, checkouten holder.

## Hvad det er

`START_DEV_APPLIANCE.cmd` stopper release-appliancen, bygger backend fra
HEAD, starter backend og worker med **appliancens egne data og env**
(`ModelRig-appliance\modelrig.env`, parset med kommentar-strip), binder
backend til LAN så telefonen kan nå den, og venter på begge healthz.

Ny kode på riggen er derefter to skridt:

    git pull --ff-only
    START_DEV_APPLIANCE.cmd

`STOP_DEV_APPLIANCE.cmd` (eller `-Stop`) lukker dev-stakken og starter
`KalivBootstrap` igen, så den signerede release kommer tilbage.

## Telefonen: samme loop

`INSTALL_DEV_APK.cmd` henter CI's kandidat-APK for `origin/main`s tip (og
bestiller bygget, hvis det ikke findes), og installerer den over adb med
`-r -d`. Debug- og release-builds signeres med samme `modelrig`-nøgle og
deler pakkenavn, så den installeres **oven på** release-appen, og parringen
bevares. Regn med 5-8 minutters CI-tid, hvis bygget ikke ligger klar.

Ny kode hele vejen rundt er derfor:

    git pull --ff-only
    START_DEV_APPLIANCE.cmd
    INSTALL_DEV_APK.cmd

## Hvad det ikke er

- **Det er ikke bevis.** Intet, dev-appliancen kører, er kandidatbundet, og
  ingen gate læser dens output. Citér aldrig en dev-kørsel som evidens i et
  issue.
- **Det rører ikke `production_activation`.** Hver konstant forbliver
  `False`; flip-værnet fælder ellers CI. Den fysiske vej — Stage A,
  proof-kampagnen, Stage B — er stadig baren den dag, produktion bliver
  virkelig.
- **Det springer ikke updater-kæden over for altid.** Release-appliancen er
  ét `-Stop` væk.

## Fælder, scriptet allerede kender

- Env-filen parses af `scripts/Read-KalivEnvFile.ps1` — ikke af et regex.
  `KEY=value # kommentar` giver `value`, ikke `value # kommentar`. Det kostede
  tre døgn i august.
- Backend bindes til `0.0.0.0` som standard. Mesh-netværk med
  klient-isolation gør alligevel telefonen blind for riggen; brug da
  `adb reverse tcp:8080 tcp:8080` og `http://127.0.0.1:8080` i appen.
- De to konsolvinduer ER stakken. Luk dem ikke; brug `-Stop`.
