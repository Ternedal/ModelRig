# BodyRig AR placement — Slice D

Denne slice er AR-halvdelen af BodyRig Unity-rendererens aktuelle Android-stack.
Den er stablet på live-frame/RigLink/Android-host-sporet (#1930→#1940) og ændrer
ikke BodyRig wire-kontrakten eller production authority.

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

1. **AR Foundation 6.3.5** og **Google ARCore XR Plugin 6.3.5** er
   repository-pinnet i `Packages/manifest.json` og `packages-lock.json`.
   Det er Unity 6000.3's released package-line; ændr ikke versionerne manuelt i
   Package Manager uden at opdatere lock + `tests/bodyrig/ar_packages_contract.py`.
2. Android batch-buildet aktiverer `ARCoreLoader` programmatisk gennem
   midlertidige XR Management-subassets. Eksisterende XR-settings overskrives
   aldrig; findes de uden ARCore, fejler buildet lukket.
3. Player Settings er repository-pinnet til ARM64, minSdk 28 og
   `BODYRIG_AR` for Android. De værdier skal ikke klikkes ind manuelt.
4. Den genererede tomme build-scene bootstrapper nu selv `ARSession`,
   `ARInputManager`, `XROrigin`, tracked AR-kamera (`ARCameraManager` +
   `ARCameraBackground` + Input System `TrackedPoseDriver`), `ARPlaneManager`
   og `ARRaycastManager`. Plane detection pinner horizontal + vertical, og den
   konkrete raycast-manager gives direkte til placement-komponenten.

## Software-proof vs. fysisk proof

`tests/bodyrig/ar_placement_contract.py` beviser softwaregrænserne og køres
eksplicit af BodyRig renderer-workflowet på exact PR-head. Den ligger under den
renderer-specifikke testsuite og ændrer derfor ikke repoets genererede top-level
test-inventory i `CURRENT_STATE.md`. Det er **ikke** et Android-build eller et
fysisk AR-bevis.

Fysisk acceptance kræver stadig, på samme exact candidate head:

- Android host-build/install/launch receipt (#1939-sporet);
- token-sikker intent RigLink receipt (#1940-sporet), hvis live rig anvendes;
- ARCore runtime readiness på den fysiske enhed;
- rigtig VRM load og live frames fra riggen;
- tap på et detekteret plan;
- direkte observation af at avatarens placering ikke stopper blink, gaze,
  speech-mouth, gesture eller interruption;
- separat evidence/acceptance-gate. CI eller screenshots alene må ikke erstatte
  det.

Runtime-bootstrapen ændrer ingen release- eller production authority.
