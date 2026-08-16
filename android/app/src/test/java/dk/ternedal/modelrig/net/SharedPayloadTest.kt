package dk.ternedal.modelrig.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SharedPayloadTest {

    @Test
    fun `delt tekst bliver til tekst`() {
        val p = SharedPayload.from("husk mælk", null, null, null, null)
        assertEquals(SharedPayload.Text("husk mælk", null), p)
    }

    @Test
    fun `en fil vinder over teksten — mange apps sender begge`() {
        val p = SharedPayload.from("se vedhæftet", null, "content://docs/1", "application/pdf", "rapport.pdf")
        assertTrue(p is SharedPayload.Document)
        assertEquals("rapport.pdf", (p as SharedPayload.Document).suggestedName)
    }

    @Test
    fun `tom deling giver null — appen starter helt almindeligt`() {
        assertNull(SharedPayload.from("   ", null, null, null, null))
        assertNull(SharedPayload.from(null, "kun emne", null, null, null))
        assertNull(SharedPayload.from(null, null, "  ", null, null))
    }

    @Test
    fun `emnet foreslaas som kildenavn, ellers foerste linje`() {
        assertEquals(
            "Kvartalsnoter",
            (SharedPayload.from("linje 1\nlinje 2", "Kvartalsnoter", null, null, null) as SharedPayload.Text).suggestedName,
        )
        assertEquals(
            "linje 1",
            (SharedPayload.from("linje 1\nlinje 2", null, null, null, null) as SharedPayload.Text).suggestedName,
        )
    }

    @Test
    fun `filnavn falder tilbage til sidste sti-led uden query`() {
        val d = SharedPayload.from(null, null, "content://x/y/noter.md?take=1", "text/markdown", null)
        assertEquals("noter.md", (d as SharedPayload.Document).suggestedName)
    }

    @Test
    fun `meget lang tekst klippes — og det kan aflaeses`() {
        val long = "a".repeat(SharedPayload.MAX_TEXT + 500)
        val p = SharedPayload.from(long, null, null, null, null) as SharedPayload.Text
        assertEquals(SharedPayload.MAX_TEXT, p.text.length)
        assertTrue(SharedPayload.wasTruncated(long))
        assertTrue(!SharedPayload.wasTruncated("kort"))
    }

    @Test
    fun `en delt URL er TEKST — ikke en kommando om at hente noget`() {
        val p = SharedPayload.from("https://example.com/artikel", null, null, null, null)
        assertTrue(p is SharedPayload.Text)
        assertEquals("https://example.com/artikel", (p as SharedPayload.Text).text)
    }
}
