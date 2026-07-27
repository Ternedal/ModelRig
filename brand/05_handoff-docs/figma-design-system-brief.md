# Figma / Design System Brief – ModelRig

> **OVERHALET — læs ikke dette som gældende.**
>
> Dette dokument beskriver **ModelRig** med *safirblå* som primær handlingsfarve
> og champagne som accent. Produktet hedder nu **Kaliv**, og designretningen er
> skiftet til messing/bronze. Der er ingen blå i det gældende system.
>
> Gældende kilder:
> - `brand/KALIV_BRAND_HANDOFF.md` — brandpakken, ankh-symbolet
> - `assets/design/kaliv-ui-guide/` — UI-guide, mockups og tjekliste
> - `assets/design/kaliv-ui-guide/kaliv-ui-tokens.json` — **eneste** tokenkilde;
>   den genereres til Kotlin af `scripts/design_tokens.py` og er CI-gated
>
> Bevaret som historik. Bygger du efter tokennavnene herunder
> (`color.primary.sapphire`, `radius.sm`, `space.5 = 24`), bygger du et andet
> produkt end det der findes.


## Mål
Omsæt brandmaterialet til et lille, robust Figma-system.

## Foreslået Figma-struktur

### Page 1 – Foundations
- logo
- color styles
- typography styles
- icon rules
- spacing
- radius
- elevation / borders

### Page 2 – Components
- buttons
- fields
- chips / badges
- side navigation
- cards
- model list items
- document list items
- toggles / switches
- chat components

### Page 3 – Patterns
- application shell
- left sidebar
- content area
- right utility / context panel
- dashboard cards
- empty states

### Page 4 – Screens
- chat screen
- model screen
- settings screen
- documents / RAG screen

## Komponentprincipper
- 8pt grid
- konsistent padding
- samme radiusskala overalt
- tydelige states: default / hover / active / disabled / error
- statusfarver skal være få og tydelige

## Teksturer og effekter
- meget subtile glows
- lav støj
- mørke gradients med forsigtighed
- brug elevation sparsomt
- vigtigste fokus skal være læsbarhed og kontrol
