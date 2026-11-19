# RIGDAG V1 — Kaliv V1 på 2.0.21

Kommandoerne til de syv V1-gates (ADR-SYS-001), gate for gate og i den
rækkefølge der virker. Hvert trin peger på sin autoritative vejledning; står
der noget andet dér, gælder den. Udskiftede værdier står som `<…>`.

> **Status:** samlet 19/11-2026 fra vejledningerne nedenfor. **Ikke kørt som
> helhed.** Stak-kommandolinjerne til gate 2, 3 og 8 og workerens opstart med
> dem er kørt i rig-simulatoren på windows-latest (#2437, #2438). Ingen gate er
> kørt på 2.0.21.

## Rækkefølgen og hvorfor

1. **Gate 2, 3, 8 først, på valideringsstakken.** Stakken bruger samme porte
   som appliancen (8080/8099; `Wait-PortFree` i stakken), og gate 2 genstarter
   workeren med vilje. Kørt under soaken ville det give røde prøver.
2. **Gate 5 (VoiceRig)** kan køres når som helst før manifestet.
3. **Gate 9 (soak) omkring Stage B.** Prøverne skal starte **før** Stage B's
   første forsøg og løbe mindst 6 timer; Stage B's genstarter skal ligge inde i
   vinduet ([KALIV_RECOVERY_SOAK_QUALIFICATION.md](KALIV_RECOVERY_SOAK_QUALIFICATION.md)).
   Gate 9 kræver altså en Stage B på 2.0.21-kandidaten.
4. **Gate 1 og 10 sidst**, når alle fire pins ligger fast. Gate 10 kan kun
   tages, mens hvert repos `main` stadig står på sin pin.
5. **Manifestet** til sidst.

## 0. Før alt

- Nyt PowerShell-vindue. Stakken advarer om `KALIV_*` arvet fra vinduet (#2439).
- `gh auth status` som en konto med admin på de fire repos (gate 10).
- De fire pins: `<modelrig-sha> <bodyrig-sha> <visionrig-sha> <voicerig-sha>`.
- Kandidat-checkout af ModelRig, ren, på `<modelrig-sha>`.
- `qwen3:14b` varmet op (koldload kan vælte workeren).

## 1. Gate 2 — `consciousness_live_lifecycle`

Vejledning: [consciousness-core/LIVE_LIFECYCLE_QUALIFICATION.md](consciousness-core/LIVE_LIFECYCLE_QUALIFICATION.md).

```powershell
.\scripts\start-stage-a-validation-stack.ps1 -PlannerModel qwen3:14b `
  -ValidationReport <absolut sti> -WorkerOnly `
  -EnableScheduler -SchedulerDataDir <dir> -SchedulerApprovalSecret <32+ tegn> `
  -EnableConsciousnessLifecycle
```

I et andet vindue:

```powershell
python scripts\consciousness_live_lifecycle_operator.py `
  --profile-file <filen KALIV_CONSCIOUSNESS_PROFILE_FILE peger på> `
  --swap-profile <kopi hvor kun modelkalibreringen er ændret>
```

Operatoren beder om genstarten undervejs. Ref'en (`consciousness-live-lifecycle:<sha>:<sha256>`)
står som `release_evidence_ref` i qualifierens rapport i kørslens mappe.

## 2. Gate 8 — `end_to_end_latency`

Vejledning: [KALIV_END_TO_END_LATENCY_QUALIFICATION.md](KALIV_END_TO_END_LATENCY_QUALIFICATION.md).
Stop gate 2's stak først.

```powershell
.\scripts\start-stage-a-validation-stack.ps1 -PlannerModel qwen3:14b `
  -ValidationReport <absolut sti> -WorkerOnly -EnableE2eLatency
```

```powershell
python scripts\kaliv_e2e_latency_voice_driver.py --record-seconds 5
```

Derefter qualifieren på kørslens mappe, som vejledningen viser
(`kaliv_end_to_end_latency_qualifier.py --evidence-root … --perception … --cognition … --outward …`).

## 3. Gate 3 — `visionrig_physical_perception`

Vejledninger: VisionRig `docs/PHYSICAL_QUALIFICATION.md`,
[consciousness-core/VISIONRIG_ADMISSION.md](consciousness-core/VISIONRIG_ADMISSION.md).

ModelRig-workeren med admission:

```powershell
.\scripts\start-stage-a-validation-stack.ps1 -PlannerModel qwen3:14b `
  -ValidationReport <absolut sti> -WorkerOnly -EnableVisionRigAdmission
```

Gate 3 og 8 kan køre på samme worker: giv begge switches.

I VisionRig-checkouten på `<visionrig-sha>`, én kilde:

```powershell
.\run-v1-release-gate.ps1 -QualifyKinect -KinectModelManifest <fil> -ModelRigWorkerUrl http://127.0.0.1:8099
```

(eller `-QualifyAndroid` / `-QualifyQuest`). Ref'en
(`visionrig-physical-perception:<visionrig-sha>:<sha256>`) står i
`validation\visionrig-physical-perception-latest.json`.

> **Åbent:** hvilken kilde V1 skal bevises med. Beslutningen 12/11 nævner
> "webcam på riggen"; wrapperen kender Kinect, Android (CameraX) og Quest.

## 4. Gate 5 — `voicerig_physical_acceptance`

Vejledning: VoiceRig `docs/RIG_ACCEPTANCE.md` (installation, `validate-rig.ps1`,
lyttekontrol). Til sidst i VoiceRig:

```powershell
.\complete-acceptance.ps1 -QualityPass -QualityNote "<din vurdering>"
```

`release-acceptance.json` skal have `ok: true`. Derefter i ModelRig:

```powershell
python scripts\kaliv_voicerig_physical_qualifier.py <sti til release-acceptance.json> `
  --voicerig-sha <voicerig-sha> --report validation\kaliv-voicerig-physical-latest.json
```

## 5. Gate 9 — `recovery_soak` (med Stage B)

Vejledning: [KALIV_RECOVERY_SOAK_QUALIFICATION.md](KALIV_RECOVERY_SOAK_QUALIFICATION.md);
Stage B: `STAGE_B_UPDATER_EVIDENCE.md`. Valideringsstakken skal være stoppet;
appliancen kører.

Røgprøve (trin 0 i vejledningen), så sampling i eget vindue, **før Stage B**:

```powershell
python scripts\kaliv_recovery_soak_collector.py sample
```

Loopet overlever ikke Stage B's reboot: start det igen inden for 15 minutter,
eller brug den planlagte opgave i vejledningen. Kør Stage B. Lad appliancen
køre, til der er gået mindst 6 timer fra første prøve. Så:

```powershell
python scripts\kaliv_recovery_soak_collector.py assemble `
  --stage-b-report validation\stage-b-physical-final-latest.json `
  --required-duration-seconds 21600 `
  --max-sample-gap-seconds 900

python scripts\kaliv_recovery_soak_qualification.py `
  validation\recovery-soak-observations.json `
  --stage-b-report validation\stage-b-physical-final-latest.json `
  --report validation\kaliv-recovery-soak-latest.json
```

## 6. Gate 1 — `software_exact_green`

Vejledning: [KALIV_SOFTWARE_EXACT_GREEN_QUALIFICATION.md](KALIV_SOFTWARE_EXACT_GREEN_QUALIFICATION.md).
VisionRig's exact-head kører kun ved dispatch, og kun mens pinnen er branchens head:

```powershell
gh workflow run exact-head-qualification.yml -R Ternedal/VisionRig --ref main -f head_sha=<visionrig-sha>
```

Når alle fire repos er grønne på deres pin:

```powershell
python scripts\kaliv_software_exact_green_assembler.py `
  --pin-modelrig <modelrig-sha> --pin-bodyrig <bodyrig-sha> `
  --pin-visionrig <visionrig-sha> --pin-voicerig <voicerig-sha> --out <ny mappe>
```

## 7. Gate 10 — `repository_authority`

Vejledning: [KALIV_REPOSITORY_AUTHORITY_QUALIFICATION.md](KALIV_REPOSITORY_AUTHORITY_QUALIFICATION.md).
En verdict pr. repo fra en ren `main`-checkout, mens `main` står på pinnen,
gemt uden for alle checkouts; derefter `kaliv_repository_authority_assembler.py`
som vejledningen viser.

## 8. Manifestet

Vejledning: [KALIV_SYSTEM_RELEASE_QUALIFICATION.md](KALIV_SYSTEM_RELEASE_QUALIFICATION.md#kaliv-v1---release-scope-v1)
— v1-kommandoen med de syv refs. Læg hver producers outputfil ved siden af
manifestet: den endelige gate tjekker kun ref'ens form og pin, ikke filen bag.

## Åbne punkter før rigdagen

- Kilden til gate 3 (se ovenfor).
- Gate 5 punkt 9 kræver at "ModelRig backend rapporterer VoiceRig": om det er
  appliancen eller valideringsstakken, står ikke i VoiceRig's vejledning.
- Gate 9 betyder en fuld Stage B på 2.0.21 (kilde 2.0.20) med soak omkring.
