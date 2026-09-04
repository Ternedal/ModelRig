# Fontlicenser — Kaliv-redesignet

Begge familier er licenseret under SIL Open Font License 1.1 (fuld tekst i
`docs/design/fonts/`). Hentet fra `github.com/google/fonts` 13/08-2026 og
instansieret som statiske vaegte med fontTools' instancer (OFL tillader
modifikation; instanserne beholder OFL og krediteringen i navnetabellen):

| Fil (res/font/) | Familie | Vaegt | Kilde-akser |
| --- | --- | --- | --- |
| eb_garamond_medium.ttf | EB Garamond | 500 | wght=500 |
| inter_regular.ttf | Inter | 400 | wght=400, opsz=14 |
| inter_semibold.ttf | Inter | 600 | wght=600, opsz=14 |
| inter_bold.ttf | Inter | 700 | wght=700, opsz=14 |

Samlet APK-tilvaekst ca. 1,5 MB (TTF komprimerer stort set ikke i APK'en).
Statiske instanser fremfor variable filer er et bevidst valg, jf. KalivType.kt.
