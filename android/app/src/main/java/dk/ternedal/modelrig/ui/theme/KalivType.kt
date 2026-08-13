package dk.ternedal.modelrig.ui.theme

import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.em
import dk.ternedal.modelrig.R

/**
 * Typografilaget for Kaliv-redesignet (DDR-001, fase 1).
 *
 * Fontene er bundlet som statiske instanser i praecis de vaegte designet
 * bruger (EB Garamond 500 til titler, Inter 400/600/700 til resten) --
 * instansieret fra Google Fonts' variable filer, se docs/design/FONT_LICENSES.md.
 * Statiske instanser fremfor variable filer: rendering er identisk paa alle
 * API-niveauer, og ingen afhaengighed af variable-font-instancing i Compose.
 *
 * Stoerrelser/vaegte/tracking laeses fra de genererede KalivTokens.Typography-
 * roller, saa dette lag aldrig kan drifte fra token-JSON'en: aendres en rolle
 * i JSON'en, foelger TextStyle med ved naeste regenerering.
 */
object KalivType {

    val EbGaramond: FontFamily = FontFamily(
        Font(R.font.eb_garamond_medium, FontWeight.Medium),
    )

    val Inter: FontFamily = FontFamily(
        Font(R.font.inter_regular, FontWeight.Normal),
        Font(R.font.inter_semibold, FontWeight.SemiBold),
        Font(R.font.inter_bold, FontWeight.Bold),
    )

    private fun familyOf(name: String): FontFamily =
        if (name == "EB Garamond") EbGaramond else Inter

    /** Skaermtitler, 26sp EB Garamond 500 (mockup 21px, jf. B2-skalaen). */
    val Title: TextStyle = TextStyle(
        fontFamily = familyOf(KalivTokens.Typography.Title.family),
        fontWeight = FontWeight(KalivTokens.Typography.Title.weight),
        fontSize = KalivTokens.Typography.Title.size,
        letterSpacing = KalivTokens.Typography.Title.trackingEm.em,
    )

    /** Sheet-titler, 24sp EB Garamond 500. */
    val SheetTitle: TextStyle = TextStyle(
        fontFamily = familyOf(KalivTokens.Typography.Sheettitle.family),
        fontWeight = FontWeight(KalivTokens.Typography.Sheettitle.weight),
        fontSize = KalivTokens.Typography.Sheettitle.size,
        letterSpacing = KalivTokens.Typography.Sheettitle.trackingEm.em,
    )

    /** Raekketitler/brod i kort og lister, 16,5sp Inter 600. */
    val RowTitle: TextStyle = TextStyle(
        fontFamily = familyOf(KalivTokens.Typography.Rowtitle.family),
        fontWeight = FontWeight(KalivTokens.Typography.Rowtitle.weight),
        fontSize = KalivTokens.Typography.Rowtitle.size,
    )

    /** Sekundaer tekst, 13,5sp Inter 400. */
    val Secondary: TextStyle = TextStyle(
        fontFamily = familyOf(KalivTokens.Typography.Secondary.family),
        fontWeight = FontWeight(KalivTokens.Typography.Secondary.weight),
        fontSize = KalivTokens.Typography.Secondary.size,
    )

    /** Sub-/metatekst, 13sp Inter 400. */
    val Sub: TextStyle = TextStyle(
        fontFamily = familyOf(KalivTokens.Typography.Sub.family),
        fontWeight = FontWeight(KalivTokens.Typography.Sub.weight),
        fontSize = KalivTokens.Typography.Sub.size,
    )

    /** Caps-sektionslabels, 11,5sp Inter 700, tracking 0,18em. Brug uppercase i indhold. */
    val CapsLabel: TextStyle = TextStyle(
        fontFamily = familyOf(KalivTokens.Typography.Capslabel.family),
        fontWeight = FontWeight(KalivTokens.Typography.Capslabel.weight),
        fontSize = KalivTokens.Typography.Capslabel.size,
        letterSpacing = KalivTokens.Typography.Capslabel.trackingEm.em,
    )

    /** KALIV-afsenderlinjen, 12sp Inter 700, tracking 0,2em. */
    val BrandLine: TextStyle = TextStyle(
        fontFamily = familyOf(KalivTokens.Typography.Brandline.family),
        fontWeight = FontWeight(KalivTokens.Typography.Brandline.weight),
        fontSize = KalivTokens.Typography.Brandline.size,
        letterSpacing = KalivTokens.Typography.Brandline.trackingEm.em,
    )
}
