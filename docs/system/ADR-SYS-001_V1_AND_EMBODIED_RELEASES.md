# ADR-SYS-001: V1 og Kaliv Embodied som to releases

**Status:** VEDTAGET af Anders 12-11-2026 ("vedtag ADR'en").
**Udkast:** skrevet af Claude 12-11-2026 som afgørelse B i #2373.
**Serie:** første dokument i en SYS-serie for beslutninger, der går på tværs af de fire repositories.
**Stopreglen (A4-005) er overholdt:** dette dokument landes FØR den kode, det beskriver.

---

## 1. Kontekst

`docs/KALIV_SYSTEM_RELEASE_QUALIFICATION.md` definerer én systemrelease med ti gates. `scripts/kaliv_system_release_gate.py` kræver alle ti som `PASS` på samme pin-sæt (`REQUIRED_GATES`).

Tilstand 12/11-2026:

- Én gate er bestået: `software_exact_green`, på pins fra 9/10. Alle fire repositories er flyttet siden.
- Seks gates kræver en rigdag eller en administrator, og kan lukkes, når de bliver kørt: `consciousness_live_lifecycle`, `visionrig_physical_perception`, `voicerig_physical_acceptance`, `end_to_end_latency`, `recovery_soak`, `repository_authority`.
- Tre gates afhænger af, at en fotoreal klon af en rigtig person bliver menneskeligt accepteret: `bodyrig_photoreal_likeness`, `bodyrig_digital_twin_m6`, `bodyrig_android_live_body`. En klonkørsel tager ca. 7 døgn, og BodyRig #817 har endnu ingen accepteret lighed.

Så længe alle ti hænger sammen, kan intet i Kaliv kaldes færdigt, før BodyRig er i mål. BodyRig har ingen dato.

**Det egentlige spørgsmål er:**

> Er en Kaliv, der tænker, husker, ser og taler, men endnu ikke har en fotoreal krop, en release?

## 2. Beslutninger

**D1. To navngivne releases.** "Kaliv V1" og "Kaliv Embodied". Hver har sit eget manifest og sin egen gate-kørsel.

**D2. V1 kræver syv gates.** `software_exact_green`, `consciousness_live_lifecycle`, `visionrig_physical_perception`, `voicerig_physical_acceptance`, `end_to_end_latency`, `recovery_soak`, `repository_authority`.

**D3. Embodied kræver alle ti.** De tre krops-gates beholder præcis de krav, de har i dag. Intet evidenskrav lempes.

**D4. BodyRig bliver i V1's pin-sæt.** `software_exact_green` og `repository_authority` dækker fortsat alle fire repositories. V1 udelader kroppens fysiske accept, ikke kroppens software.

**D5. `end_to_end_latency` i V1 måler perception → kognition → tale.** Latency-kontrakten tillader allerede `outward_kind` = `voice` uden krop, så validatoren skal ikke ændres. Det, der ændres, er release-kvalifikationens tekst, som i dag kræver måling til både første talte svar og næste kropsframe. Kropsframen flytter til Embodied (`voice+body`).

**D6. En V1-release må ikke påstå en krop.** Manifestet får et felt `release_scope` med værdien `v1` eller `embodied`. Klienternes body-flader forbliver bag deres nuværende gates, og release-noterne for V1 skal sige, at den fotoreale krop ikke er accepteret.

**D7. Embodied kan ikke bestå uden V1.** Embodied-manifestet skal pege på et bestået V1-manifest for samme eller ældre pins i de tre andre repositories, eller selv bære alle ti gates.

**D8. Dokumentet aktiverer ingenting.** Ingen runtime-flag, ingen default, ingen release følger af vedtagelsen.

## 3. Fravalgte alternativer

- **Behold ti gates som ét krav.** Ærligt, men V1 får ingen dato, og hver rigdag for de seks nemme gates forældes, mens BodyRig itererer.
- **Fjern de tre krops-gates.** Det ville lempe et krav i stilhed. D3 beholder dem uændret under eget navn.
- **Udelad BodyRig helt af V1's pin-sæt.** Så kunne V1 skibe med en BodyRig-software, ingen har kvalificeret, mens klienterne indeholder body-kode.
- **Lad latency-kravets tekst stå urørt.** Så kræver V1 stadig en måling til næste kropsframe, og opdelingen er kun på papiret.

## 4. Konsekvenser

- V1 kan lukkes på omkring tre rigdage efter 2.0.20 (rækkefølgen står i #2373, fase 4).
- Der bliver to manifester at vedligeholde og to gate-kørsler.
- "Kaliv V1" kommer til at betyde noget smallere end `KALIV_SYSTEM_DEFINITION.md` beskriver. Definitionen skal sige det.
- Embodied mister ikke noget, men heller ikke sin afhængighed af 7-døgns kørsler.

## 5. Kontrakttests (grønne før implementeringen landes)

1. Et V1-manifest med de syv gates `PASS` og de tre krops-gates `PENDING` består V1-gaten.
2. Samme manifest fejler Embodied-gaten.
3. Et manifest uden `release_scope`, eller med en ukendt værdi, afvises.
4. Et V1-manifest, hvor BodyRig mangler i pin-sættet, afvises (D4).
5. Et V1-manifest, hvor en af de syv er `PENDING` eller `FAIL`, afvises.
6. Et Embodied-manifest, hvor en af de ti ikke er `PASS`, afvises (D3).
7. Mutation: fjernes en gate fra V1's liste i kilden, bliver mindst én test rød.

## 6. Implementering (efter vedtagelse)

1. Land dette dokument alene.
2. Kontrakttests 1–7 som røde tests.
3. `kaliv_system_release_gate.py`: `release_scope`, to gate-lister, D7.
4. `KALIV_SYSTEM_RELEASE_QUALIFICATION.md`, `KALIV_SYSTEM_DEFINITION.md` og manifest-skabelonen.
5. Release-kvalifikationens latency-afsnit for D5. Validatoren røres ikke.

## 7. Valg truffet ved vedtagelsen

Anders fik tre spørgsmål 12/11 og vedtog udkastet med dets standardvalg.

- **Navn.** Den smalle release hedder "Kaliv V1". Den fulde hedder "Kaliv Embodied".
- **Latency.** V1 måler til første talte svar (`outward_kind` = `voice`). Det er D5.
- **VoiceRig-pin.** Afgøres ikke her. V1-accepten ligger på RC25 (`587e6cc`); om V1 pinner den SHA eller kræver ny accept på nyere `main`, afgøres, når pins vælges.

## 8. Hvad dokumentet bevidst ikke gør

- Det vælger ikke pins.
- Det ændrer ikke BodyRigs egne acceptkrav (BodyRig #2, #3, #4, #5, #817).
- Det tager ikke stilling til feature-stoppet (afgørelse C i #2373).
- Det ændrer ingen kode. Gate-scriptet og kravdokumenterne følger i egne PR'er efter afsnit 6.
