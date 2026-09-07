# BodyRig AR placement — Slice D

Denne draft er AR-halvdelen af BodyRig Unity-rendererens Slice D. Den er stablet
på den levende frame-kilde i #846 og ændrer ikke BodyRig wire-kontrakten,
renderer-semantikken eller production authority.

`production_activation=false`.

## Grænsen

`BodyRigArPlacement` flytter kun den **indlæste VRM-instans' root transform**.
Den må aldrig flytte eller deaktivere controller-GameObject'et, som ejer loader,
renderer, frame source og AR-placement-komponenten selv.

Det betyder:

- controller-roden forbliver aktiv under hele sessionen;
- avatar-childen skjules efter succesfuldt VRM-load/bind;
- brugeren vælger et fundet AR-plan med et eksplicit tap;
- et tap, der kommer mens VRM'en stadig loader asynkront, gemmes og anvendes
  først når den rigtige avatar-root findes;
- avatar-childen bliver først synlig efter en gyldig placering;
- placering rører ingen bones, expressions, BodyCue-felter eller render frames.

`BodyRigVrmLoader` afleverer `instance.transform` til placement-komponenten først
efter `renderer.Bind(...)` har resulteret i `renderer.IsBound == true`.

## Android/AR build-forudsætninger

AR-koden kompileres kun når scripting define `BODYRIG_AR` er sat. Uden det
forbliver den fysisk beviste Windows-sti uden AR Foundation-afhængighed.

På riggen, i Unity `6000.3.21f1`:

1. Installer **AR Foundation** og **Google ARCore XR Plugin** gennem Package
   Manager. Brug de kompatible versioner Unity Package Manager tilbyder til det
   installerede editor-/package-set; denne draft pinner ikke en uprøvet version
   i `manifest.json`.
2. Project Settings -> XR Plug-in Management -> Android -> aktiver ARCore.
3. Player Settings -> Android: ARM64, IL2CPP og minimum API 24 eller højere.
4. Player Settings -> Scripting Define Symbols (Android) -> tilføj
   `BODYRIG_AR`.
5. Scenen skal indeholde `AR Session`, `XR Origin (AR)`, `ARRaycastManager` og
   `ARPlaneManager`. Placement-komponenten finder raycast-manageren i scenen.

## Software-proof vs. fysisk proof

`tests/bodyrig/ar_placement_contract.py` beviser softwaregrænserne og køres
eksplicit af BodyRig renderer-workflowet på exact PR-head. Den ligger under den
renderer-specifikke testsuite og ændrer derfor ikke repoets genererede top-level
test-inventory i `CURRENT_STATE.md`. Det er **ikke** et Android-build eller et
fysisk AR-bevis.

Fysisk acceptance kræver senere, på samme exact candidate head:

- rigtig Android-build med ARCore;
- rigtig VRM load og live frames fra riggen;
- tap på et detekteret plan;
- direkte observation af at avatarens placering ikke stopper blink, gaze,
  speech-mouth, gesture eller interruption;
- separat evidence/acceptance-gate. CI eller screenshots alene må ikke erstatte
  det.

#846's live physical-proof freeze og dens authority ændres ikke af denne draft.
