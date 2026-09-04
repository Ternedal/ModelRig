package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class Agent4SnapshotOperatorRaceTest {
    private val root = "a".repeat(64)
    private val otherRoot = "b".repeat(64)
    private val digest = "c".repeat(64)

    @Test
    fun recreatedClientContinuesCampaignPagingOnRetainedServerRoot() {
        val server = MockWebServer()
        val start = campaignCursor(root, position = 0, total = 2, lastId = null)
        val next = campaignCursor(root, position = 1, total = 2, lastId = "campaign-1")
        val head = campaignCursor(root, position = 2, total = 2, lastId = "campaign-2")
        server.enqueue(response(listBody(root, "campaign-1", start, next, head, true)))
        server.enqueue(response(listBody(root, "campaign-2", next, head, head, false)))
        server.start()
        try {
            val firstClient = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val first = firstClient.listCampaigns(limit = 1)

            // Process/UI recreation is allowed to discard every in-memory client
            // object. Correctness is carried only by the retained root id and the
            // server-owned cursors returned on the first page.
            val restartedClient = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val second = restartedClient.listCampaigns(
                snapshotId = first.snapshotId,
                after = first.nextCursor,
                snapshotHead = first.headCursor,
                limit = 1,
            )

            assertEquals(root, second.snapshotId.value)
            assertEquals("campaign-2", second.campaigns.single().campaignId)
            assertFalse(second.hasMore)
            server.takeRequest()
            val continuation = server.takeRequest()
            assertEquals(root, continuation.requestUrl?.queryParameter("snapshot_id"))
            assertEquals(first.nextCursor.encoded, continuation.requestUrl?.queryParameter("after"))
            assertEquals(first.headCursor.encoded, continuation.requestUrl?.queryParameter("snapshot_head"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun serverCursorBoundToDifferentRootFailsBeforeItCanBeReused() {
        val server = MockWebServer()
        server.enqueue(
            response(
                listBody(
                    root,
                    "campaign-1",
                    campaignCursor(root, 0, 1, null),
                    campaignCursor(otherRoot, 1, 1, "campaign-1"),
                    campaignCursor(root, 1, 1, "campaign-1"),
                    false,
                ),
            ),
        )
        server.start()
        try {
            val client = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val failure = runCatching { client.listCampaigns(limit = 1) }.exceptionOrNull()
                as Agent4SnapshotOperatorClient.OperatorException

            assertEquals(Agent4SnapshotOperatorClient.ErrorKind.PROTOCOL, failure.kind)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun malformedInnerCursorTypeFailsClosed() {
        val server = MockWebServer()
        val malformed = """{
          "schema":"${Agent4SnapshotOperatorClient.SNAPSHOT_CURSOR_SCHEMA}",
          "snapshot_id":"$root",
          "cursor":{
            "schema":"modelrig-agent4/campaign-timeline-query-cursor/v1",
            "campaign_id":"campaign-1",
            "sequence":1,
            "entry_hash":"sha256:$digest"
          }
        }""".trimIndent()
        server.enqueue(
            response(
                listBody(
                    root,
                    "campaign-1",
                    campaignCursor(root, 0, 1, null),
                    malformed,
                    campaignCursor(root, 1, 1, "campaign-1"),
                    false,
                ),
            ),
        )
        server.start()
        try {
            val client = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val failure = runCatching { client.listCampaigns(limit = 1) }.exceptionOrNull()
                as Agent4SnapshotOperatorClient.OperatorException

            assertEquals(Agent4SnapshotOperatorClient.ErrorKind.PROTOCOL, failure.kind)
        } finally {
            server.shutdown()
        }
    }

    private fun response(body: String): MockResponse = MockResponse()
        .setResponseCode(200)
        .setHeader("Content-Type", Agent4SnapshotOperatorClient.MEDIA_TYPE)
        .setBody(body)

    private fun listBody(
        snapshot: String,
        campaignId: String,
        start: String,
        next: String,
        head: String,
        hasMore: Boolean,
    ): String = """{
      "schema":"${Agent4SnapshotOperatorClient.SCHEMA}",
      "snapshot_id":"$snapshot",
      "campaigns":[${overview(campaignId)}],
      "start_cursor":$start,
      "next_cursor":$next,
      "head_cursor":$head,
      "has_more":$hasMore
    }""".trimIndent()

    private fun overview(id: String): String = """{
      "record":{
        "schema":"modelrig-agent4/campaign-record/v1",
        "spec":{"campaign_id":"$id","name":"Campaign $id","workflow":"agent3.write-pilot","created_at":"2026-08-10T18:00:00Z"},
        "state":{"campaign_id":"$id","status":"running","revision":1,"attempt":1,"updated_at":"2026-08-10T18:00:01Z","last_error":null,"pause_reason":null,"cancel_reason":null,"handoff":null,"last_checkpoint_id":null,"next_retry_at":null}
      },
      "timeline_entries":0,
      "event_entries":0,
      "evidence_entries":0,
      "latest_timeline_hash":null
    }""".trimIndent()

    private fun campaignCursor(snapshot: String, position: Int, total: Int, lastId: String?): String {
        val last = if (lastId == null) "null" else "\"$lastId\""
        return """{
          "schema":"${Agent4SnapshotOperatorClient.SNAPSHOT_CURSOR_SCHEMA}",
          "snapshot_id":"$snapshot",
          "cursor":{
            "schema":"modelrig-agent4/campaign-list-query-cursor/v1",
            "statuses":[],
            "position":$position,
            "total":$total,
            "last_campaign_id":$last,
            "snapshot_sha256":"sha256:$digest"
          }
        }""".trimIndent()
    }
}
