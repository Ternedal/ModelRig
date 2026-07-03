# Implementeringsbrief – ModelRig

## Formål
Dette dokument er en kort handoff til udvikling og designimplementering.

## Hvad skal implementeres først

### 1. Brand foundations
Implementér følgende først:
- logo lockup
- symbol / app-ikon
- primær farvepalette
- typografisk system
- basis spacing / radius

### 2. Design tokens
Etabler følgende tokens:

#### Farver
- `color.bg.obsidian`
- `color.bg.graphite`
- `color.primary.sapphire`
- `color.primary.sapphireGradientStart`
- `color.primary.sapphireGradientEnd`
- `color.accent.champagne`
- `color.text.cloud`
- `color.state.success`
- `color.state.danger`

#### Radius
- `radius.sm = 8`
- `radius.md = 12`
- `radius.lg = 16`
- `radius.pill = 999`

#### Spacing
- `space.1 = 4`
- `space.2 = 8`
- `space.3 = 12`
- `space.4 = 16`
- `space.5 = 24`
- `space.6 = 32`
- `space.7 = 48`
- `space.8 = 64`

### 3. Første komponenter i UI-biblioteket
Byg disse først:
- button (primary / secondary / tertiary / danger)
- input field (default / focus / filled / disabled / error)
- navigation item
- sidebar section card
- model card
- badge / status dot
- chat bubble
- RAG toggle row
- document list item

### 4. Første skærme
Omsæt derefter disse visninger:
- chat view
- model library / model list
- settings / preferences
- documents / RAG context panel
- status / diagnostics panel

## UX-principper
- Bevar **mørk premium base**
- Brug blå til **handlinger og fokus**
- Brug champagne til **premium accent og sekundære highlights**
- Hold meget luft og tydeligt hierarki
- Brug subtile borders frem for tung støj
- Fokusér på ro, kontrol og læsbarhed

## Handoff note
De medfølgende boards er **konceptuelle retninger**. For endelig produktion anbefales:
1. vektorrekonstruktion af logo
2. systematisk Figma-fil
3. komponentbibliotek
4. eksportpakke til ikoner og splash assets
