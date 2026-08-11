package dk.ternedal.modelrig.net

import org.json.JSONObject
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterAuditClientTest {
    @Test
    fun rawArgumentsNeverEnterControlCenterModel() {
        val snapshot = client().parse(JSONObject(payload()))
        val entry = snapshot.entries.single()

        assertEquals("tool:note_append", entry.capabilityId)
        assertEquals("task-123", entry.taskRef)
        assertEquals("confirm-123", entry.approvalId)
        assertEquals("cloud", entry.origin)
        assertEquals("executed", entry.outcome)
        assertFalse(entry.toString().contains("TOP SECRET VALUE"))
        assertFalse(snapshot.toString().contains("TOP SECRET VALUE"))
    }

    @Test
    fun taskCapabilityAndApprovalFiltersUseRecordedEvidence() {
        val snapshot = client().parse(JSONObject(payload()))

        assertEquals(1, snapshot.filtered(ControlCenterAuditFilter(task = "task-123")).size)
        assertEquals(1, snapshot.filtered(ControlCenterAuditFilter(capability = "tool:note")).size)
        assertEquals(1, snapshot.filtered(ControlCenterAuditFilter(approval = "confirm-123")).size)
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(task = "other-task")).isEmpty())
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(capability = "tool:rig_status")).isEmpty())
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(approval = "other-approval")).isEmpty())
    }

    @Test
    fun connectorFilterFailsClosedBecauseConnectorIsNotRecorded() {
        val snapshot = client().parse(JSONObject(payload()))

        assertEquals("unavailable", snapshot.connectorEvidence.state)
        assertEquals("tool_audit_does_not_record_connector_id", snapshot.connectorEvidence.reason)
        assertTrue(snapshot.entries.single().connectorId == null)
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(connector = "gmail")).isEmpty())
    }

    @Test
    fun malformedScalarTypesFailClosed() {
        val fractionalDuration = payload().replace("\"duration_ms\":12", "\"duration_ms\":12.5")
        val error = runCatching { client().parse(JSONObject(fractionalDuration)) }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue(error.message.orEmpty().contains("duration_ms must be an integer"))

        val stringDuration = payload().replace("\"duration_ms\":12", "\"duration_ms\":\"12\"")
        val error2 = runCatching { client().parse(JSONObject(stringDuration)) }.exceptionOrNull()
        assertTrue(error2 is ModelRigException)
    }

    @Test
    fun unknownOutcomeStaysUnknownDataInsteadOfSyntheticSuccess() {
        val snapshot = client().parse(
            JSONObject(payload().replace("\"outcome\":\"executed\"", "\"outcome\":\"future_outcome\"")),
        )
        assertEquals("future_outcome", snapshot.entries.single().outcome)
    }

    private fun client() = ControlCenterAuditClient("http://127.0.0.1:1", "token")

    private fun payload() = """
        {
          "entries":[
            {
              "ts":"2026-08-11T11:00:00",
              "conversation_id":"task-123",
              "tool":"note_append",
              "args_json":"{\\\"text\\\":\\\"TOP SECRET VALUE\\\"}",
              "risk":"write",
              "outcome":"executed",
              "confirmation_id":"confirm-123",
              "result_summary":"ok",
              "duration_ms":12,
              "origin":"cloud"
            }
          ]
        }
    """.trimIndent()
}
