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
        server.enqueue(
            operatorResponse(
                """{
                  "schema":"modelrig-agent4/operator-api/v1",
                  "campaigns":[{
                    "record":{
                      "schema":"modelrig-agent4/campaign-record/v1",
                      "spec":{"campaign_id":"campaign-1","name":"Rig audit"},
                      "state":{"campaign_id":"campaign-1","status":"running"}
                    },
                    "timeline_entries":4,
                    "event_entries":3,
                    "evidence_entries":2,
                    "latest_timeline_hash":"sha256:${"a".repeat(64)}"
                  }]
                }""".trimIndent(),
            ),
        )
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
            assertTrue(campaign.record.value.contains("campaign-1"))

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
    fun hashBoundCursorsAreReturnedOpaqueAndSentBackByTheClient() {
        val cursor = """{"campaign_id":"campaign-1","sequence":2,"hash":"${"b".repeat(64)}"}"""
        val server = MockWebServer()
        server.enqueue(
            operatorResponse(
                """{
                  "schema":"modelrig-agent4/operator-api/v1",
                  "page":{
                    "campaign_id":"campaign-1",
                    "entries":[],
                    "start_cursor":$cursor,
                    "next_cursor":$cursor,
                    "head_cursor":$cursor,
                    "has_more":true
                  }
                }""".trimIndent(),
            ),
        )
        server.enqueue(
            operatorResponse(
                """{
                  "schema":"modelrig-agent4/operator-api/v1",
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
            val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
            val first = client.timeline("campaign-1", limit = 1)
            assertTrue(first.hasMore)
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
            assertEquals("10", second.requestUrl?.queryParameter("limit"))
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
            assertEquals(null, result.latestTimelineHeadHash)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertTrue(request.requestUrl!!.encodedPath.contains("campaign%2Fwith%20space"))
            assertTrue(request.requestUrl!!.encodedPath.endsWith("/evidence/verification"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun authGrantAndProtocolFailuresAreDistinct() {
        val cases = listOf(
            Triple(401, "{\"error\":\"invalid token\"}", Agent4OperatorClient.ErrorKind.AUTH_REQUIRED),
            Triple(403, "{\"error\":\"agent4 read grant required\"}", Agent4OperatorClient.ErrorKind.GRANT_REQUIRED),
            Triple(404, "{\"detail\":\"agent4 operator resource not found\"}", Agent4OperatorClient.ErrorKind.NOT_FOUND),
            Triple(422, "{\"detail\":\"agent4 operator request rejected\"}", Agent4OperatorClient.ErrorKind.REQUEST_REJECTED),
            Triple(503, "{\"detail\":\"agent4 operator read unavailable\"}", Agent4OperatorClient.ErrorKind.UNAVAILABLE),
        )
        for ((status, body, expected) in cases) {
            val server = MockWebServer()
            server.enqueue(MockResponse().setResponseCode(status).setBody(body))
            server.start()
            try {
                val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
                val error = runCatching { client.listCampaigns() }.exceptionOrNull()
                assertTrue(error is Agent4OperatorClient.OperatorException)
                assertEquals(expected, (error as Agent4OperatorClient.OperatorException).kind)
                assertEquals(status, error.statusCode)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun successRequiresKnownMediaTypeSchemaStatusAndMatchingRecordIds() {
        val badResponses = listOf(
            MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody("{\"schema\":\"modelrig-agent4/operator-api/v1\",\"campaigns\":[]}"),
            operatorResponse("{\"schema\":\"unknown\",\"campaigns\":[]}"),
            operatorResponse(
                """{
                  "schema":"modelrig-agent4/operator-api/v1",
                  "campaigns":[{
                    "record":{
                      "schema":"modelrig-agent4/campaign-record/v1",
                      "spec":{"campaign_id":"c","name":"n"},
                      "state":{"campaign_id":"c","status":"future-state"}
                    },
                    "timeline_entries":0,"event_entries":0,"evidence_entries":0,
                    "latest_timeline_hash":null
                  }]
                }""".trimIndent(),
            ),
            operatorResponse(
                """{
                  "schema":"modelrig-agent4/operator-api/v1",
                  "campaigns":[{
                    "record":{
                      "schema":"modelrig-agent4/campaign-record/v1",
                      "spec":{"campaign_id":"c-1","name":"n"},
                      "state":{"campaign_id":"c-2","status":"running"}
                    },
                    "timeline_entries":0,"event_entries":0,"evidence_entries":0,
                    "latest_timeline_hash":null
                  }]
                }""".trimIndent(),
            ),
        )

        for (response in badResponses) {
            val server = MockWebServer()
            server.enqueue(response)
            server.start()
            try {
                val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
                val error = runCatching { client.listCampaigns() }.exceptionOrNull()
                assertTrue(error is Agent4OperatorClient.OperatorException)
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

    private fun operatorResponse(body: String): MockResponse = MockResponse()
        .setResponseCode(200)
        .setHeader("Content-Type", "$mediaType; charset=utf-8")
        .setBody(body)
}
