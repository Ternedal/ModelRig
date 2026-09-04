package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.Agent4OperatorClient
import dk.ternedal.modelrig.net.Agent4SnapshotOperatorClient
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent4SnapshotDetailPolicyTest {
    private val root = Agent4SnapshotOperatorClient.SnapshotId("a".repeat(64))
    private val other = Agent4SnapshotOperatorClient.SnapshotId("b".repeat(64))
    private val timelineHash = "sha256:${"c".repeat(64)}"
    private val evidenceHash = "sha256:${"d".repeat(64)}"

    @Test
    fun oneRootAndMatchingOverlapCanComposeReadyState() {
        Agent4SnapshotDetailPolicy.requireConsistent(
            detail = detail(root),
            timeline = timeline(root),
            evidence = evidence(root),
            verification = verification(root),
        )
    }

    @Test
    fun anyCrossResponseRootChangeFailsClosed() {
        val variants = listOf<() -> Unit>(
            { Agent4SnapshotDetailPolicy.requireConsistent(detail(root), timeline(other), evidence(root), verification(root)) },
            { Agent4SnapshotDetailPolicy.requireConsistent(detail(root), timeline(root), evidence(other), verification(root)) },
            { Agent4SnapshotDetailPolicy.requireConsistent(detail(root), timeline(root), evidence(root), verification(other)) },
        )
        variants.forEach { attempt ->
            val failure = runCatching(attempt).exceptionOrNull()
            assertTrue(failure is IllegalArgumentException)
        }
    }

    @Test
    fun immutableRootDoesNotReplaceA4_24OverlapChecks() {
        val badTimeline = timeline(root).copy(
            headCursor = cursor(root, Agent4SnapshotOperatorClient.CursorKind.TIMELINE, 2, timelineHash),
        )
        val badEvidence = evidence(root).copy(
            headCursor = cursor(root, Agent4SnapshotOperatorClient.CursorKind.EVIDENCE, 2, evidenceHash),
        )
        assertTrue(
            runCatching {
                Agent4SnapshotDetailPolicy.requireConsistent(detail(root), badTimeline, evidence(root), verification(root))
            }.exceptionOrNull() is IllegalArgumentException,
        )
        assertTrue(
            runCatching {
                Agent4SnapshotDetailPolicy.requireConsistent(detail(root), timeline(root), badEvidence, verification(root))
            }.exceptionOrNull() is IllegalArgumentException,
        )
    }

    private fun detail(snapshot: Agent4SnapshotOperatorClient.SnapshotId) =
        Agent4SnapshotOperatorClient.CampaignDetail(
            snapshot,
            Agent4OperatorClient.CampaignOverview(
                campaignId = "campaign-1",
                name = "Campaign",
                status = Agent4OperatorClient.CampaignStatus.RUNNING,
                timelineEntries = 1,
                eventEntries = 1,
                evidenceEntries = 1,
                latestTimelineHash = timelineHash,
                record = Agent4OperatorClient.CanonicalJson("{}"),
            ),
        )

    private fun timeline(snapshot: Agent4SnapshotOperatorClient.SnapshotId) =
        Agent4SnapshotOperatorClient.TimelinePage(
            snapshotId = snapshot,
            campaignId = "campaign-1",
            entries = emptyList(),
            startCursor = cursor(snapshot, Agent4SnapshotOperatorClient.CursorKind.TIMELINE, 0, null),
            nextCursor = cursor(snapshot, Agent4SnapshotOperatorClient.CursorKind.TIMELINE, 1, timelineHash),
            headCursor = cursor(snapshot, Agent4SnapshotOperatorClient.CursorKind.TIMELINE, 1, timelineHash),
            hasMore = false,
        )

    private fun evidence(snapshot: Agent4SnapshotOperatorClient.SnapshotId) =
        Agent4SnapshotOperatorClient.EvidencePage(
            snapshotId = snapshot,
            campaignId = "campaign-1",
            records = emptyList(),
            startCursor = cursor(snapshot, Agent4SnapshotOperatorClient.CursorKind.EVIDENCE, 0, null),
            nextCursor = cursor(snapshot, Agent4SnapshotOperatorClient.CursorKind.EVIDENCE, 1, evidenceHash),
            headCursor = cursor(snapshot, Agent4SnapshotOperatorClient.CursorKind.EVIDENCE, 1, evidenceHash),
            hasMore = false,
        )

    private fun verification(snapshot: Agent4SnapshotOperatorClient.SnapshotId) =
        Agent4SnapshotOperatorClient.EvidenceVerification(
            snapshotId = snapshot,
            campaignId = "campaign-1",
            recordCount = 1,
            headHash = evidenceHash,
            latestTimelineHeadHash = timelineHash,
        )

    private fun cursor(
        snapshot: Agent4SnapshotOperatorClient.SnapshotId,
        kind: Agent4SnapshotOperatorClient.CursorKind,
        sequence: Int,
        hash: String?,
    ) = Agent4SnapshotOperatorClient.SnapshotCursor(
        encoded = "${snapshot.value}:$kind:$sequence:${hash.orEmpty()}",
        snapshotId = snapshot,
        kind = kind,
        sequence = sequence,
        hash = hash,
    )
}
