package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Test

class Agent4SnapshotCursorContractTest {
    private val root = "a".repeat(64)
    private val digest = "b".repeat(64)

    @Test
    fun campaignCursorStatusFilterMustMatchRequestBeforeReuse() {
        val server = MockWebServer()
        val cursor = campaignCursor(
            statuses = listOf("running"),
            position = 0,
            total = 1,
            lastId = null,
            snapshotHash = "sha256:$digest",
        )
        server.enqueue(response(listBody(cursor, cursor, cursor)))
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

    @Test
    fun campaignCursorMustRespectPositionLastIdentityAndDigestContract() {
        val server = MockWebServer()
        val malformed = campaignCursor(
            statuses = emptyList(),
            position = 1,
            total = 1,
            lastId = null,
            snapshotHash = digest,
        )
        server.enqueue(response(listBody(malformed, malformed, malformed)))
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

    @Test
    fun timelineCursorMustBelongToRequestedCampaign() {
        val server = MockWebServer()
        val cursor = timelineCursor(campaignId = "campaign-other", sequence = 0, hash = null)
        server.enqueue(
            response(
                """{
                  "schema":"${Agent4SnapshotOperatorClient.SCHEMA}",
                  "snapshot_id":"$root",
                  "page":{
                    "campaign_id":"campaign-1",
                    "entries":[],
                    "start_cursor":$cursor,
                    "next_cursor":$cursor,
                    "head_cursor":$cursor,
                    "has_more":false
                  }
                }""".trimIndent(),
            ),
        )
        server.start()
        try {
            val client = Agent4SnapshotOperatorClient(server.url("/").toString(), "token")
            val failure = runCatching {
                client.timeline(
                    "campaign-1",
                    Agent4SnapshotOperatorClient.SnapshotId(root),
                    limit = 1,
                )
            }.exceptionOrNull() as Agent4SnapshotOperatorClient.OperatorException

            assertEquals(Agent4SnapshotOperatorClient.ErrorKind.PROTOCOL, failure.kind)
        } finally {
            server.shutdown()
        }
    }

    private fun response(body: String): MockResponse = MockResponse()
        .setResponseCode(200)
        .setHeader("Content-Type", Agent4SnapshotOperatorClient.MEDIA_TYPE)
        .setBody(body)

    private fun listBody(start: String, next: String, head: String): String = """{
      "schema":"${Agent4SnapshotOperatorClient.SCHEMA}",
      "snapshot_id":"$root",
      "campaigns":[],
      "start_cursor":$start,
      "next_cursor":$next,
      "head_cursor":$head,
      "has_more":false
    }""".trimIndent()

    private fun campaignCursor(
        statuses: List<String>,
        position: Int,
        total: Int,
        lastId: String?,
        snapshotHash: String,
    ): String {
        val statusJson = statuses.joinToString(",") { "\"$it\"" }
        val last = if (lastId == null) "null" else "\"$lastId\""
        return """{
          "schema":"${Agent4SnapshotOperatorClient.SNAPSHOT_CURSOR_SCHEMA}",
          "snapshot_id":"$root",
          "cursor":{
            "schema":"modelrig-agent4/campaign-list-query-cursor/v1",
            "statuses":[$statusJson],
            "position":$position,
            "total":$total,
            "last_campaign_id":$last,
            "snapshot_sha256":"$snapshotHash"
          }
        }""".trimIndent()
    }

    private fun timelineCursor(campaignId: String, sequence: Int, hash: String?): String {
        val encodedHash = if (hash == null) "null" else "\"$hash\""
        return """{
          "schema":"${Agent4SnapshotOperatorClient.SNAPSHOT_CURSOR_SCHEMA}",
          "snapshot_id":"$root",
          "cursor":{
            "schema":"modelrig-agent4/campaign-timeline-query-cursor/v1",
            "campaign_id":"$campaignId",
            "sequence":$sequence,
            "entry_hash":$encodedHash
          }
        }""".trimIndent()
    }
}
