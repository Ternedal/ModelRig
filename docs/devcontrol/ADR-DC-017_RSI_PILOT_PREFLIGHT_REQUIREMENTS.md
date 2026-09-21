# ADR-DC-017 — Inert DC-L16 pilot preflight requirements manifest

**Dato 13/09-2026. Status: foreslået til beslutning.**

## Kontekst

ADR-DC-015 kan verificere en separat menneskelig `GO`, `NO-GO` eller
`GO WITH CONDITIONS` beslutning uden at starte DC-L16. ADR-DC-016 kan derefter
indsnævre et positivt human proof til præcis én inert trial-scope.

Issue #423 kræver imidlertid flere runtime-egenskaber før en rigtig product-pilot
må starte: feature flag skal fortsat være off indtil den eksplicitte start,
native Windows isolation og trusted-Git closure skal genbruges, kill/revoke skal
være præpareret, credentials og network-write skal være fraværende, off-state må
ikke importere DevControl, og execution/receipt skal være exact bundet.

Det er vigtigt ikke at forveksle en liste over disse krav med et bevis for, at de
er opfyldt.

## Beslutning

Der indføres et rent, deterministisk requirements-manifest:

`kaliv-rsi-dc-l16-pilot-preflight-requirements/v1`

Manifestet må kun afledes fra en exact `PilotTrialScopeProof` med authority
`verified-dc-l16-single-trial-scope-only` og med alle runtime/start/publication-
grænser fortsat lukkede.

Manifestet kopierer exact scope-bindinger:

- trial-scope digest;
- human decision-proof digest;
- campaign/task/task-digest;
- repository, base SHA og requested-main SHA;
- decision ID og decision type;
- trial ID;
- operator surface;
- præcis ét selected pilot task ID;
- workspace-root path digest;
- local-commit valget;
- eventuelle human conditions/notes.

## Krav som manifestet fastlåser

Et senere, separat runtime-preflight proof skal mindst bevise:

1. feature flag er observeret off før preflight/start;
2. pilot runtime-boundary er verificeret;
3. native Windows isolation er til stede;
4. trusted-Git closure er til stede;
5. kill switch er prearmed;
6. restart/revoke er prearmed;
7. network write er blokeret;
8. credentials er fraværende fra pilot-runtime;
9. unattended cadence er forbudt;
10. off-state blokerer produktimport af DevControl;
11. source/base/head binding er exact;
12. receipt-binding er påkrævet.

Disse felter betyder **required**, ikke **observed**.

## Fail-closed non-authority

Et gyldigt ADR-DC-017 manifest skal altid have:

- `pilot_scope_verified=true`;
- alle ovenstående `*_required`/`*_forbidden` krav sat `true`;
- `preflight_observed=false`;
- `preflight_satisfied=false`;
- `pilot_start_authorized=false`;
- `product_pilot_started=false`;
- `remote_write_authorized=false`;
- `push_authorized=false`;
- `pr_mutation_authorized=false`;
- `merge_authorized=false`;
- `release_authorized=false`;
- `deploy_authorized=false`;
- `production_activation_authorized=false`.

Authority er kun:

`dc-l16-pilot-preflight-requirements-only`

Et manifest kan derfor ikke bruges som pilot-admission, runtime proof, start
receipt eller activation authority.

## Conditional GO

Hvis upstream human decision er `GO WITH CONDITIONS`, skal `conditional_go=true`
og alle signerede notes bevares. Et tomt conditions-set fejler lukket. ADR-DC-017
fortolker eller markerer ikke conditions som opfyldt.

## Production boundary

Denne slice tilføjer ingen host-observer, feature-flag reader, command registry,
product entrypoint, executor, credential-loader, network transport eller signer.
Den udfører ingen I/O ud over almindelig in-memory canonicalisering af de
allerede leverede proof-objekter.

`kaliv_dev_control/__init__.py` må fortsat ikke importere manifest-facaden.
Repositoryets normale command catalog forbliver tomt.

## Konsekvens

ADR-DC-017 gør næste authority-step snævrere: en fremtidig runtime-preflight kan
ikke selv vælge hvilke sikkerhedsegenskaber der er relevante. Den skal bevise det
fastlåste requirement-set mod exact ADR-DC-016 scope.

ADR-DC-017 er ikke Anders' GO, er ikke runtime-verifikation og starter ikke en
pilot. `production_activation=false` bevares.
