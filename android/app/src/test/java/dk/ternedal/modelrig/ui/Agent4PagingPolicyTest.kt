package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class Agent4PagingPolicyTest {
    @Test
    fun appendsContiguousTimelineAndEvidencePages() {
        val timeline = Agent4PagingPolicy.appendTimeline(
            listOf(timelineRow(1, "event-1", "a")),
            listOf(
                timelineRow(2, "event-2", "b"),
                timelineRow(3, "event-3", "c"),
            ),
        )
        assertEquals(listOf(1, 2, 3), timeline.map { it.sequence })

        val evidence = Agent4PagingPolicy.appendEvidence(
            listOf(evidenceRow(1, "evidence-1", "d")),
            listOf(
                evidenceRow(2, "evidence-2", "e"),
                evidenceRow(3, "evidence-3", "f"),
            ),
        )
        assertEquals(listOf(1, 2, 3), evidence.map { it.sequence })
    }

    @Test
    fun rejectsTimelineSequenceLossOverlapAndDuplicateIdentity() {
        val current = listOf(timelineRow(1, "event-1", "a"))
        assertThrows(IllegalArgumentException::class.java) {
            Agent4PagingPolicy.appendTimeline(
                current,
                listOf(timelineRow(3, "event-3", "c")),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            Agent4PagingPolicy.appendTimeline(
                current,
                listOf(timelineRow(1, "event-2", "b")),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            Agent4PagingPolicy.appendTimeline(
                current,
                listOf(timelineRow(2, "event-1", "b")),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            Agent4PagingPolicy.appendTimeline(
                current,
                listOf(timelineRow(2, "event-2", "a")),
            )
        }
    }

    @Test
    fun rejectsEvidenceSequenceLossOverlapAndDuplicateIdentity() {
        val current = listOf(evidenceRow(1, "evidence-1", "a"))
        assertThrows(IllegalArgumentException::class.java) {
            Agent4PagingPolicy.appendEvidence(
                current,
                listOf(evidenceRow(3, "evidence-3", "c")),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            Agent4PagingPolicy.appendEvidence(
                current,
                listOf(evidenceRow(1, "evidence-2", "b")),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            Agent4PagingPolicy.appendEvidence(
                current,
                listOf(evidenceRow(2, "evidence-1", "b")),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            Agent4PagingPolicy.appendEvidence(
                current,
                listOf(evidenceRow(2, "evidence-2", "a")),
            )
        }
    }

    private fun timelineRow(sequence: Int, eventId: String, hashSeed: String) =
        Agent4TimelineRow(
            sequence = sequence,
            kind = "started",
            occurredAt = "2026-08-09T10:00:00Z",
            eventId = eventId,
            entryHash = "sha256:${hashSeed.repeat(64)}",
            evidenceCount = 0,
        )

    private fun evidenceRow(sequence: Int, evidenceId: String, hashSeed: String) =
        Agent4EvidenceRow(
            sequence = sequence,
            recordedAt = "2026-08-09T10:00:00Z",
            evidenceId = evidenceId,
            mediaType = "application/json",
            location = "evidence/$evidenceId.json",
            sizeBytes = 1,
            recordHash = "sha256:${hashSeed.repeat(64)}",
        )
}
