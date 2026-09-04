package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

class Agent4SnapshotOperatorClientTest {
    private val a = "a".repeat(64)
    private val b = "b".repeat(64)
    private val c = "c".repeat(64)

    @Test
    fun detailAcquiresRootAndEveryRelatedReadCarriesIt() {
        val server = MockWebServer()
        server.enqueue(response(detailBody(a)))
        server.enqueue(response(timelineBody(a)))
        server.enqueue(response(evidenceBody(a)))
        server.enqueue(response(verificationBody(a)))
        server.start()
        try {
            val client = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val detail = client.campaign("campaign-1")
            val timeline = client.timeline("campaign-1", detail.snapshotId)
            val evidence = client.evidencePage("campaign-1", detail.snapshotId)
            val verification = client.evidenceVerification("campaign-1", detail.snapshotId)

            assertEquals(a, detail.snapshotId.value)
            assertEquals(detail.snapshotId, timeline.snapshotId)
            assertEquals(detail.snapshotId, evidence.snapshotId)
            assertEquals(detail.snapshotId, verification.snapshotId)

            val detailRequest = server.takeRequest()
            assertNull(detailRequest.requestUrl?.queryParameter("snapshot_id"))
            repeat(3) {
                val request = server.takeRequest()
                assertEquals(a, request.requestUrl?.queryParameter("snapshot_id"))
                assertEquals(Agent4SnapshotOperatorClient.MEDIA_TYPE, request.getHeader("Accept"))
            }
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun responseThatChangesSnapshotIdMidFlowFailsClosed() {
        val server = MockWebServer()
        server.enqueue(response(detailBody(a)))
        server.enqueue(response(timelineBody(b)))
        server.start()
        try {
            val client = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val detail = client.campaign("campaign-1")
            val error = runCatching {
                client.timeline("campaign-1", detail.snapshotId)
            }.exceptionOrNull() as Agent4SnapshotOperatorClient.OperatorException

            assertEquals(Agent4SnapshotOperatorClient.ErrorKind.PROTOCOL, error.kind)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun expiredSnapshotIsRefreshRequiredAndNeverRetriedAgainstCurrent() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(410)
                .setHeader("Content-Type", Agent4SnapshotOperatorClient.MEDIA_TYPE)
                .setBody("""{"detail":"agent4 operator snapshot unavailable"}"""),
        )
        server.start()
        try {
            val client = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val error = runCatching {
                client.timeline(
                    "campaign-1",
                    Agent4SnapshotOperatorClient.SnapshotId(a),
                )
            }.exceptionOrNull() as Agent4SnapshotOperatorClient.OperatorException

            assertEquals(Agent4SnapshotOperatorClient.ErrorKind.REFRESH_REQUIRED, error.kind)
            assertEquals(410, error.statusCode)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun campaignPagingRoundTripsServerOwnedRootBoundCursors() {
        val server = MockWebServer()
        val firstStart = campaignCursor(a, 0, 2, null)
        val firstNext = campaignCursor(a, 1, 2, "campaign-1")
        val firstHead = campaignCursor(a, 2, 2, "campaign-2")
        server.enqueue(
            response(
                listBody(
                    snapshot = a,
                    campaigns = listOf(overview("campaign-1")),
                    start = firstStart,
                    next = firstNext,
                    head = firstHead,
                    more = true,
                ),
            ),
        )
        server.enqueue(
            response(
                listBody(
                    snapshot = a,
                    campaigns = listOf(overview("campaign-2")),
                    start = firstNext,
                    next = firstHead,
                    head = firstHead,
                    more = false,
                ),
            ),
        )
        server.start()
        try {
            val client = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val first = client.listCampaigns(limit = 1)
            val second = client.listCampaigns(
                snapshotId = first.snapshotId,
                after = first.nextCursor,
                snapshotHead = first.headCursor,
                limit = 1,
            )

            assertEquals(a, second.snapshotId.value)
            assertFalse(second.hasMore)
            server.takeRequest()
            val request = server.takeRequest()
            assertEquals(a, request.requestUrl?.queryParameter("snapshot_id"))
            assertEquals(first.nextCursor.encoded, request.requestUrl?.queryParameter("after"))
            assertEquals(first.headCursor.encoded, request.requestUrl?.queryParameter("snapshot_head"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun timelineContinuationCarriesRootAndCursorButNeverClientSnapshotHead() {
        val server = MockWebServer()
        server.enqueue(response(timelineBody(a, hasMore = true)))
        server.enqueue(response(timelineBody(a, startSequence = 1, hasMore = false)))
        server.start()
        try {
            val client = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val root = Agent4SnapshotOperatorClient.SnapshotId(a)
            val first = client.timeline("campaign-1", root, limit = 1)
            client.timeline("campaign-1", root, after = first.nextCursor, limit = 1)

            server.takeRequest()
            val request = server.takeRequest()
            assertEquals(a, request.requestUrl?.queryParameter("snapshot_id"))
            assertEquals(first.nextCursor.encoded, request.requestUrl?.queryParameter("after"))
            assertNull(request.requestUrl?.queryParameter("snapshot_head"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun malformedOrUppercaseSnapshotIdsFailProtocolValidation() {
        val server = MockWebServer()
        server.enqueue(response(detailBody(a.uppercase())))
        server.start()
        try {
            val error = runCatching {
                Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
                    .campaign("campaign-1")
            }.exceptionOrNull() as Agent4SnapshotOperatorClient.OperatorException
            assertEquals(Agent4SnapshotOperatorClient.ErrorKind.PROTOCOL, error.kind)
        } finally {
            server.shutdown()
        }
    }

    private fun response(body: String): MockResponse = MockResponse()
        .setResponseCode(200)
        .setHeader("Content-Type", Agent4SnapshotOperatorClient.MEDIA_TYPE)
        .setBody(body)

    private fun detailBody(snapshot: String): String = """{
      "schema":"${Agent4SnapshotOperatorClient.SCHEMA}",
      "snapshot_id":"$snapshot",
      "campaign":${overview("campaign-1")}
    }""".trimIndent()

    private fun listBody(
        snapshot: String,
        campaigns: List<String>,
        start: String,
        next: String,
        head: String,
        more: Boolean,
    ): String = """{
      "schema":"${Agent4SnapshotOperatorClient.SCHEMA}",
      "snapshot_id":"$snapshot",
      "campaigns":[${campaigns.joinToString(",")}],
      "start_cursor":$start,
      "next_cursor":$next,
      "head_cursor":$head,
      "has_more":$more
    }""".trimIndent()

    private fun timelineBody(
        snapshot: String,
        startSequence: Int = 0,
        hasMore: Boolean = false,
    ): String {
        val nextSequence = startSequence + 1
        val headSequence = if (hasMore) nextSequence + 1 else nextSequence
        val nextHash = if (nextSequence == 1) "sha256:$b" else "sha256:$c"
        val headHash = if (headSequence == 1) "sha256:$b" else "sha256:$c"
        val startHash = when (startSequence) {
            0 -> null
            1 -> "sha256:$b"
            else -> "sha256:$c"
        }
        return """{
          "schema":"${Agent4SnapshotOperatorClient.SCHEMA}",
          "snapshot_id":"$snapshot",
          "page":{
            "campaign_id":"campaign-1",
            "entries":[${timelineEntry(nextSequence, nextHash)}],
            "start_cursor":${timelineCursor(snapshot, startSequence, startHash)},
            "next_cursor":${timelineCursor(snapshot, nextSequence, nextHash)},
            "head_cursor":${timelineCursor(snapshot, headSequence, headHash)},
            "has_more":$hasMore
          }
        }""".trimIndent()
    }

    private fun evidenceBody(snapshot: String): String = """{
      "schema":"${Agent4SnapshotOperatorClient.SCHEMA}",
      "snapshot_id":"$snapshot",
      "page":{
        "campaign_id":"campaign-1",
        "records":[${evidenceRecord(1, "sha256:$c")}],
        "start_cursor":${evidenceCursor(snapshot, 0, null)},
        "next_cursor":${evidenceCursor(snapshot, 1, "sha256:$c")},
        "head_cursor":${evidenceCursor(snapshot, 1, "sha256:$c")},
        "has_more":false
      }
    }""".trimIndent()

    private fun verificationBody(snapshot: String): String = """{
      "schema":"${Agent4SnapshotOperatorClient.SCHEMA}",
      "snapshot_id":"$snapshot",
      "verification":{
        "campaign_id":"campaign-1",
        "record_count":1,
        "head_hash":"sha256:$c",
        "latest_timeline_head_hash":"sha256:$b"
      }
    }""".trimIndent()

    private fun overview(id: String): String = """{
      "record":{
        "schema":"modelrig-agent4/campaign-record/v1",
        "spec":{"campaign_id":"$id","name":"Campaign $id","workflow":"agent3.write-pilot","created_at":"2026-08-10T18:00:00Z"},
        "state":{"campaign_id":"$id","status":"running","revision":1,"attempt":1,"updated_at":"2026-08-10T18:00:01Z","last_error":null,"pause_reason":null,"cancel_reason":null,"handoff":null,"last_checkpoint_id":null,"next_retry_at":null}
      },
      "timeline_entries":1,
      "event_entries":1,
      "evidence_entries":1,
      "latest_timeline_hash":"sha256:$b"
    }""".trimIndent()

    private fun campaignCursor(snapshot: String, position: Int, total: Int, lastId: String?): String {
        val last = if (lastId == null) "null" else "\"$lastId\""
        return """{
          "schema":"${Agent4SnapshotOperatorClient.SNAPSHOT_CURSOR_SCHEMA}",
          "snapshot_id":"$snapshot",
          "cursor":{
            "schema":"modelrig-agent4/campaign-list-query-cursor/v1",
            "statuses":[],"position":$position,"total":$total,"last_campaign_id":$last,"snapshot_sha256":"sha256:$a"
          }
        }""".trimIndent()
    }

    private fun timelineCursor(snapshot: String, sequence: Int, hash: String?): String = boundCursor(
        snapshot,
        "modelrig-agent4/campaign-timeline-query-cursor/v1",
        sequence,
        "entry_hash",
        hash,
    )

    private fun evidenceCursor(snapshot: String, sequence: Int, hash: String?): String = boundCursor(
        snapshot,
        "modelrig-agent4/campaign-evidence-query-cursor/v1",
        sequence,
        "record_hash",
        hash,
    )

    private fun boundCursor(snapshot: String, schema: String, sequence: Int, field: String, hash: String?): String {
        val value = if (hash == null) "null" else "\"$hash\""
        return """{
          "schema":"${Agent4SnapshotOperatorClient.SNAPSHOT_CURSOR_SCHEMA}",
          "snapshot_id":"$snapshot",
          "cursor":{"schema":"$schema","campaign_id":"campaign-1","sequence":$sequence,"$field":$value}
        }""".trimIndent()
    }

    private fun timelineEntry(sequence: Int, hash: String): String = """{
      "schema":"modelrig-agent4/campaign-timeline-entry/v1",
      "event":{"schema":"modelrig-agent4/campaign-event/v1","event_id":"event-$sequence","campaign_id":"campaign-1","kind":"recovered","sequence":$sequence,"occurred_at":"2026-08-10T18:00:0${sequence}Z","payload":{}},
      "evidence":[],"previous_hash":null,"entry_hash":"$hash"
    }""".trimIndent()

    private fun evidenceRecord(sequence: Int, hash: String): String = """{
      "schema":"modelrig-agent4/campaign-evidence-record/v1",
      "evidence_id":"evidence-$sequence","campaign_id":"campaign-1","sequence":$sequence,"recorded_at":"2026-08-10T18:01:00Z",
      "timeline_head_hash":"sha256:$b","related_event_id":"event-1","evidence":{"schema":"modelrig-agent4/campaign-evidence/v1","evidence_id":"evidence-$sequence","media_type":"application/json","location":"evidence/$sequence.json","sha256":"sha256:$a","size_bytes":10,"metadata":{}},
      "previous_hash":null,"record_hash":"$hash"
    }""".trimIndent()
}
