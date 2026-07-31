# Milestone 3 — offline current-main handoff

Denne builder pakker den grønne, dormante Milestone 3-kandidat fra PR #250 til kontrolleret overførsel til Windows-riggen uden en moving checkout og uden en publiceret release.

## Binding

- kandidatbranch: `agent/milestone3-current-main-v2`;
- builderbranch: `agent/milestone3-current-main-handoff-v2`;
- version: `1.58.147`;
- fysisk launcher i pakken: `START_MILESTONE3_CURRENT_MAIN.cmd`.

## Byg pakken

Checkout builderbranchen rent og kør:

```text
BUILD_MILESTONE3_CURRENT_MAIN_HANDOFF.cmd
```

Builderen kræver, at helperbranchen nedstammer fra den præcise kandidat, og at diffen kun indeholder de allowlistede handoff-/dokumentations-/testfiler. Kandidaten bygges i et detached worktree ved dens eksakte SHA.

Pakken indeholder:

- verificeret lokalt Git bundle af kandidatbranchen;
- Android debug-APK bygget fra kandidatworktree;
- Windows Compose uber-jar fra samme worktree;
- `START_HERE.cmd`, som initialiserer et nyt lokalt repository, verificerer bundlet, fetcher den eksakte branch, kontrollerer SHA og ren tree og starter current-main Milestone 3-launcheren;
- kandidatmanifest med separat kandidat- og builderidentitet;
- SHA-256 og byteantal for alle handoff-inputs;
- verificeret ZIP.

## Hård grænse

Pakken har altid:

- `physical_evidence_collected=false`;
- `published=false`;
- `production_activation=false`.

Builderen udfører ingen netværksupload, GitHub API-kald, merge, push, tag, release eller baggrundsproces. Den fysiske T-020/T-022/T-023-kampagne skal stadig køres på Windows-riggen med præcis én parret Android-enhed.
