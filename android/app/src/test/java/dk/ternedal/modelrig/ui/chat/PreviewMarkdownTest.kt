package dk.ternedal.modelrig.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class PreviewMarkdownTest {

    @Test
    fun `fed skrift bliver ren tekst`() {
        assertEquals(
            "Du tænker sandsynligvis på Iliaden (oldgræsk)",
            previewFromMarkdown("Du tænker sandsynligvis på **Iliaden** (oldgræsk)"),
        )
        assertEquals(
            "Platons linjelignelse er en model",
            previewFromMarkdown("Platons **linjelignelse** er en model"),
        )
    }

    @Test
    fun `overskrifter citater og listetegn fjernes`() {
        assertEquals("Sådan virker det", previewFromMarkdown("### Sådan virker det"))
        assertEquals("citat her", previewFromMarkdown("> citat her"))
        assertEquals("første punkt", previewFromMarkdown("- første punkt"))
    }

    @Test
    fun `kode og links reduceres til tekst`() {
        assertEquals("kør docker build nu", previewFromMarkdown("kør `docker build` nu"))
        assertEquals("se dokumentationen", previewFromMarkdown("se [dokumentationen](https://eksempel.dk/a_b)"))
        assertEquals("skærmbillede", previewFromMarkdown("![skærmbillede](fil.png)"))
    }

    @Test
    fun `linjeskift og dobbelt mellemrum foldes sammen`() {
        assertEquals("linje et linje to", previewFromMarkdown("linje et\nlinje to"))
        assertEquals("a b", previewFromMarkdown("  a    b  "))
    }

    @Test
    fun `almindelig tekst med stjerner og understreger står urørt`() {
        assertEquals("2 * 3 = 6", previewFromMarkdown("2 * 3 = 6"))
        assertEquals("fil_navn_her.txt", previewFromMarkdown("fil_navn_her.txt"))
    }
}
