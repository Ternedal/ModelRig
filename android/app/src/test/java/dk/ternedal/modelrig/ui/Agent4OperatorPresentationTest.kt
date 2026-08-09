package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.Agent4OperatorClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class Agent4OperatorPresentationTest {
    @Test
    fun parsesCampaignDetailWithoutCreatingAParallelDomainModel() {
        val detail = Agent4OperatorPresentation.campaignDetail(
            Agent4OperatorClient.CanonicalJson(
                """{
                  "schema":"modelrig-agent4/campaign-record/v1",
                  "spec":{
                    "campaign_id":"c1","name":"Audit","workflow":"agent3.read",
                    "created_at":"2026-08-09T10:00:00Z","priority":20,
                    "scheduled_for":null,"max_attempts":3,"parameters":{},"metadata":{}
                  },
                  "state":{
                    "campaign_id":"c1","status":"running","revision":4,
                    "attempt":2,"updated_at":"2026-08-09T10:05:00Z",
                    "checkpoint_id":null,"last_error":null,
                    "execution_intervention_required":false,
                    "resource_reconciliation_required":false
                  }
                }""".trimIndent(),
            ),
        )
        assertEquals("agent3.read", detail.workflow)
        assertEquals(20, detail.priority)
        assertEquals(3, detail.maxAttempts)
        assertEquals(2, detail.attempt)
        assertEquals(4, detail.revision)
        assertNull(detail.lastError)
    }

    @Test
    fun parsesTimelineAndEvidenceRowsIncludingLargeCanonicalSize() {
        val timeline = Agent4OperatorPresentation.timelineRow(
            Agent4OperatorClient.CanonicalJson(
                """{
                  "schema":"modelrig-agent4/campaign-timeline-entry/v1",
                  "event":{
                    "event_id":"event-1","campaign_id":"c1","kind":"started",
                    "sequence":2,"occurred_at":"2026-08-09T10:01:00Z","payload":{}
                  },
                  "previous_hash":"sha256:${"a".repeat(64)}",
                  "evidence":[],
                  "entry_hash":"sha256:${"b".repeat(64)}"
                }""".trimIndent(),
            ),
        )
        assertEquals(2, timeline.sequence)
        assertEquals("started", timeline.kind)
        assertEquals(0, timeline.evidenceCount)

        val evidence = Agent4OperatorPresentation.evidenceRow(
            Agent4OperatorClient.CanonicalJson(
                """{
                  "schema":"modelrig-agent4/campaign-evidence-record/v1",
                  "campaign_id":"c1","sequence":1,
                  "recorded_at":"2026-08-09T10:02:00Z",
                  "evidence":{
                    "evidence_id":"ev-1","media_type":"application/json",
                    "location":"evidence/ev-1.json","sha256":"sha256:${"c".repeat(64)}",
                    "size_bytes":3000000000,"metadata":{}
                  },
                  "timeline_head_hash":"sha256:${"d".repeat(64)}",
                  "related_event_id":"event-1","previous_hash":null,
                  "record_hash":"sha256:${"e".repeat(64)}"
                }""".trimIndent(),
            ),
        )
        assertEquals("ev-1", evidence.evidenceId)
        assertEquals("application/json", evidence.mediaType)
        assertEquals(3_000_000_000L, evidence.sizeBytes)
    }

    @Test
    fun rejectsUnknownSchemaMalformedHashesAndNonStringText() {
        assertThrows(IllegalArgumentException::class.java) {
            Agent4OperatorPresentation.timelineRow(
                Agent4OperatorClient.CanonicalJson("{\"schema\":\"unknown\"}"),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            Agent4OperatorPresentation.timelineRow(
                Agent4OperatorClient.CanonicalJson(
                    """{
                      "schema":"modelrig-agent4/campaign-timeline-entry/v1",
                      "event":{
                        "event_id":7,"campaign_id":"c1","kind":"started",
                        "sequence":1,"occurred_at":"2026-08-09T10:01:00Z","payload":{}
                      },
                      "previous_hash":null,"evidence":[],
                      "entry_hash":"sha256:${"b".repeat(64)}"
                    }""".trimIndent(),
                ),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            Agent4OperatorPresentation.evidenceRow(
                Agent4OperatorClient.CanonicalJson(
                    """{
                      "schema":"modelrig-agent4/campaign-evidence-record/v1",
                      "campaign_id":"c1","sequence":1,
                      "recorded_at":"2026-08-09T10:02:00Z",
                      "evidence":{
                        "evidence_id":"ev-1","media_type":"application/json",
                        "location":"evidence/ev-1.json","sha256":"sha256:${"c".repeat(64)}",
                        "size_bytes":128,"metadata":{}
                      },
                      "timeline_head_hash":"sha256:${"d".repeat(64)}",
                      "related_event_id":null,"previous_hash":null,
                      "record_hash":"not-a-hash"
                    }""".trimIndent(),
                ),
            )
        }
    }
}
