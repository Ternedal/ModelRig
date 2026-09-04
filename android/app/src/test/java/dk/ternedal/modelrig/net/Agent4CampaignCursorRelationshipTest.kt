package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Test

class Agent4CampaignCursorRelationshipTest {
    @Test
    fun campaignPagesRejectInconsistentCursorRelationships() {
        val statuses = listOf("running")
        val goodStart = campaignCursor(statuses, 0, 2, null, "a")
        val goodNext = campaignCursor(statuses, 1, 2, "campaign-1", "a")
        val goodHead = campaignCursor(statuses, 2, 2, "campaign-2", "a")
        val campaign = campaignOverview("campaign-1")

        val cases = listOf(
            campaignListResponse(
                campaigns = listOf(campaign),
                start = goodStart,
                next = campaignCursor(statuses, 1, 3, "campaign-1", "a"),
                head = goodHead,
                hasMore = true,
            ),
            campaignListResponse(
                campaigns = listOf(campaign),
                start = goodStart,
                next = campaignCursor(statuses, 1, 2, "campaign-1", "b"),
                head = goodHead,
                hasMore = true,
            ),
            campaignListResponse(
                campaigns = emptyList(),
                start = goodStart,
                next = goodNext,
                head = goodHead,
                hasMore = true,
            ),
            campaignListResponse(
                campaigns = listOf(campaign),
                start = goodStart,
                next = goodNext,
                head = goodHead,
                hasMore = false,
            ),
            campaignListResponse(
                campaigns = listOf(campaign),
                start = goodStart,
                next = campaignCursor(statuses, 1, 2, "different-campaign", "a"),
                head = goodHead,
                hasMore = true,
            ),
        )

        val server = MockWebServer()
        cases.forEach(server::enqueue)
        server.start()
        try {
            val client = Agent4OperatorClient(server.url("/").toString(), "device-token")
            repeat(cases.size) {
                val failure = runCatching {
                    client.listCampaigns(
                        statuses = setOf(Agent4OperatorClient.CampaignStatus.RUNNING),
                        limit = 1,
                    )
                }.exceptionOrNull()
                assertEquals(
                    Agent4OperatorClient.ErrorKind.PROTOCOL,
                    (failure as Agent4OperatorClient.OperatorException).kind,
                )
            }
        } finally {
            server.shutdown()
        }
    }

    private fun campaignListResponse(
        campaigns: List<String>,
        start: String,
        next: String,
        head: String,
        hasMore: Boolean,
    ): MockResponse = MockResponse()
        .setHeader("Content-Type", Agent4OperatorClient.MEDIA_TYPE)
        .setBody(
            """{
              "schema":"${Agent4OperatorClient.SCHEMA}",
              "campaigns":[${campaigns.joinToString(",")}],
              "start_cursor":$start,
              "next_cursor":$next,
              "head_cursor":$head,
              "has_more":$hasMore
            }""".trimIndent(),
        )

    private fun campaignCursor(
        statuses: List<String>,
        position: Int,
        total: Int,
        lastCampaignId: String?,
        digestChar: String,
    ): String {
        val encodedStatuses = statuses.joinToString(",") { "\"$it\"" }
        val last = lastCampaignId?.let { "\"$it\"" } ?: "null"
        return """{
          "schema":"${Agent4OperatorClient.CAMPAIGN_CURSOR_SCHEMA}",
          "statuses":[$encodedStatuses],
          "position":$position,
          "total":$total,
          "last_campaign_id":$last,
          "snapshot_sha256":"sha256:${digestChar.repeat(64)}"
        }""".trimIndent()
    }

    private fun campaignOverview(campaignId: String): String = """{
      "record":{
        "schema":"modelrig-agent4/campaign-record/v1",
        "spec":{"campaign_id":"$campaignId","name":"Campaign $campaignId"},
        "state":{"campaign_id":"$campaignId","status":"running"}
      },
      "timeline_entries":0,
      "event_entries":0,
      "evidence_entries":0,
      "latest_timeline_hash":null
    }""".trimIndent()
}
