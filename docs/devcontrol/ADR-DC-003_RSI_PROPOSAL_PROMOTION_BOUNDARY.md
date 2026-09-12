# ADR-DC-003 — Signeret promotion fra RSI-forslag til DevelopmentTask

**Dato: 12/09-2026. Status: foreslået til beslutning.**

## Kontekst

ADR-DC-002 afgrænser et modelgenereret `ImprovementProposal` som et ikke-autoriserende forslag bundet til konkret eval-evidens. Det næste RSI-led skal kunne omsætte et accepteret forslag til en rigtig `DevelopmentTask` uden at lade modellen tildele sig selv scope, kommandoer, budget eller anden DevControl-authority.

Dette ADR-udkast beskriver kun **proposal → menneskeligt autoriseret DevelopmentTask**. Det starter ingen udviklingskampagne og ændrer ikke ADR-DC-001's terminale menneskelige merge-/release-/deploy-/activation-authority.

## Beslutning 1 — Promotion er en separat authority-grænse

Der findes ingen implicit eller automatisk cast fra `kaliv-rsi-improvement-proposal/v1` til `kaliv-development-task/v1`.

Promotion kræver et separat `kaliv-rsi-promotion-authorization/v1` artifact. Artifactet skal indeholde hele den autoriserende `DevelopmentTask`, inklusive:

- `allowed_paths`;
- `protected_paths`;
- `allowed_command_ids`;
- `required_tests`;
- budget;
- risk;
- acceptance criteria;
- `merge_authority=human`.

Ingen af disse felter må defaultes fra modellens `suggested_paths` eller `suggested_tests`.

## Beslutning 2 — Human authority skal være kryptografisk verificerbar

Et promotion-authorization artifact er ikke autoriserende alene, fordi nogen har skrevet `approved=true` i JSON.

Artifactets præcise kanoniske bytes skal være signeret gennem ModelRigs eksisterende verification-only Ed25519 authority. Runtime må fortsat kun modtage pinned public keys, keyring epoch, revocation state og detached signatures. Private signing keys, signere og credential-loaders forbliver uden for DevControl-runtime.

RSI-promotion accepterer kun signaturer fra authority-systemet `modelrig-rsi-human-review`. Et andet ellers gyldigt authority-system kan ikke bruges som RSI-human-approval.

## Beslutning 3 — Authorization skal være bundet til ét præcist proposal

Authorization skal binde:

- `proposal_id`;
- SHA-256 af proposalets kanoniske JSON;
- repository;
- exact 40-hex `base_sha`;
- hele DevelopmentTask-payloaden;
- proposalets `required_evals`.

Ændres scope, budget, commands, task eller proposal efter signering, skal verifikation fejle lukket.

## Beslutning 4 — Promotion må ikke svække evidenskrav

Promotion må gerne gøre en task mere restriktiv eller kræve ekstra tests, men må ikke:

- fjerne proposalets acceptance criteria;
- fjerne eller ændre proposalets `required_evals`;
- nedklassificere proposalets risk.

Dermed kan et menneskeligt review skærpe en opgave uden at viske den målbare forbedringshypotese væk.

## Beslutning 5 — Promotion producerer provenance, ikke execution

En godkendt promotion producerer:

1. den almindelige, eksisterende `DevelopmentTask`;
2. et `kaliv-rsi-promotion-receipt/v1` artifact, som binder proposal-hash, authorization-hash, detached-signature-hash og task-hash samt reviewer-identitet og verification-tidspunkt.

Promotion-funktionen må ikke:

- persistere eller starte tasken;
- oprette workspace;
- køre commands eller subprocesser;
- skrive patches;
- oprette commits/branches/PR'er;
- kalde Git/GitHub write-paths;
- merge, release, deploye eller aktivere noget.

Den returnerede DevelopmentTask skal efterfølgende gå gennem den eksisterende DevControl-kæde.

## Beslutning 6 — Human trust root er eksplicit

At en Ed25519-key repræsenterer en menneskelig reviewer er et trust-root-spørgsmål i keyring-provisioneringen. Runtime udleder ikke "human" fra et frit tekstfelt; den verificerer kun trusted key identity, issuer actor, issuer system, epoch, validity og revocation gennem den eksisterende asymmetric-authority boundary.

En senere operationalisering skal derfor have en særskilt procedure for at provisionere/rotere `modelrig-rsi-human-review` keys. Denne slice opfinder ikke en privat-key-management-løsning.

## Beslutning 7 — Ingen unattended RSI-loop endnu

Selv efter succesfuld promotion er der ingen controller, som automatisk starter tasken eller fortsætter til patch/review/publication.

Næste selvstændige RSI-led efter dette ADR er kandidatmåling: **candidate-vs-incumbent regression proof** med samme evalfamilie og et eksplicit forbedringskriterium. Først når den måling eksisterer, giver det mening at diskutere kontrolleret iteration over proposal → candidate → eval.

## Obligatoriske kontrakttests

1. Proposalets `suggested_paths` bliver aldrig implicit `allowed_paths`.
2. Authorization er bundet til exact proposal-hash, repository og base SHA.
3. Hele DevelopmentTask-authority ligger inde i de signerede authorization-bytes.
4. Scopeændring efter signering gør signaturen ugyldig.
5. En signatur fra et andet authority-system afvises.
6. Proposalets required evals kan ikke droppes eller udskiftes.
7. Proposalets acceptance criteria kan ikke droppes.
8. Risk kan ikke nedgraderes under promotion.
9. Promotion receipt binder proposal, authorization, signature og task kryptografisk.
10. Promotion starter ingen task, subprocess, netværksmutation eller Git-operation.

## Konsekvenser

**Positivt:** ModelRig får et reelt, teknisk adskilt RSI-led fra modelhypotese til bounded udviklingsopgave. Modellen kan foreslå, men authority kommer fra en separat, verificerbar menneskelig trust root.

**Begrænsning:** Der kræves fortsat et eksternt signing/review-step, og en promoted task kører ikke automatisk. Det er tilsigtet. Denne slice øger RSI-sammenhængen uden at gøre systemet selvautoriserende.
