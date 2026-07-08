# Alva brand identity

**Projekt:** Alva  
**Backend/motor:** ModelRig  
**Brandretning:** Lokal-først, privat, nordisk, runisk, rolig og premium uden at blive kitsch.  
**Status:** Brand-retning til kvalitetssikring og videreudvikling i eksisterende roadmap.

---

## 1. Brandbeslutninger

| Område | Beslutning |
|---|---|
| Appnavn | **Alva** |
| Backend/motor | **ModelRig** |
| Voice layer | **Alva Voice** |
| Memory layer | **Alva Memory** |
| Tools layer | **Alva Tools** |
| UI layer | **Alva UI** |
| Wake word | **“Hey Alva”** |
| Overordnet tagline | **Din personlige AI-assistent** |
| Sekundær tagline | **Bygget lokalt. Designet til dig.** |
| Brandprincip | Lokal-first, privat, åben, modulær |

---

## 2. Kernepositionering

Alva er den menneskelige, brugerrettede assistentoplevelse. ModelRig er maskinrummet.

```text
Alva = personlig assistent, samtale, stemme, hukommelse og handling
ModelRig = lokal model-runtime, routing, orchestration, pipelines og infrastruktur
```

Kort produkttekst:

> Alva er en lokal-først personlig AI-assistent, der samler stemme, hukommelse, værktøjer og åbne modeller i én rolig brugeroplevelse. ModelRig er motoren under Alva og håndterer modeller, routing, ASR, TTS, lokal viden og integrationer.

---

## 3. Logo-retning

Logoet skal tage udgangspunkt i brugerens eksisterende ModelRig-inspirerede node-/graf-symbol, men omformes til en mere runisk og nordisk bindmark.

### Det endelige symbol skal føles som

- en **rune/bindrune** bygget af noder og forbindelser,
- et **monogram** med indirekte relation til A / V / M,
- en lokal AI-kernel / nodegraf,
- noget indgraveret i sten eller metal,
- premium og teknisk, men ikke corporate SaaS.

### Logoet må ikke føles som

- Bluetooth-symbol,
- fantasy-game guild logo,
- tilfældig vikingeclipart,
- religiøst/mystisk emblem,
- for tungt eller for svært at aflæse som appikon.

### Hovedgreb

Brug en geometrisk runisk struktur med:

- lodrette stavformer,
- diagonale krydsforbindelser,
- fire nodepunkter/cirkler,
- subtil symmetri,
- små sekundære runetegn som ornamental støtte,
- cirkel/segl som primær ramme til ikon og brand moments.

---

## 4. Farvepalette

Primær palette fra den nuværende retning:

| Navn | Hex | Brug |
|---|---:|---|
| Deep Forest | `#13241E` | Primær mørk baggrund, app shell, cards |
| Nordic Charcoal | `#1A1D1F` | Sekundær mørk baggrund, modal, paneler |
| Stone Gray | `#5A5F60` | Neutral tekst, strokes, sekundære elementer |
| Bone White | `#E7E3DA` | Lys tekst, lyse flader, kontrast |
| Antique Gold | `#B89A5D` | Accent, logo-metal, highlights, active states |

### Brug

- Brug mørkegrøn/sort som primær base.
- Brug guld sparsomt som accent, ikke som flad UI-farve overalt.
- Brug bone/stone som varme neutrale farver, så brandet ikke bliver koldt blå-SaaS.
- Undgå neon, ren blå/lilla gradient og for meget “AI startup”-glow.

---

## 5. Typografi

### Brand/headline

**Cinzel / Trajan-lignende display serif**

Bruges til:

- logo-lockups,
- brandboards,
- hero-sektioner,
- særlige produktmoments.

Bemærk: Brug ikke en kommerciel font uden licenstjek. Hvis projektet skal være frit delbart, vælg en åben font med lignende udtryk.

### UI/brødtekst

**Inter**

Bruges til:

- app UI,
- menuer,
- knapper,
- settings,
- dokumentation,
- teknisk tekst.

---

## 6. Tone of voice

Alva skal lyde:

- rolig,
- klar,
- hjælpsom,
- kompetent,
- respektfuld,
- lidt tør og menneskelig uden at blive påtaget.

Sprogprincipper:

- Kort når det giver mening.
- Forklarende når brugeren beder om det.
- Ærlig når noget er usikkert.
- Aldrig bedrevidende.
- Lokal-first og privatlivsorienteret.

Eksempel:

> Klart. Jeg kan godt hjælpe med det. Jeg starter med det lokale først, og bruger kun cloud, hvis du beder om det eller hvis opgaven kræver det.

---

## 7. Produktarkitektur i brandet

```text
Alva
├─ Alva Voice      Stemme, ASR, TTS og interaktion
├─ Alva Memory     Lokal hukommelse, kontekst og RAG
├─ Alva Tools      Handlinger og integrationer
├─ Alva UI         Desktop/web/mobile interface
└─ ModelRig Core   Lokal AI-kerne, modelruntime og orchestration
```

ModelRig bør omtales som “powered by ModelRig” eller “drives Alva locally”.

---

## 8. UI-retning

UI skal være:

- mørk, rolig og fokuseret,
- tydeligt modulopdelt,
- lokalt/privat som standard,
- lav på visuel støj,
- med diskret guld-accent,
- med store, tydelige samtale- og inputfelter.

Navigation:

```text
Hjem
Samtaler
Hukommelse
Værktøjer
Indsigter / Projekter
Indstillinger
```

Kortnavne:

```text
Samtal       Naturlige samtaler
Hukommelse   Husker det vigtige
Værktøjer    Gør mere for dig
Indsigter    Forstå det vigtige
```

---

## 9. Design-do / design-don’t

### Do

- Genskab logoet som ren SVG.
- Hold symbolet enkelt nok til 512x512 appikon.
- Bevar nodegraf-DNA fra originalikonet.
- Brug runisk formsprog som struktur, ikke pynt.
- Brug guld/sten-metal som accent i brandmateriale.
- Brug fladere, enklere version i faktisk UI.

### Don’t

- Brug ikke den genererede bitmap som eneste logo-source.
- Gør ikke runerne for komplekse.
- Brug ikke for mange ornamenter i UI.
- Lav ikke symbolet for tæt på Bluetooth.
- Gør ikke appen til fantasy-univers. Den skal stadig være en AI-assistent.

---

## 10. Næste designopgaver

1. Genskab hovedsymbolet som SVG.
2. Lav optisk simplificeret app-icon version.
3. Lav monokrom version.
4. Lav mørk/lys logo-lockup.
5. Lav favicon/small-size test.
6. Lav UI-tokenfil med farver, typografi, spacing og komponentprincipper.
7. Opdater roadmap med brandhierarki: Alva ovenpå ModelRig.
