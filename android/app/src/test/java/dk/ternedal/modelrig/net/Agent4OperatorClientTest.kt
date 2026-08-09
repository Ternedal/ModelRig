package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent4OperatorClientTest {
    private val mediaType = Agent4OperatorClient.MEDIA_TYPE

    @Test
    fun listCampaignsUsesBackendBearerAndParsesCanonicalEnvelope() {
        val server = MockWebServer()
        server.enqueue(campaignListResponse(listOf(campaignOverview("campaign-1", "Rig audit", "running"))))
        server.start()
        try {
            val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
            val result = client.listCampaigns(
                statuses = setOf(
                    Agent4OperatorClient.CampaignStatus.RUNNING,
                    Agent4OperatorClient.CampaignStatus.PAUSED,
                ),
                limit = 25,
            )

            assertEquals(1, result.campaigns.size)
            val campaign = result.campaigns.single()
            assertEquals("campaign-1", campaign.campaignId)
            assertEquals("Rig audit", campaign.name)
            assertEquals(Agent4OperatorClient.CampaignStatus.RUNNING, campaign.status)
            assertEquals(4, campaign.timelineEntries)
            assertEquals(2, campaign.evidenceEntries)
            assertFalse(result.hasMore)

            val request = server.takeRequest()
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
            assertEquals(mediaType, request.getHeader("Accept"))
            assertTrue(request.getHeader("Cache-Control").orEmpty().contains("no-cache"))
            assertEquals("25", request.requestUrl?.queryParameter("limit"))
            assertEquals(
                listOf("paused", "running"),
                request.requestUrl?.queryParameterValues("status"),
            )
            assertEquals(
                "/api/v1/experimental/agent4/operator/campaigns",
                request.requestUrl?.encodedPath,
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun campaignListCursorsAreOpaqueAndRoundTripWithSnapshotHead() {
        val statuses = listOf("running")
        val start = campaignCursor(statuses, position = 0, total = 2, lastId = null, seed = "a")
        val next = campaignCursor(statuses, position = 1, total = 2, lastId = "campaign-2", seed = "a")
        val head = campaignCursor(statuses, position = 2, total = 2, lastId = "campaign-1", seed = "a")
        val server = MockWebServer()
        server.enqueue(
            campaignListResponse(
                campaigns = listOf(campaignOverview("campaign-2", "Two", "running")),
                start = start,
                next = next,
                head = head,
                hasMore = true,
            ),
        )
        server.enqueue(
            campaignListResponse(
                campaigns = listOf(campaignOverview("campaign-1", "One", "running")),
                start = next,
                next = head,
                head = head,
                hasMore = false,
            ),
        )
        server.start()
        try {
            val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
            val first = client.listCampaigns(
                statuses = setOf(Agent4OperatorClient.CampaignStatus.RUNNING),
                limit = 1,
            )
            assertTrue(first.hasMore)
            val second = client.listCampaigns(
                statuses = setOf(Agent4OperatorClient.CampaignStatus.RUNNING),
                after = first.nextCursor,
                snapshotHead = first.headCursor,
                limit = 1,
            )
            assertEquals("campaign-1", second.campaigns.single().campaignId)
            assertFalse(second.hasMore)

            server.takeRequest()
            val request = server.takeRequest()
            assertEquals(first.nextCursor.encoded, request.requestUrl?.queryParameter("after"))
            assertEquals(first.headCursor.encoded, request.requestUrl?.queryParameter("snapshot_head"))
            assertEquals(listOf("running"), request.requestUrl?.queryParameterValues("status"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun malformedCampaignCursorOrHalfPagingFailsClosed() {
        val wrongStatuses = campaignCursor(
            statuses = listOf("paused"),
            position = 0,
            total = 0,
            lastId = null,
            seed = "b",
        )
        val server = MockWebServer()
        server.enqueue(
            campaignListResponse(
                campaigns = emptyList(),
                start = wrongStatuses,
                next = wrongStatuses,
                head = wrongStatuses,
                hasMore = false,
            ),
        )
        server.start()
        try {
            val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
            val error = runCatching {
                client.listCampaigns(
                    statuses = setOf(Agent4OperatorClient.CampaignStatus.RUNNING),
                )
            }.exceptionOrNull()
            assertEquals(
                Agent4OperatorClient.ErrorKind.PROTOCOL,
                (error as Agent4OperatorClient.OperatorException).kind,
            )
            val half = runCatching {
                client.listCampaigns(after = Agent4OperatorClient.CampaignCursor("{}"))
            }.exceptionOrNull()
            assertEquals(
                Agent4OperatorClient.ErrorKind.PROTOCOL,
                (half as Agent4OperatorClient.OperatorException).kind,
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun hashBoundTimelineCursorsAreReturnedOpaqueAndSentBack() {
        val cursor = """{
          "schema":"modelrig-agent4/campaign-timeline-query-cursor/v1",
          "campaign_id":"campaign-1",
          "sequence":2,
          "entry_hash":"sha256:${"b".repeat(64)}"
        }""".trimIndent()
        val server = MockWebServer()
        server.enqueue(operatorResponse(timelinePage(cursor, true)))
        server.enqueue(operatorResponse(timelinePage(cursor, false)))
        server.start()
        try {
            val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
            val first = client.timeline("campaign-1", limit = 1)
            client.timeline(
                campaignId = "campaign-1",
                after = first.nextCursor,
                snapshotHead = first.headCursor,
                limit = 10,
            )
            server.takeRequest()
            val second = server.takeRequest()
            assertEquals(first.nextCursor.encoded, second.requestUrl?.queryParameter("after"))
            assertEquals(first.headCursor.encoded, second.requestUrl?.queryParameter("snapshot_head"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun verificationAndDynamicPathSegmentsStayReadOnlyAndEncoded() {
        val server = MockWebServer()
        server.enqueue(
            operatorResponse(
                """{
                  "schema":"modelrig-agent4/operator-api/v1",
                  "verification":{
                    "campaign_id":"campaign/with space",
                    "record_count":2,
                    "head_hash":"sha256:${"c".repeat(64)}",
                    "latest_timeline_head_hash":null
                  }
                }""".trimIndent(),
            ),
        )
        server.start()
        try {
            val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
            val result = client.evidenceVerification("campaign/with space")
            assertEquals(2, result.recordCount)
            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertTrue(request.requestUrl!!.encodedPath.contains("campaign%2Fwith%20space"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun authGrantRejectedAndUnavailableFailuresAreDistinct() {
        val cases = listOf(
            Triple(401, "{\"error\":\"invalid token\"}", Agent4OperatorClient.ErrorKind.AUTH_REQUIRED),
            Triple(403, "{\"error\":\"agent4 read grant required\"}", Agent4OperatorClient.ErrorKind.GRANT_REQUIRED),
            Triple(405, "{\"detail\":\"method not allowed\"}", Agent4OperatorClient.ErrorKind.REQUEST_REJECTED),
            Triple(422, "{\"detail\":\"agent4 operator request rejected\"}", Agent4OperatorClient.ErrorKind.REQUEST_REJECTED),
            Triple(503, "{\"detail\":\"agent4 operator read unavailable\"}", Agent4OperatorClient.ErrorKind.UNAVAILABLE),
        )
        for ((status, body, expected) in cases) {
            val server = MockWebServer()
            server.enqueue(MockResponse().setResponseCode(status).setBody(body))
            server.start()
            try {
                val error = runCatching {
                    Agent4OperatorClient(server.url("/").toString(), "device-token").listCampaigns()
                }.exceptionOrNull()
                assertEquals(expected, (error as Agent4OperatorClient.OperatorException).kind)
                assertEquals(status, error.statusCode)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun missingListRouteIsFeatureDisabledButMissingCampaignIsNotFound() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(404).setBody("404 page not found"))
        server.enqueue(MockResponse().setResponseCode(404).setBody("{\"detail\":\"agent4 operator resource not found\"}"))
        server.start()
        try {
            val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
            val disabled = runCatching { client.listCampaigns() }.exceptionOrNull()
            assertEquals(
                Agent4OperatorClient.ErrorKind.FEATURE_DISABLED,
                (disabled as Agent4OperatorClient.OperatorException).kind,
            )
            val missing = runCatching { client.campaign("missing") }.exceptionOrNull()
            assertEquals(
                Agent4OperatorClient.ErrorKind.NOT_FOUND,
                (missing as Agent4OperatorClient.OperatorException).kind,
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun successRequiresKnownMediaTypeSchemaStatusAndNumericFields() {
        val badResponses = listOf(
            MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(campaignListBody(emptyList())),
            operatorResponse("{\"schema\":\"unknown\",\"campaigns\":[]}"),
            operatorResponse(
                campaignListBody(
                    listOf(campaignOverview("c", "n", "future-state")),
                ),
            ),
            operatorResponse(
                campaignListBody(
                    listOf(campaignOverview("c", "n", "running", timelineEntries = "\"0\"")),
                ),
            ),
        )
        for (response in badResponses) {
            val server = MockWebServer()
            server.enqueue(response)
            server.start()
            try {
                val error = runCatching {
                    Agent4OperatorClient(server.url("/").toString(), "device-token").listCampaigns()
                }.exceptionOrNull()
                assertEquals(
                    Agent4OperatorClient.ErrorKind.PROTOCOL,
                    (error as Agent4OperatorClient.OperatorException).kind,
                )
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun invalidClientInputsFailBeforeNetwork() {
        val server = MockWebServer()
        server.start()
        try {
            val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
            val badLimit = runCatching { client.listCampaigns(limit = 0) }.exceptionOrNull()
            val badId = runCatching { client.campaign(" campaign-1") }.exceptionOrNull()
            assertEquals(
                Agent4OperatorClient.ErrorKind.PROTOCOL,
                (badLimit as Agent4OperatorClient.OperatorException).kind,
            )
            assertEquals(
                Agent4OperatorClient.ErrorKind.PROTOCOL,
                (badId as Agent4OperatorClient.OperatorException).kind,
            )
            assertFalse(server.requestCount > 0)
        } finally {
            server.shutdown()
        }
    }

    private fun campaignOverview(
        id: String,
        name: String,
        status: String,
        timelineEntries: String = "4",
    ): String = """{
      "record":{
        "schema":"modelrig-agent4/campaign-record/v1",
        "spec":{"campaign_id":"$id","name":"$name"},
        "state":{"campaign_id":"$id","status":"$status"}
      },
      "timeline_entries":$timelineEntries,
      "event_entries":3,
      "evidence_entries":2,
      "latest_timeline_hash":"sha256:${"a".repeat(64)}"
    }""".trimIndent()

    private fun campaignCursor(
        statuses: List<String>,
        position: Int,
        total: Int,
        lastId: String?,
        seed: String,
    ): String {
        val statusJson = statuses.joinToString(",") { "\"$it\"" }
        val lastJson = lastId?.let { "\"$it\"" } ?: "null"
        return """{
          "schema":"modelrig-agent4/campaign-list-query-cursor/v1",
          "statuses":[$statusJson],
          "position":$position,
          "total":$total,
          "last_campaign_id":$lastJson,
          "snapshot_sha256":"sha256:${seed.repeat(64)}"
        }""".trimIndent()
    }

    private fun campaignListResponse(
        campaigns: List<String>,
        start: String = campaignCursor(emptyList(), 0, campaigns.size, null, "d"),
        next: String = campaignCursor(
            emptyList(),
            campaigns.size,
            campaigns.size,
            campaigns.lastOrNull()?.let { Regex("campaign_id\\\":\\\"([^\\\"]+)").find(it)?.groupValues?.get(1) },
            "d",
        ),
        head: String = next,
        hasMore: Boolean = false,
    ): MockResponse = operatorResponse(
        campaignListBody(campaigns, start, next, head, hasMore),
    )

    private fun campaignListBody(
        campaigns: List<String>,
        start: String = campaignCursor(emptyList(), 0, campaigns.size, null, "d"),
        next: String = campaignCursor(emptyList(), 0, campaigns.size, null, "d"),
        head: String = next,
        hasMore: Boolean = false,
    ): String = """{
      "schema":"modelrig-agent4/operator-api/v1",
      "campaigns":[${campaigns.joinToString(",")}],
      "start_cursor":$start,
      "next_cursor":$next,
      "head_cursor":$head,
      "has_more":$hasMore
    }""".trimIndent()

    private fun timelinePage(cursor: String, hasMore: Boolean): String = """{
      "schema":"modelrig-agent4/operator-api/v1",
      "page":{
        "campaign_id":"campaign-1",
        "entries":[],
        "start_cursor":$cursor,
        "next_cursor":$cursor,
        "head_cursor":$cursor,
        "has_more":$hasMore
      }
    }""".trimIndent()

    private fun operatorResponse(body: String): MockResponse = MockResponse()
        .setResponseCode(200)
        .setHeader("Content-Type", "$mediaType; charset=utf-8")
        .setBody(body)
}
