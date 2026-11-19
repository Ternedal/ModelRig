# RIGDAG V1 — Kaliv V1 på 2.0.21

Kommandoerne til de syv V1-gates (ADR-SYS-001), gate for gate og i den
rækkefølge der virker. Hvert trin peger på sin autoritative vejledning; står
der noget andet dér, gælder den. Udskiftede værdier står som `<…>`.

> **Status:** samlet 19/11-2026, gate 3's webcam-vej tilføjet samme aften fra vejledningerne nedenfor. **Ikke kørt som
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
4. **Gate 10 tidligt, så snart hver pin står.** En verdict kan kun tages,
   mens det repos `main` stadig står på pinnen. For **ModelRig betyder det lige
   efter merge af bump-PR'en, før noget andet lander**: meld landingspausen på
   #2275 først. BodyRig, VisionRig og VoiceRig, så snart deres pins er valgt.
   Selve assembleren kan køres senere.
5. **Gate 1 sidst**, når alle fire pins har grøn exact-head.
6. **Manifestet** til sidst.

## 0. Før alt

- Nyt PowerShell-vindue. Stakken advarer om `KALIV_*` arvet fra vinduet (#2439).
- `gh auth status` som en konto med admin på de fire repos (gate 10).
- De fire pins: `<modelrig-sha> <bodyrig-sha> <visionrig-sha> <voicerig-sha>`.
- Kandidat-checkout af ModelRig, ren, på `<modelrig-sha>`.
- `qwen3:14b` varmet op (koldload kan vælte workeren).

## 1. Gate 2 — `consciousness_live_lifecycle`

Vejledning: [consciousness-core/LIVE_LIFECYCLE_QUALIFICATION.md](consciousness-core/LIVE_LIFECYCLE_QUALIFICATION.md).

**Forudsætning:** en SelfState og en valgt, godkendt Person Revision i
workerens datarod. Findes de ikke, så fra `worker/` med samme miljø som
workeren (vejledningen, "prerequisites"):

```powershell
python -m app.consciousness_core.dev_bootstrap
```

Operatorens preflight stopper med en `readiness_gaps`-liste, hvis noget mangler.

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

VisionRig-kernen skal køre på loopback med ModelRig-broen slået til
(VisionRig `docs/PHYSICAL_QUALIFICATION.md`, "Prerequisites"):

```text
VISIONRIG_MODELRIG_BRIDGE=1
VISIONRIG_MODELRIG_WORKER_URL=http://127.0.0.1:8099
```

**Kilde: riggens webcam** (beslutning 12/11). Kræver VisionRig `07c47ca8`
eller nyere (#206, `-QualifySourceId`). I VisionRig-checkouten på
`<visionrig-sha>`:

Vindue 1 — produceren. Den skal køre hele tiden og have leveret frames, før
kvalifikationen starter; luk den ikke undervejs:

```powershell
visionrig-producer --camera 0 --source-id windows-webcam --fps 5
```

Vindue 2 — kvalifikationen:

```powershell
.\run-v1-release-gate.ps1 -QualifySourceId windows-webcam
```

Ref'en (`visionrig-physical-perception:<visionrig-sha>:<sha256>`) står som
`release_evidence_ref` i `validation\visionrig-windows-webcam-physical.json`.
(Kinect, Android og Quest findes stadig: `-QualifyKinect`, `-QualifyAndroid`,
`-QualifyQuest`.)

**Evidens — hvad der er bevist, og hvad der ikke er:**

| | Status |
|---|---|
| `-QualifySourceId` afviser ugyldige og gentagne id'er før noget kører (CI, Windows PowerShell 5.1) | bevist i CI |
| Wrapperen kører under Windows PowerShell 5.1 (`-StatusOnly`) | bevist i CI |
| Fysisk webcam-kvalifikation: rigtigt kamera → frames → ModelRig-admission → PASS | **ikke kørt** |

Grøn CI er ikke gate 3. Gate 3 er kun bestået, når wrapperen er endt uden
fejl og rapporten har en `release_evidence_ref` på den valgte VisionRig-SHA.
Fejler eller afbrydes kvalifikationen, mangler rapporten, eller mangler ref'en,
**er gate 3 ikke bestået** og må ikke meldes som PASS; ret årsagen og kør den
igen. Brug aldrig en ref fra en tidligere kørsel eller en anden SHA.

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
**Tages når pinnen står, ikke her** (se rækkefølgen): ModelRig lige efter
bump-mergen under landingspause, de tre andre når deres pins er valgt. En
verdict pr. repo fra en ren `main`-checkout, gemt uden for alle checkouts.

**VisionRig-pinnen til 2.0.21 skal være `07c47ca8` eller nyere** (ellers
mangler `-QualifySourceId` til gate 3). VisionRig-verdicten skal være taget på
præcis den pin, der står i manifestet; en verdict fra en anden VisionRig-SHA
gælder ikke. Det samme gælder gate 3's ref og gate 1.
Her til sidst kører du kun `kaliv_repository_authority_assembler.py` på de
fire gemte verdicts, som vejledningen viser.

## 8. Manifestet

Vejledning: [KALIV_SYSTEM_RELEASE_QUALIFICATION.md](KALIV_SYSTEM_RELEASE_QUALIFICATION.md#kaliv-v1---release-scope-v1)
— v1-kommandoen med de syv refs. Læg hver producers outputfil ved siden af
manifestet: den endelige gate tjekker kun ref'ens form og pin, ikke filen bag.

## Åbne punkter før rigdagen

- Gate 3's fysiske webcam-kvalifikation er ikke kørt (se evidens-tabellen i
  afsnit 3).
- Gate 5 punkt 9 kræver at "ModelRig backend rapporterer VoiceRig": om det er
  appliancen eller valideringsstakken, står ikke i VoiceRig's vejledning.
- Gate 9 betyder en fuld Stage B på 2.0.21 med soak omkring. **Kilden er den
  signerede 2.0.12**, ikke 2.0.20: `stage_b_one_click_v2.py` kræver backend og
  worker på præcis 2.0.12 (`EXPECTED_SOURCE_VERSION`), og
  `STAGE_B_UPDATER_EVIDENCE.md` kræver overgangen 2.0.12 → 2.0.21. Appliancen
  skal altså stå på 2.0.12, før soak-prøverne startes.
