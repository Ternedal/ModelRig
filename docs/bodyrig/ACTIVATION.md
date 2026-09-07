# BodyRig production activation — #704

Denne slice lukker kun softwarekravet om, at BodyRig-integrationen skal være
**dormant/off som standard**. Den ændrer ikke de fysiske acceptance-krav og giver
ingen production authority.

`production_activation=false`.

## Én production-switch

Den eneste production-aktiveringsnøgle i denne slice er:

```text
KALIV_BODYRIG_ENABLED=1
```

Manglende variabel og alle andre værdier end den trimmede eksakte streng `1`
betyder **off**. Værdier som `true`, `yes` eller `2` aktiverer ikke BodyRig.

Når flaget er **off**:

- production-entrypointet monterer ingen `/body/*` routes;
- body asset- og session-routerne importeres ikke af mount-laget;
- chat-turn phases kalder fortsat deres eksisterende `note_state(...)` hook, men
  hooken returnerer før active-body/session resolution;
- VoiceRig/TTS kalder fortsat `note_speech(...)`, men hooken returnerer før den
  åbner WAV-filen eller rører BodyRig runtime;
- en aktiv `.mrbody` på disken er derfor ikke i sig selv aktivering.

Når flaget er **on**:

- den self-guarded `mount_bodyrig(...)` monterer både validerede body assets og
  live session/frame-surface præcis én gang;
- eksisterende BodyRig runtime-, schema- og profile-validation-regler gælder
  uændret;
- aktivering ændrer **ikke** workerens host/bind/LAN-policy. Et BodyRig-flag er
  ikke netværksautorisation.

Direkte unit tests må stadig bygge routerne isoleret for at teste implementationen;
production-entrypointet går gennem den self-guarded mount. Eksisterende
`tests/worker_body_session.py` sætter derfor flaget eksplicit i sin test-fixture.

## Software-proof

To lag beviser grænsen:

1. `tests/bodyrig/activation_contract.py` er dependency-fri og køres i den
   hurtige exact-head BodyRig-gate. Den pinner exact opt-in, self-guard før lazy
   imports/route-registration, idempotens, hook-order og at production chat +
   VoiceRig fortsat går gennem de guardede hooks.
2. `tests/worker_bodyrig_activation.py` kører i den fulde worker-suite med
   FastAPI-dependencies og beviser den faktiske runtime: ingen `/body/*` routes
   som default, routes ved explicit opt-in, idempotent mount og at disabled
   hooks hverken kalder `current_session()` eller åbner en WAV.

`tests/worker_body_session.py` kører den eksisterende BodyRig implementation med
`KALIV_BODYRIG_ENABLED=1`, så production-default ikke forveksles med et krav om
at gøre implementationen utilgængelig for tests.

## Hvad denne slice ikke beviser

Den er ikke fysisk BodyRig acceptance. #704 forbliver åben, og følgende kan ikke
substitueres med CI:

- upstream fysisk video -> BodyPrint proof;
- source-derived BodyPrint -> fitted VRM/.mrbody proof;
- rigtig Windows/Android/Kaliv runtime, pairing, fallback og reconnect;
- #846's live machine + visual evidence-chain;
- endelig reference til de konkrete upstream proof-identiteter.

Ingen merge, flag-flip eller fysisk acceptance følger automatisk af en grøn
software-gate.
