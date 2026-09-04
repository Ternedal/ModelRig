package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.Agent4OperatorClient
import org.junit.Assert.assertThrows
import org.junit.Test

class Agent4DetailSnapshotPolicyTest {
    @Test
    fun acceptsMatchingNonEmptyHeads() {
        Agent4DetailSnapshotPolicy.requireConsistent(
            campaign = campaign(timelineEntries = 3, timelineHash = hash("a")),
            timelineHead = cursor(sequence = 3, hash = hash("a")),
            evidenceHead = cursor(sequence = 2, hash = hash("b")),
            verification = verification(recordCount = 2, headHash = hash("b")),
        )
    }

    @Test
    fun acceptsMatchingEmptyHeads() {
        Agent4DetailSnapshotPolicy.requireConsistent(
            campaign = campaign(timelineEntries = 0, timelineHash = null),
            timelineHead = cursor(sequence = 0, hash = null),
            evidenceHead = cursor(sequence = 0, hash = null),
            verification = verification(recordCount = 0, headHash = null),
        )
    }

    @Test
    fun rejectsTimelineCountDrift() {
        assertThrows(IllegalArgumentException::class.java) {
            Agent4DetailSnapshotPolicy.requireConsistent(
                campaign = campaign(timelineEntries = 2, timelineHash = hash("a")),
                timelineHead = cursor(sequence = 3, hash = hash("a")),
                evidenceHead = cursor(sequence = 0, hash = null),
                verification = verification(recordCount = 0, headHash = null),
            )
        }
    }

    @Test
    fun rejectsTimelineHashDrift() {
        assertThrows(IllegalArgumentException::class.java) {
            Agent4DetailSnapshotPolicy.requireConsistent(
                campaign = campaign(timelineEntries = 3, timelineHash = hash("a")),
                timelineHead = cursor(sequence = 3, hash = hash("b")),
                evidenceHead = cursor(sequence = 0, hash = null),
                verification = verification(recordCount = 0, headHash = null),
            )
        }
    }

    @Test
    fun rejectsEvidenceCountDrift() {
        assertThrows(IllegalArgumentException::class.java) {
            Agent4DetailSnapshotPolicy.requireConsistent(
                campaign = campaign(timelineEntries = 0, timelineHash = null),
                timelineHead = cursor(sequence = 0, hash = null),
                evidenceHead = cursor(sequence = 2, hash = hash("b")),
                verification = verification(recordCount = 3, headHash = hash("b")),
            )
        }
    }

    @Test
    fun rejectsEvidenceHashDrift() {
        assertThrows(IllegalArgumentException::class.java) {
            Agent4DetailSnapshotPolicy.requireConsistent(
                campaign = campaign(timelineEntries = 0, timelineHash = null),
                timelineHead = cursor(sequence = 0, hash = null),
                evidenceHead = cursor(sequence = 2, hash = hash("b")),
                verification = verification(recordCount = 2, headHash = hash("c")),
            )
        }
    }

    private fun campaign(
        timelineEntries: Int,
        timelineHash: String?,
    ) = Agent4OperatorClient.CampaignOverview(
        campaignId = "campaign-1",
        name = "Campaign 1",
        status = Agent4OperatorClient.CampaignStatus.RUNNING,
        timelineEntries = timelineEntries,
        eventEntries = timelineEntries,
        evidenceEntries = 0,
        latestTimelineHash = timelineHash,
        record = Agent4OperatorClient.CanonicalJson("{}"),
    )

    private fun cursor(
        sequence: Int,
        hash: String?,
    ) = Agent4OperatorClient.Cursor(
        encoded = "{}",
        sequence = sequence,
        hash = hash,
    )

    private fun verification(
        recordCount: Int,
        headHash: String?,
    ) = Agent4OperatorClient.EvidenceVerification(
        campaignId = "campaign-1",
        recordCount = recordCount,
        headHash = headHash,
        latestTimelineHeadHash = null,
    )

    private fun hash(seed: String) = "sha256:${seed.repeat(64)}"
}
