package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.Agent4OperatorClient

/**
 * Cross-request consistency checks for the initial Agent 4 detail read.
 *
 * Each transport response is already validated independently. This policy
 * prevents the UI from composing those valid responses into one Ready state
 * when timeline or evidence heads moved between the separate requests.
 */
internal object Agent4DetailSnapshotPolicy {
    fun requireConsistent(
        campaign: Agent4OperatorClient.CampaignOverview,
        timelineHead: Agent4OperatorClient.Cursor,
        evidenceHead: Agent4OperatorClient.Cursor,
        verification: Agent4OperatorClient.EvidenceVerification,
    ) {
        require(campaign.timelineEntries == timelineHead.sequence) {
            "Agent 4 campaign/timeline snapshot har modstridende antal"
        }
        require(campaign.latestTimelineHash == timelineHead.hash) {
            "Agent 4 campaign/timeline snapshot har modstridende head-hash"
        }
        require(verification.recordCount == evidenceHead.sequence) {
            "Agent 4 evidence snapshot har modstridende antal"
        }
        require(verification.headHash == evidenceHead.hash) {
            "Agent 4 evidence snapshot har modstridende head-hash"
        }
    }
}
