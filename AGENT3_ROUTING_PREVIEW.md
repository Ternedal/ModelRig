# Kaliv Agent 3.0 — Routing Preview

Status: **developer-only, feature-flagged og ikke koblet til normal chat-routing.**

Routing Preview viser, om en almindelig turn *kunne* kvalificere til Agent 3.0's
udviklersti ud fra serverens aktuelle route-, capability- og evidensstatus.
Endpointet ændrer aldrig den faktiske routing.

## Sikkerhedsinvariant

Hver gyldig respons har:

```json
{
  "selected_surface": "agent_v2",
  "production_activation": false,
  "planned": false,
  "executed": false
}
```

Klienterne afviser responsen, hvis serveren påstår noget andet.

Routing Preview:

- kalder ikke en planner eller answer-model,
- opretter ikke en plan eller et run,
- eksekverer ikke tools,
- læser eller skriver ikke memory,
- ændrer ikke normal Android-/desktop-chat,
- kan ikke aktivere Agent 3.0 eller produktion,
- echo'er ikke beskedteksten i svaret.

Beskeden repræsenteres kun ved tegnantal og SHA-256 receipt.

## Endpoint

```text
POST /api/v1/experimental/agent3/routing-preview
Authorization: Bearer <paired device token>
Content-Type: application/json
```

Eksempel:

```json
{
  "message": "Vis status på riggen",
  "mode": "rig",
  "tools": true,
  "rag": false,
  "has_image": false,
  "voice": false,
  "allow_rag_cloud": false,
  "auto_cloud_fallback": false
}
```

Klienten kan kun beskrive selve turnen. Følgende kan ikke injiceres:

- `cloud_ready`,
- `worker_ready`,
- `tools_ready`,
- validation-/promotionstatus,
- capability graph,
- risk, sensitivity eller egress,
- den valgte produktionssurface.

Ukendte felter afvises med HTTP 422.

## Respons

Responsen viser blandt andet:

- `selected_surface`: altid `agent_v2`,
- `candidate_surface`: `agent3_developer_preview` eller `null`,
- `eligible_for_agent3_preview`,
- den deterministiske `route`,
- påkrævede capabilities,
- konkrete blockers og warnings,
- developer-preview- og write-pilot-evidens,
- capability graph-schema,
- message SHA-256 og tegnantal.

En positiv kandidatstatus er kun observation. Den giver ikke adgang til planner,
run-start, confirmation eller tools.

## Serverautoritære facts

Workerens preview-snapshot bruger den eksisterende V2 ToolGate som autoritet for
tool readiness.

I den aktuelle draft er følgende bevidst fail-closed i routing preview:

- cloud readiness,
- voice readiness.

De må først blive dynamiske, når en fremtidig RigGate leverer betroede runtime-facts.
RAG readiness er fortsat en lokal worker-capability, mens developer-preview-evidens
kommer fra den eksisterende versionbundne promotions-gate.

## Aktivering

Både backend og worker skal startes med:

```powershell
$env:KALIV_AGENT3_ENABLED = "1"
$env:KALIV_TOOLS_ENABLED = "1"
```

Alle offentlige routing-preview-kald går gennem Go-backendens almindelige
Bearer-middleware. Workerens direkte endpoint er fortsat loopback-only og uden egen
auth, ligesom de øvrige worker-routes.

## Desktop

```powershell
cd desktop
.\gradlew.bat :composeApp:run --args="--agent3-routing-preview"
```

Skærmen:

- bruger eksisterende backend-URL og device-token,
- lader udvikleren beskrive turnens mode/tools/RAG/image/voice-flags,
- viser route, required capabilities, blockers og receipts,
- har ingen knap til at starte Agent 3.0.

Normal desktop-start uden flag kalder fortsat den eksisterende `App()`.

## Android

```powershell
adb shell am start -S `
  -n dk.ternedal.modelrig/.MainActivity `
  --ez dk.ternedal.modelrig.extra.AGENT3_ROUTING_PREVIEW true
```

Android-skærmen bruger kun den allerede gemte rig-URL og device-token fra
`TokenStore`. Der er ingen launcher-knap, deep link eller ekstra eksporteret activity.
Normal launcher-start åbner fortsat `AppUi()`.

## Testbeviser

Testpakken dækker:

- plain chat bliver på Agent v2,
- lokale tools og RAG evalueres mod de korrekte capabilities,
- cloud, voice og image fejler lukket, når capabilities/policy ikke tillader dem,
- manglende fysisk developer-preview-evidens er en synlig blocker,
- beskedteksten forekommer ikke i responsen,
- klientinjektion af readiness/evidens afvises,
- feature flag off giver 404,
- feature flag on kræver Bearer-token,
- Go-backend forwarder til worker og aldrig direkte til Ollama,
- begge klienter afviser aktivering, planlægning eller eksekvering i responsen,
- worker-mount er idempotent,
- normal Agent v2-/chat-surface forbliver urørt.

## Næste gate før rigtig routing

Routing Preview er bevidst et observationslag. Før normal chat må vælge Agent 3.0,
skal mindst følgende leveres og valideres separat:

1. frisk versionbundet fysisk rig-evidens,
2. betroet RigGate-snapshot for cloud/voice/runtime readiness,
3. en eksplicit shadow-evalueringsperiode med audit og ingen routingændring,
4. klientvisning og brugeraccept før første Agent 3.0-run,
5. rollback/kill-switch-test på den fysiske rig,
6. separat beslutning om hvilke turn-typer der overhovedet må være kandidater.

Ingen af disse gates åbnes automatisk af denne leverance.
