# Person Profile — den fælles kontrakt (#752)

ModelRig/Kaliv understøtter flere personer samtidig. Hver person har én
stabil identitet og versionsstyrede **body**-, **voice**- og
**personality**-komponenter under sig.

## Den ene regel: atomisk person-aktivering

Body, voice og personality aktiveres **aldrig** uafhængigt.

Komponentrevisioner er kandidater. Det eneste, der kan være aktivt, er en
godkendt **Person Revision** — en konkret tripel:

    person-r0007 = body-r0003 + voice-r0002 + personality-r0005

En ny komponentrevision ændrer intet ved den aktive person. En Person
Revision kan kun oprettes, når et compatibility-review eksplicit har
bekræftet alle fire checks:

- `body_voice` — body ↔ voice matcher,
- `voice_personality` — voice ↔ personality matcher,
- `body_personality` — body ↔ personality matcher,
- `overall` — samlet sammenhæng.

Virker stemmen for ung til kroppen, bliver kombinationen ikke aktiv; der
laves en ny kandidat først. Godkendte Person Revisions er uforanderlige —
den eneste vej til en anden tripel er en ny revision med sit eget review.

## Identitet

Stabilt `person_id`: `person-<32 lowercase hex>`.

`bodyid-*`, VoiceRig voice-id, Stash performer-id og display name er
komponent-/kilde-identiteter og bruges **ikke** som personens stabile id.
Revisioner navngives `body-rNNNN`, `voice-rNNNN`, `personality-rNNNN`
og `person-rNNNN` pr. person.

## Ejerskab

ModelRig ejer personality/persona-execution og runtime-siden: ved valg af
person anvendes **samme aktive Person Revision** til alle tre bindings.
BodyRig og VoiceRig ejer artefakterne bag `bodyid-*` og voice-id'er;
registret refererer til dem, det indeholder dem ikke.

Personality-revisioner bærer mindst: `system_instructions`,
`default_language`, valgfri `style_notes` og `feedback`.

## API (worker `/persons`, backend `/api/v1/persons` bag device-token)

| Metode | Sti | Effekt |
|---|---|---|
| GET | `/persons` | liste + `selected_person_id` |
| POST | `/persons` | opret person (`display_name`) |
| GET | `/persons/{id}` | én person med alle revisioner |
| POST | `/persons/{id}/body-revisions` | ny body-kandidat (`source_id`, `note`) |
| POST | `/persons/{id}/voice-revisions` | ny voice-kandidat (`source_id`, `note`) |
| POST | `/persons/{id}/personality-revisions` | ny personality-kandidat |
| POST | `/persons/{id}/person-revisions` | ny Person Revision — kræver fuldt `review` + `reviewer` |
| POST | `/persons/{id}/activate` | sæt `active_person_revision` — **eneste aktiveringsrute** |
| POST | `/persons/select` | vælg person for runtime |
| GET | `/persons/active` | valgt person + opløste bindings fra dens aktive revision |

Der findes ingen rute, der aktiverer én komponent alene. Det er en del af
kontrakten og bindes af `tests/worker_person_registry.py`, som læser
routerens ruteinventar.

## Persistens

Ét JSON-dokument (`modelrig-person-registry/v1`), skrevet atomisk.
Sti: `KALIV_PERSONS_STORE` (default `persons-registry.json` i workerens
arbejdsmappe).

## Status

- Registry, API og kontrakttests: landet (worker).
- Backend-forwarding `/api/v1/persons` bag device-token: landet. Lukket
  allowlist af under-ruter; ugyldige id'er og ukendte handlinger afvises
  FØR workeren nås; kræver loopback-worker.
- Runtime-binding: landet for `tools/chat` og `tools/chat/stream` (den vej
  Android altid bruger). Med en valgt person med aktiv revision vinder
  registrets personality over klientens `system`-tekst, og svaret bærer
  `person` (person_id, person_revision, personality_revision). Uden valgt
  person er adfærden uændret. Plain `/api/v1/chat` går direkte til Ollama
  uden om workeren og er IKKE bundet — kendt hul for desktop-plain-chat.
- Voice-binding (VoiceRig-profil fra `voice`-revisionen) og body-binding
  (BodyRig) læser samme `active_bindings()`; deres runtime-integration er
  deres egne spor.
