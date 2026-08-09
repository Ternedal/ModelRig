package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.Agent4OperatorClient

/** Fail-closed append rules for server-verified Agent 4 read pages. */
internal object Agent4PagingPolicy {
    fun appendCampaigns(
        current: List<Agent4OperatorClient.CampaignOverview>,
        next: List<Agent4OperatorClient.CampaignOverview>,
    ): List<Agent4OperatorClient.CampaignOverview> {
        if (next.isEmpty()) return current
        val ids = current.mapTo(mutableSetOf()) { it.campaignId }
        require(next.all { ids.add(it.campaignId) }) {
            "Agent 4 campaign-side gentager campaign-id"
        }
        return current + next
    }

    fun appendTimeline(
        current: List<Agent4TimelineRow>,
        next: List<Agent4TimelineRow>,
    ): List<Agent4TimelineRow> {
        if (next.isEmpty()) return current
        val expectedFirst = (current.lastOrNull()?.sequence ?: 0) + 1
        require(next.first().sequence == expectedFirst) {
            "Agent 4 timeline-side starter ikke ved forventet sequence"
        }
        require(next.zipWithNext().all { (left, right) -> right.sequence == left.sequence + 1 }) {
            "Agent 4 timeline-side har sequence-tab eller overlap"
        }
        val eventIds = current.mapTo(mutableSetOf()) { it.eventId }
        val hashes = current.mapTo(mutableSetOf()) { it.entryHash }
        require(next.all { eventIds.add(it.eventId) }) {
            "Agent 4 timeline-side gentager event-id"
        }
        require(next.all { hashes.add(it.entryHash) }) {
            "Agent 4 timeline-side gentager entry-hash"
        }
        return current + next
    }

    fun appendEvidence(
        current: List<Agent4EvidenceRow>,
        next: List<Agent4EvidenceRow>,
    ): List<Agent4EvidenceRow> {
        if (next.isEmpty()) return current
        val expectedFirst = (current.lastOrNull()?.sequence ?: 0) + 1
        require(next.first().sequence == expectedFirst) {
            "Agent 4 evidence-side starter ikke ved forventet sequence"
        }
        require(next.zipWithNext().all { (left, right) -> right.sequence == left.sequence + 1 }) {
            "Agent 4 evidence-side har sequence-tab eller overlap"
        }
        val evidenceIds = current.mapTo(mutableSetOf()) { it.evidenceId }
        val hashes = current.mapTo(mutableSetOf()) { it.recordHash }
        require(next.all { evidenceIds.add(it.evidenceId) }) {
            "Agent 4 evidence-side gentager evidence-id"
        }
        require(next.all { hashes.add(it.recordHash) }) {
            "Agent 4 evidence-side gentager record-hash"
        }
        return current + next
    }
}
