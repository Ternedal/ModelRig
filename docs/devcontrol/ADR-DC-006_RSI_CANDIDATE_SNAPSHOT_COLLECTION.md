# ADR-DC-006 — Read-only RSI candidate snapshot collection

**Dato: 12/09-2026. Status: foreslået til beslutning.**

## Kontekst

ADR-DC-005 definerer en ren proof-kerne, der kan binde et komplet candidate-tree til workerens målte `code_sha256`. Proof-kernen udfører med vilje ingen filesystem-I/O og ingen Git-processer. Der mangler derfor et kontrolleret led, som kan hente de faktiske tracked bytes fra DC-L13's local-only bare candidate-repository.

Dette ADR beskriver kun collection af evidens. Det ændrer ikke ADR-DC-001's terminale menneskelige authority og giver ingen ny udviklings-, publikations- eller aktiveringsret.

## Beslutning 1 — DC-L13 skal genverificeres før og efter collection

Collectorens produktionsentrypoint accepterer den eksisterende `LocalCandidateMaterializationReceipt`, den tilhørende `DevelopmentTask` samt de eksisterende authorization/publisher/semantic verifiers.

Før første objektlæsning kaldes `verify_local_candidate_materialization(...)` mod exact control-plane, source repository, materialization root og trusted Git runtime.

Efter sidste objektlæsning verificeres både trusted Git runtime og materialization receipt igen. Collection må ikke gøre et stale eller flyttet candidate-tree gyldigt.

## Beslutning 2 — Kun staged TrustedGitRuntime må læse Git-objekter

Collector må ikke bruge hostens implicitte `git` fra PATH. Den opretter en separat scratch-operation og bruger `TrustedGitRunner` med den allerede staged og verificerede Git runtime.

Tilladte Git-operationer i dette slice er read-only:

- `rev-parse <commit>^{commit}`;
- `rev-parse <commit>^{tree}`;
- `ls-tree -r -z --full-tree <commit>`;
- `cat-file -s <blob>`;
- `cat-file blob <blob>`.

Der udføres ingen checkout, fetch, ref update, push, remote transport, config mutation, merge eller publication.

## Beslutning 3 — Metadata før payload og eksplicitte budgets

Før blob-bytes læses indsamles filantal og blob-størrelser. Collector håndhæver:

- maksimum antal tracked filer;
- maksimum bytes pr. blob;
- maksimum samlede snapshot-bytes.

En overskridelse stopper før blob-payloads læses, hvor det er muligt. Første defaults er 20.000 filer, 128 MiB pr. fil og 512 MiB samlet, med hårde kontraktmaksima på 100.000 filer, 256 MiB pr. fil og 2 GiB samlet.

## Beslutning 4 — Gitlinks/submodules fejler lukket

Første slice accepterer kun Git blob modes `100644`, `100755` og `120000`. `160000 commit`/gitlinks afvises i stedet for at blive behandlet som almindelige filer eller fulgt rekursivt.

Symlinks indgår som deres Git blob bytes i exact root-tree snapshot. ADR-DC-005's proof-kern afviser fortsat en `worker/app/**/*.py` symlink, fordi Git blobben indeholder linkmålet, mens workerens runtime-fingerprint ellers ville læse resolved bytes.

## Beslutning 5 — Hver blob bindes før receipt

For hver listed blob:

1. `cat-file -s` skal være inden for budget;
2. den læste payload skal have præcis den annoncerede størrelse;
3. Git blob SHA-1 reproduceres fra payloaden og skal matche objekt-ID'et;
4. payloadens SHA-256 gemmes i snapshot-manifestet.

Efter alle blobs reproduceres candidate root-tree SHA igen gennem ADR-DC-005's tree-hasher og skal matche materialization receiptens candidate tree.

## Beslutning 6 — Collector receipt er ikke authority

`kaliv-rsi-candidate-snapshot-receipt/v1` binder:

- materialization receipt SHA-256;
- task SHA-256;
- candidate commit/tree;
- file count og total bytes;
- manifest SHA-256;
- trusted Git runtime manifest SHA-256;
- trusted Git executable SHA-256.

Receipt har altid:

- `network_performed = false`;
- `repository_mutated = false`;
- `authority = evidence-only`;
- `merge_authority = human`.

## Beslutning 7 — Collector scratch er separat fra materialization transaction

TrustedGitRunner må bruge sin normale isolerede HOME/config/temp struktur, men den skal placeres i en separat caller-supplied collector root uden for DC-L13 materialization transaction. Scratch fjernes efter collection. Candidate-repository og receipt-filer ændres ikke.

## Obligatoriske kontrakttests

1. Happy path returnerer exact candidate bytes og receipt med commit/tree/count/bytes.
2. Receipt er offline, read-only, evidence-only og human-merged.
3. Gitlinks/submodules afvises.
4. File-count budget afvises før payload collection.
5. Per-file og aggregate byte budgets afvises før payload collection.
6. Blob-byteændring mellem size og read opdages via størrelse eller Git blob-ID.
7. Candidate root-tree kan ikke ændres mellem materialization og collection.
8. Truncated/non-NUL `ls-tree` output afvises.
9. Collection-kernen bruger en reader-interface, mens produktionsadapteren er fast bundet til `TrustedGitRunner` og DC-L13 reverification.

## Konsekvenser

**Positivt:** RSI-kæden kan nu hente den exact tracked source, som ADR-DC-005 kræver, uden at give improvement-laget remote Git eller repository-mutation. Det gør provenance-leddet fysisk anvendeligt mod DC-L13's lokale candidate.

**Begrænsning:** Dette slice starter ikke candidate runtime eller Agent 3-evalen. End-to-end orkestrering af `collect → run candidate eval → regression proof → runtime provenance` er fortsat et separat, menneske-initieret pilottrin og må ikke blive en unattended cadence i denne ADR.
