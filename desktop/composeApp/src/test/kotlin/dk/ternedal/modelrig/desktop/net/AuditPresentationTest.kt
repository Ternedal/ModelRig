package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class AuditPresentationTest {
    @Test
    fun rigStatusIsHumanizedWhileRawEvidenceIsRetained() {
        val raw = """
            disk_free_gb=321.5
            disk_total_gb=931.5
            asr_available=True
            asr_device=cuda
            asr_model=whisper-large-v3
            tts_available=False
            gpu=NVIDIA RTX 3060, 1024 MiB, 12288 MiB
        """.trimIndent()

        val entry = AuditEntry(tool = "rig_status", rawResultSummary = raw)

        assertEquals(raw, entry.rawResultSummary)
        assertEquals(
            """
                Ledig diskplads: 321.5 GB
                Disk i alt: 931.5 GB
                GPU: NVIDIA RTX 3060, 1024 MiB, 12288 MiB
                Talegenkendelse: tilgængelig
                Talegenkendelse kører på: cuda
                Talegenkendelsesmodel: whisper-large-v3
                Talesyntese: ikke tilgængelig
            """.trimIndent(),
            entry.result_summary,
        )
        assertFalse("asr_available=" in entry.result_summary)
        assertFalse("disk_free_gb=" in entry.result_summary)
    }

    @Test
    fun unknownRigStatusKeysFailClosedInsteadOfBecomingUiCopy() {
        val raw = """
            future_internal_token=do-not-display
            asr_available=False
            private_debug_path=C:\Users\operator\secret
        """.trimIndent()

        val rendered = desktopAuditOperatorSummary("rig_status", raw)

        assertEquals("Talegenkendelse: ikke tilgængelig", rendered)
        assertFalse("future_internal_token" in rendered)
        assertFalse("do-not-display" in rendered)
        assertFalse("private_debug_path" in rendered)
        assertFalse("secret" in rendered)
    }

    @Test
    fun unavailableGpuAndUnknownAvailabilityStayOperatorReadable() {
        val rendered = desktopAuditOperatorSummary(
            "rig_status",
            "gpu=unavailable\nasr_available=maybe\ntts_available=",
        )

        assertEquals(
            "GPU: ikke tilgængelig\nTalegenkendelse: ukendt\nTalesyntese: ukendt",
            rendered,
        )
    }

    @Test
    fun nonRigSummaryKeepsItsExistingProse() {
        val raw = "  Startede download af 'qwen3:14b' som job abc123.  "
        assertEquals(
            "Startede download af 'qwen3:14b' som job abc123.",
            desktopAuditOperatorSummary("pull_model", raw),
        )
    }

    @Test
    fun wireFieldStillDecodesAsResultSummary() {
        val entry = Json { ignoreUnknownKeys = true }.decodeFromString<AuditEntry>(
            """{"ts":"2026-09-12T10:00:00Z","tool":"rig_status","risk":"read","outcome":"executed","origin":"local","result_summary":"disk_free_gb=100.0\\nasr_available=False"}""",
        )

        assertEquals("disk_free_gb=100.0\nasr_available=False", entry.rawResultSummary)
        assertEquals(
            "Ledig diskplads: 100.0 GB\nTalegenkendelse: ikke tilgængelig",
            entry.result_summary,
        )
        assertTrue(entry.rawResultSummary.contains("disk_free_gb="))
        assertFalse(entry.result_summary.contains("disk_free_gb="))
    }
}
