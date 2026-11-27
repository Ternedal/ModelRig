# Kaliv VR — Designpakke v2.1

## Godkendt reference
`source/approved_original_1670x942.png` er den **senest godkendte** splash med en mere voksen, venlig, blå og delvist gennemsigtig hologramfigur, løst hår, diskret wireframe og ankh. Denne erstatter v2.0-referencen.

## Indhold
- `source/`: original 1670 × 942 PNG uden opskalering.
- `splash/`: separate PNG-filer i 1920 × 1080, 2560 × 1440, 3840 × 2160 og 4096 × 2304.
- `backgrounds/`: 2048 × 1024 og 4096 × 2048 WebP, centerbeskåret fra splash. **Ikke 360° panoramaer**.
- `branding/`: selvstændigt SVG-ankh og transparente PNG-varianter. Ankh er en vektoriseret stilfortolkning, ikke udtrukket fra splash. `legacy_v2_0_concept_square_1024_NOT_APPROVED.png` er bevaret alene til historik og må ikke bruges som v2.1-reference.
- `ui/`: otte ikoner som SVG og PNG i 128/256 px.
- `docs/`: PDF-designguide samt JSON/CSS tokens.

## Kvalitet og begrænsninger
- Native original er 1670 × 942; de større PNG'er er LANCZOS-opskalerede. De har korrekte pixelmål, men **ikke ægte native 4K-detaljer**.
- Splash indeholder hologram, logo, ankh og miljø i **samme flade billede**. Ingen præcise alpha-separerede lag eller 3D-avatar er inkluderet.
- 2:1-baggrunde er **flade beskæringer**, ikke stereoskopiske eller equirectangulære panoramaer.
- Designfarverne er konceptbaserede; verificer mod kaliv.dk's faktiske brandfarver inden produktionsrelease.
- Quest: vis som flad quad/loading-screen, test læsbarhed og performance i headset, og undgå at kalde flade billeder 360°-assets.

## Status
Godkendt **visuelt splash-koncept** v2.1; ikke en fuldt lagopdelt produktionspakke.
