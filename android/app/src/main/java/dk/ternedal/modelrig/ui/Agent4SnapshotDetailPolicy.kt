package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.Agent4SnapshotOperatorClient

/**
 * A4-25e cross-request guard for the dormant Android v2 detail flow.
 *
 * The immutable server root is authoritative. Existing A4-24 overlap checks are
 * retained as defence-in-depth so a malformed server payload cannot compose a
 * superficially root-matching but internally contradictory Ready state.
 */
internal object Agent4SnapshotDetailPolicy {
    fun requireConsistent(
        detail: Agent4SnapshotOperatorClient.CampaignDetail,
        timeline: Agent4SnapshotOperatorClient.TimelinePage,
        evidence: Agent4SnapshotOperatorClient.EvidencePage,
        verification: Agent4SnapshotOperatorClient.EvidenceVerification,
    ) {
        val root = detail.snapshotId
        require(timeline.snapshotId == root) { "Agent 4 timeline skiftede snapshot_id" }
        require(evidence.snapshotId == root) { "Agent 4 evidence skiftede snapshot_id" }
        require(verification.snapshotId == root) { "Agent 4 verification skiftede snapshot_id" }
        require(timeline.campaignId == detail.campaign.campaignId) {
            "Agent 4 timeline tilhører en anden campaign"
        }
        require(evidence.campaignId == detail.campaign.campaignId) {
            "Agent 4 evidence tilhører en anden campaign"
        }
        require(verification.campaignId == detail.campaign.campaignId) {
            "Agent 4 verification tilhører en anden campaign"
        }
        require(detail.campaign.timelineEntries == timeline.headCursor.sequence) {
            "Agent 4 campaign/timeline snapshot har modstridende antal"
        }
        require(detail.campaign.latestTimelineHash == timeline.headCursor.hash) {
            "Agent 4 campaign/timeline snapshot har modstridende head-hash"
        }
        require(verification.recordCount == evidence.headCursor.sequence) {
            "Agent 4 evidence snapshot har modstridende antal"
        }
        require(verification.headHash == evidence.headCursor.hash) {
            "Agent 4 evidence snapshot har modstridende head-hash"
        }
    }
}
