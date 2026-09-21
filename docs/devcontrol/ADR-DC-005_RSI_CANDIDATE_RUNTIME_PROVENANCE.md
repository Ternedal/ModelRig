# ADR-DC-005 — RSI candidate runtime provenance

**Dato: 12/09-2026. Status: foreslået til beslutning.**

## Kontekst

ADR-DC-004 kan bevise, at et candidate-eval slår den incumbent-evidens, som udløste et RSI-proposal. Det lag holder med vilje Git-identitet og den målte `backend.code_sha256` adskilt, fordi Agent 3-evalen ikke selv attesterer hvilket Git-tree worker-koden kom fra.

DevControl DC-L13 kan omvendt materialisere en exact local-only candidate commit og et exact Git root tree, men den receipt siger ikke, at et senere eval faktisk kørte worker-koden fra netop det tree.

Uden et eksplicit bridge-led kan man derfor have to hver for sig gyldige udsagn — “denne Git-candidate blev materialiseret” og “denne runtime blev målt” — uden kryptografisk bevis for, at de beskriver samme worker-kode.

## Beslutning 1 — Provenance er evidence-only

Bridge-artifactet bruger schema `kaliv-rsi-candidate-runtime-provenance/v1` og har altid:

- `authority = evidence-only`;
- `merge_authority = human`;
- `accepted_regression = true`.

Det kan ikke starte en DevelopmentTask, skrive patches, kalde Git/GitHub write, publicere, merge, release, deploye eller aktivere noget.

## Beslutning 2 — Materialization er Git-ankeret

Et verified `LocalCandidateMaterializationReceipt` leverer:

- receipt SHA-256;
- task SHA-256;
- candidate commit SHA;
- candidate root-tree SHA.

Bridge-laget accepterer kun den eksisterende local-only materialization boundary: bare repository, isolated index, ingen remote/network/push/PR/merge/release/deploy og human merge authority.

## Beslutning 3 — Hele candidate-treeet skal reproduceres

Et caller-supplied snapshot er ikke en løs filliste. Bridge-laget reproducerer Git blob- og tree-object IDs fra snapshot-bytes og kræver, at den beregnede root-tree SHA er identisk med materialization receiptens candidate tree.

Dermed kan en manglende, ekstra eller ændret tracked fil ikke skjules ved kun at levere worker-filerne. Et ufuldstændigt snapshot producerer et andet root tree og fejler lukket.

Første slice understøtter normale filer, executable files og symlinks som Git-tree entries. Gitlinks/submodules er ikke en implicit fallback; de skal have en separat eksplicit kontrakt, hvis de nogensinde bliver relevante.

## Beslutning 4 — Worker fingerprint skal matche runtime-algoritmen

For `worker/app/**/*.py` anvendes samme semantik som `worker/app/build_identity.py`:

- sortering på repository-relativ worker-path;
- path + NUL + SHA-256(content) indgår i fingerprintet;
- CRLF og lone CR normaliseres til LF;
- `__pycache__` ignoreres;
- `_build_stamp.py` ignoreres, så stemplet ikke rekursivt ændrer identiteten.

Git-tree identiteten forbliver byte-exact. EOL-normalisering gælder kun worker runtime-fingerprintet, ikke Git root-treeet.

## Beslutning 5 — Eval og regression-proof bindes exact

Candidate eval-payloadens canonical SHA-256 skal være præcis `candidate_eval_sha256` i det allerede accepterede `CandidateRegressionProof`.

Evalens `backend.code_sha256` skal samtidig være identisk med:

1. fingerprintet beregnet fra det materialiserede candidate-tree;
2. `candidate_code_sha256` i regression-proofet.

Et nyt eval med samme model/code-label men andre payload-bytes kan derfor ikke substitueres bagefter.

## Beslutning 6 — Task-chain må ikke skiftes

Materialization receiptens `task_sha256` skal være identisk med regression-proofets `task_sha256`. En materialisering fra en anden DevelopmentTask kan ikke hægtes på et ellers grønt regression-proof.

## Beslutning 7 — Snapshot collection er separat fra proof construction

Dette slice udfører ingen filesystem-I/O og ingen Git-processer. Det validerer bytes, som en separat read-only collector leverer.

Det er bevidst: proof-kernen skal være deterministisk og side-effect-free. En senere collector kan læse den local-only bare repository gennem den eksisterende trusted-Git boundary, men collectorens I/O-authority skal ikke snige sig ind i selve provenance-kontrakten.

## Obligatoriske kontrakttests

1. Et komplet snapshot reproducerer exact candidate root-tree SHA.
2. En ændring uden for `worker/app` ændrer Git-treeet og afvises, selv om worker-fingerprintet er uændret.
3. En worker-kodeændring kan ikke genbruge et eval fra den gamle worker-fingerprint.
4. CRLF/LF giver samme worker runtime-fingerprint men forskellige Git-tree IDs.
5. Et eval-payload med samme `code_sha256` men anden canonical digest afvises.
6. Et rejected regression-proof kan ikke ophøjes af provenance-laget.
7. En anden task SHA afvises.
8. Arbitrære objekter kan ikke udgive sig for at være en `LocalCandidateMaterializationReceipt` i receipt-adapteren.
9. Output er altid evidence-only og human-merged.

## Konsekvenser

**Positivt:** RSI-kæden kan nu kryptografisk følge den kode, DevControl materialiserede, frem til den runtime-fingerprint som candidate-evalen målte. Det lukker den vigtigste provenance-kløft mellem DC-L13 og eval/regression-laget uden at give systemet mere authority.

**Begrænsning:** Dette slice indsamler ikke selv snapshot-bytes fra den bare candidate-repository. En trusted, read-only collector er stadig nødvendig for en end-to-end fysisk kørsel. Den collector må ikke tilføje remote Git, credentials eller mutation.
