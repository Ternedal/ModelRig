# DevControl publisher-protokoller — H10F/H10G-A

Denne oversigt er autoritativ for fil-publication i `kaliv_dev_control`.
Formålet er at holde forskellige persistenskontrakter adskilt: immutable beviser
må ikke overskrives, mens eksplicit mutable state fortsat skal kunne opdateres
under sin egen compare-and-swap- eller transaktionsprotokol.

Den maskinelle kontrakt ligger i
`devcontrol/tests/test_publisher_protocol_inventory_h10f.py`. Enhver ny eller
ændret low-level publish-primitive skal klassificeres dér og reviewes som en
sikkerhedsændring. Testen scanner kildekoden via AST; den importerer ikke
modulerne og udvider ingen runtime-authority.

## 1. Shared crash-durable create-once file publication

Følgende understøttede immutable artefakter bruger
`durable_publication.create_once_file()`:

- authenticated draft-PR readiness;
- signed physical-isolation evidence;
- publisher authorization/replay reservations, pending entries, final entries
  og recovery receipts;
- publisher dry-run request, signed request og receipt;
- authenticated recovery authorization og receipt v3;
- semantic-review request og signed verdict; og
- trusted-Git-runtime transaction reservation.

Kontrakten er no-overwrite, link-free, file-sync plus parent-directory durability
og fail-closed fejloversættelse i den offentlige domæne-API.

## 2. Shared crash-durable directory transaction

`trusted_git_runtime_staging.py` publicerer en komplet verificeret runtime-tree
med `rename_directory_no_replace()`. Reservationen er create-once, den pending
tree synkroniseres rekursivt, og final-navnet må aldrig erstatte en eksisterende
transaction. Recovery er eksplicit og schema-bundet.

## 3. Shared bounded streaming create-once publication

H10G-A introducerer `streaming_publication.publish_stream_once()` og migrerer
`_runtime_closure_common._closure_publish_exact_file()` til den fælles primitive.
`runtime_staging.TrustedRuntimeStager.stage()` beholder foreløbig sin eksisterende,
eksplicit klassificerede hardlink-protokol og migreres separat i H10G-B.

Den fælles primitive kopierer i bounded 1 MiB chunks, beregner SHA-256 og byteantal
i samme gennemløb, synkroniserer tempfilen og publicerer via hardlink uden
replacement. En concurrent winner accepteres kun gennem callerens præcise
valideringscallback. Primitive-funktionen kan synkronisere parent-directory både
for den lokale vinder og, hvor den eksisterende kontrakt kræver det, efter en
valideret concurrent winner.

Runtime closure ejer fortsat single-link-, hash-, size- og platform-mode-
invarianterne. Der bufferes aldrig en runtime på op til 512 MiB i hukommelsen.

For H10G-A må kun `streaming_publication.py` og den endnu ikke migrerede
`runtime_staging.py` kalde `tempfile.mkstemp()` og `os.link()` for understøttet
streaming-publication. Runtime closure må kun kalde `publish_stream_once()` og
må ikke indeholde `mkstemp`, `os.link` eller replace-publication. H10G-B fjerner
den sidste direkte low-level caller.

## 4. Bevidst mutable compare-and-swap state

`store.CampaignStore.save()` er ikke et immutable evidensartefakt. Den erstatter
én campaign-record under eksklusiv lås efter at have verificeret exact previous
event hash og én gyldig append. Dens `NamedTemporaryFile` plus
`temporary.replace(path)` er derfor en eksplicit mutable CAS-protokol og må ikke
konverteres til create-once uden at ændre campaign-modellen.

## 5. Ephemeral scratch, ikke publication

`patch.WorkspacePatchApplier.apply()` bruger `NamedTemporaryFile` som bounded
scratch-input til den kontrollerede patch-anvendelse. Tempfilen er ikke et
vedvarende artefakt eller en authority receipt.

## 6. Fysisk isoleret v1-kompatibilitet

De historiske writers i
`_compatibility_v1/local_candidate_materialization.py` og
`_compatibility_v1/publisher_authorization.py` beholder deres gamle
`mkstemp()` plus `os.replace()`-adfærd alene for retained v1-evidence.
De er ikke den understøttede offentlige authority-flade. Nye imports, nye
call-sites eller kopiering af deres protokol uden for compatibility-pakken er
forbudt af inventory-kontrakten.

## Invariants

- Ingen understøttet immutable JSON/evidence-writer må bruge replace-publication.
- Nye `mkstemp`, `NamedTemporaryFile`, `os.link`, `os.replace`,
  `create_once_file`, `publish_stream_once` eller
  `rename_directory_no_replace` call-sites kræver en eksplicit
  inventory-opdatering og sikkerhedsreview.
- `os.replace()` er kun tilladt i de to retained v1-moduler.
- Den eneste understøttede mutable replace-state er campaign-store CAS.
- H10G-A har ét fælles low-level implementation point for runtime closure og én
  eksplicit klassificeret resterende runtime-staging-implementation.
- H10G-A tilføjer ingen credential, token, signer, Git-kommando, remote, socket,
  HTTP-klient, GitHub-writer, push, PR-mutation, reviewer-request, merge,
  release, settings-, deployment- eller production-authority.
