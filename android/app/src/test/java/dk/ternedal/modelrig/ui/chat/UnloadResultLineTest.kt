package dk.ternedal.modelrig.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class UnloadResultLineTest {

    @Test
    fun `rigens tal skrives som de er`() {
        assertEquals("1 model sluppet \u00b7 9,0 GB frigjort", unloadResultLine(1, 9_663_676_416L, 0))
        assertEquals("2 modeller sluppet \u00b7 9,5 GB frigjort", unloadResultLine(2, 10_200_547_328L, 0))
    }

    @Test
    fun `ingenting indlaest siges rent ud`() {
        assertEquals("Ingen modeller var indlæst", unloadResultLine(0, 0L, 0))
    }

    @Test
    fun `delvis fejl skjules ikke`() {
        assertEquals(
            "1 model sluppet \u00b7 0,1 GB frigjort \u00b7 1 kunne ikke slippes",
            unloadResultLine(1, 107_374_182L, 1),
        )
    }
}
