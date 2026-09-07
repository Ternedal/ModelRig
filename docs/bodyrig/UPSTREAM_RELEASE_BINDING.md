# BodyRig upstream physical-release binding — ModelRig #704

Denne gate løser kun **reference/binding-delen** af ModelRig #704. Den gør det
muligt at tage BodyRigs endelige fysiske release-receipt og binde den til de
præcise `.mrbody`-bytes, som ModelRig faktisk har installeret.

Den aktiverer ikke BodyRig i ModelRig.

`production_activation=false`.

## Forudsætning

BodyRig skal først have kørt sin egen canonical fysiske kæde færdig og have
skrevet en create-only:

```text
bodyrig-release-acceptance.json
```

Receiptet skal være `bodyrig-release-acceptance` version 2 med:

- `release_gate_pass=true`;
- `production_activation=true` **på BodyRig-siden**;
- production-valid `stash-sith-high-fidelity` physical clone;
- `skin_qa_assessment=low-risk`;
- machine-quality PASS på både WindowsPlayer og Quest-class hardware;
- identisk runtime/avatar/bodyprint authority på begge platforme.

ModelRig accepterer ikke et tidligere Gate A-, fixture-, Windows-only- eller
machine-partial receipt som upstream production authority.

## Binding på riggen

Kør fra den exact clean ModelRig-candidate, der skal eje bindingen. BodyRig skal
ligge i sin egen exact clean checkout på den revision, som release-receiptet
navngiver.

```powershell
python .\scripts\bodyrig_bind_upstream_release.py `
  --bodyrig-release "C:\path\to\acceptance\bodyrig-release-acceptance.json" `
  --bodyrig-repo "C:\path\to\BodyRig" `
  --store $env:KALIV_BODY_STORE `
  --output "C:\path\to\modelrig-evidence\bodyrig-upstream-release-binding.json"
```

Outputfilen skal ikke eksistere i forvejen. Den er create-only.

## Hvad gaten verificerer

- upstream receiptets exact schema og feltmængde;
- BodyRig exact clean Git HEAD matcher `bodyrig_revision` i receiptet;
- BodyRig `origin` er `Ternedal/BodyRig`;
- ModelRig checkout er exact clean og `origin` er `Ternedal/ModelRig`;
- upstream `body_id` findes i ModelRigs profile store;
- den installerede `.mrbody` revalideres gennem `MRBodyProfileStore.load()`;
- installeret package SHA-256 er byte-identisk med BodyRigs accepterede package;
- Windows + Quest receipts er begge machine-quality PASS;
- runtime manifest, avatar, BodyPrint, renderer og Unity authority er coherent
  på tværs af Windows/Quest;
- upstream release-receiptets egne bytes SHA-256-bindes ind i ModelRig-receiptet.

## Privacy / authority boundary

ModelRig-bindingen serialiserer kun revisions-, body-, package- og
proof-digests. Den serialiserer ikke:

- Stash URL eller API-key;
- lokale video/source paths;
- private segmenter eller raw frames;
- 4D-Humans/PHALP/SiTH model paths;
- BodyRig eller ModelRig checkout paths;
- device bearer token eller andre credentials.

Den endelige ModelRig-binding har derfor fortsat:

```json
"production_activation": false
```

BodyRigs `production_activation=true` er **upstream evidence**, ikke en
ModelRig feature-toggle. ModelRig #704/#846 og den fysiske Windows/Android/Kaliv
integration skal stadig bestå deres egne gates før nogen ModelRig-aktivering.

## Software-proof

`tests/bodyrig/upstream_release_binding.py` sabotage-tester mindst:

- package mismatch;
- upstream receipt uden final production PASS;
- Windows/Quest runtime-byte drift;
- manglende Quest-proof;
- schema/unknown-field drift, inklusive private-looking felter;
- ModelRig binding forbliver non-activating;
- installed `.mrbody` bliver revalideret;
- output hashbinder upstream receiptet og er create-only.

Den dedikerede `bodyrig-renderer-contract` workflow kører både kontrakttesten og
CLI-surface-checket på exact PR-head.
