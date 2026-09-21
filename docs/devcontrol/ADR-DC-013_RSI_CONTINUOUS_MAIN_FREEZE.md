# ADR-DC-013 — Live continuous `main` freeze over one physical campaign

**Dato:** 13/09-2026  
**Status:** Foreslået til beslutning  
**Aktivering:** `production_activation=false`

## Problem

ADR-DC-010 kan autorisere starten af én manuel fysisk DC-L15-kampagne.
ADR-DC-011 kan verificere post-campaign physical evidence, og ADR-DC-012 kan
binde den exact runner/report execution til en separat human/Ed25519-signatur.

Kæden mangler stadig et bevis for, at local `refs/heads/main` forblev uændret
gennem hele den relevante execution/evidence-periode. Samme SHA før og efter er
ikke tilstrækkeligt: en ref kan flyttes og senere flyttes tilbage uden at være
synlig i to punktmålinger.

## Beslutning

`continuous_main_freeze_confirmation` lukkes kun af en live, process-local
freeze-lease, som etablerer OS-backed watch history **før** den første
authority-bearing start-observation. Den samme lease skal forblive levende
gennem exact runner execution, post-campaign evidence og ADR-DC-012
execution-binding og finaliseres først efter en ny Trusted-Git-observation.

Lease-sekvensen er:

1. valider exact live ADR-DC-010 admission, canonical repository og exact
   host-controlled `TrustedGitRuntime`;
2. arm Git-ref history watcher;
3. drain watcher og verificer watched-object identity;
4. observer `refs/heads/main^{commit}` med den restricted host-controlled
   read-only Git-reader;
5. drain watcher igen;
6. behold den samme live watcher gennem campaign/evidence/execution-binding;
7. ved finalisering: verificer exact ADR-DC-012 execution proof og at execution
   intervallet ligger inden for lease-intervallet;
8. drain watcher, lav en ny Trusted-Git main-observation, drain watcher igen;
9. udsted kun freeze-proof hvis alle checks er rene og begge observationer er
   exact `requested_main_sha`.

Mutation → restore er derfor stadig en revocation. Start/end-SHA-lighed er kun
et nødvendigt resultat, ikke kontinuitetsbeviset.

## Ref-storage scope

V1 understøtter kun standard Git **files** ref backend og overvåger den metadata,
der kan ændre eller omdirigere `main`:

- repository-pathens ancestry entries;
- `.git/config` og `.git/config.lock`;
- `.git/refs` og `.git/refs/heads`;
- `.git/refs/heads/main` og `main.lock`;
- `.git/packed-refs` og `packed-refs.lock`.

Følgende fejler lukket i V1:

- reftable/non-files ref storage;
- linked worktrees eller `.git` file indirection;
- `commondir`/external common Git metadata;
- symbolic `refs/heads/main`;
- watcher backend/platform uden de krævede history-semantics.

Dette er bevidst smallere end at forsøge at understøtte alle Git storage modes
med svagere garantier.

## OS history boundary

### Linux

Linux bruger `inotify` med watch-before-observe. Queue overflow, ignored watch,
unmount, parent delete/move, malformed event stream og mutation af et protected
exact child-name fejler lukket. Hvert clean-check bruger:

`history drain → current object identity → history drain`

så mutation ikke kan gemmes i et drain/stat race.

### Windows

Windows bruger overlapped `ReadDirectoryChangesW` på de relevante parent
directories. Watch loss, zero/malformed completion, API-fejl eller mutation af
et protected exact child-name fejler lukket. Watchen re-armes først efter en
fuldt valideret completion.

## Live authority, ikke reloadable state

`PhysicalCampaignMainFreezeLease` er bevidst ikke et serialiserbart authority
artifact. Live provenance bindes process-lokalt til:

- exact object identity;
- exact identity digest;
- originating PID;
- den levende OS watcher.

Forked child-processer arver ingen lease authority. Finalize eller abort
forbruger leasen og lukker watcher-håndtagene. En reconstructed dataclass kan
ikke finalisere et freeze-proof.

Det serialiserbare `PhysicalCampaignMainFreezeProof` er evidence efter en
succesfuld live transaction; deserialisering genskaber ikke watcher authority.

## Authority

Et succesfuldt proof må kun hævde:

- `runner_execution_binding_proven=true`;
- `continuous_main_freeze_proven=true`;
- authority `verified-continuous-main-freeze-only`.

Det må fortsat **ikke** hævde:

- `physical_campaign_completed`;
- `dc_l15_complete`;
- `dc_l14_independent_human_verdict`;
- `human_pilot_go_decision`;
- `pilot_go_authorized`;
- merge/publication/release/deploy/activation authority.

De resterende completion-gates er præcis:

1. `dc_l14_independent_human_verdict`
2. `human_pilot_go_decision`

## Tier-A isolation

DC-013 importeres ikke fra `kaliv_dev_control/__init__.py`. Production boundary
installeres kun ved import af den specifikke
`improvement_physical_campaign_main_freeze` facade. Dermed udvides package-root
static reachability/Tier-A closure ikke.

## Konsekvens

DC-013 kan bevise, at exact local `main` ikke blev muteret gennem det live
overvågede interval på de understøttede Git/OS backends. Det er stadig ikke et
fuldt DC-L15 completion-verdict. Independent human verdict og human pilot GO
forbliver særskilte authority-gates.

Ingen fysisk campaign, merge, publication, release, deploy eller activation
udføres af denne ADR.
