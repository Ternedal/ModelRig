package dk.ternedal.modelrig.ui.chat

import dk.ternedal.modelrig.R
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/**
 * Riggens værktøjs-navnerum er en KENDT, lukket liste. Testen pinner den:
 * ændrer nogen REGISTRY uden at give det nye værktøj et ikon, falder det
 * ned på værktøjs-glyffen — og det skal være et bevidst valg, ikke et uheld.
 */
class AuditToolIconTest {

    private val registry = listOf(
        "rig_status", "note_append", "list_models", "current_datetime",
        "job_status", "cancel_job", "list_documents", "delete_model", "pull_model",
        "web_research", "github_read", "desktop_screenshot", "desktop_action_preview",
    )

    @Test
    fun `hvert kendt vaerktoej har sit eget ikon — ingen falder paa fallback`() {
        for (tool in registry) {
            assertNotEquals(
                "$tool mangler et ikon og falder paa vaerktoejs-glyffen",
                R.drawable.ic_kaliv_tools,
                auditToolIcon(tool),
            )
        }
    }

    @Test
    fun `ukendt vaerktoej faar vaerktoejs-glyffen — aldrig et laant ikon`() {
        assertEquals(R.drawable.ic_kaliv_tools, auditToolIcon("noget_helt_nyt"))
        assertEquals(R.drawable.ic_kaliv_tools, auditToolIcon(""))
        assertEquals(R.drawable.ic_kaliv_tools, auditToolIcon("Filer"))
        assertEquals(R.drawable.ic_kaliv_tools, auditToolIcon("Terminal"))
    }

    @Test
    fun `navnet normaliseres for mellemrum og store bogstaver`() {
        assertEquals(auditToolIcon("note_append"), auditToolIcon("  NOTE_APPEND "))
    }

    @Test
    fun `de to desktop-vaerktoejer deler skaerm-ikonet`() {
        assertEquals(auditToolIcon("desktop_screenshot"), auditToolIcon("desktop_action_preview"))
    }

    @Test
    fun `beslaegtede men forskellige handlinger deler ikke ikon`() {
        assertNotEquals(auditToolIcon("pull_model"), auditToolIcon("delete_model"))
        assertNotEquals(auditToolIcon("job_status"), auditToolIcon("cancel_job"))
    }
}
