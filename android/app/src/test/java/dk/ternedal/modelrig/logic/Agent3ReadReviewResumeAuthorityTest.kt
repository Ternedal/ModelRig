package dk.ternedal.modelrig.logic

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReadReviewResumeAuthorityTest {
    @Test
    fun exactRunAndCompletedStepDefineAuthority() {
        val current = Agent3ReadReviewResumeAuthority.capture("run-1", "step-a")
        assertTrue(isAgent3ReadReviewResumeConsumed(current, current))
        assertFalse(
            isAgent3ReadReviewResumeConsumed(
                Agent3ReadReviewResumeAuthority.capture("run-1", "step-b"),
                current,
            ),
        )
        assertFalse(
            isAgent3ReadReviewResumeConsumed(
                Agent3ReadReviewResumeAuthority.capture("run-2", "step-a"),
                current,
            ),
        )
    }

    @Test
    fun missingAuthorityFailsClosed() {
        assertNull(Agent3ReadReviewResumeAuthority.capture(null, "step-a"))
        assertNull(Agent3ReadReviewResumeAuthority.capture("run-1", null))
        assertNull(Agent3ReadReviewResumeAuthority.capture(" ", "step-a"))
        assertNull(Agent3ReadReviewResumeAuthority.capture("run-1", " "))
        assertTrue(isAgent3ReadReviewResumeConsumed(null, null))
        assertFalse(canAgent3ReadReviewResume(null, null, busy = false))
    }

    @Test
    fun presentationOnlyEnablesFreshExactAuthority() {
        val checkpointA = Agent3ReadReviewResumeAuthority.capture("run-1", "step-a")
        val checkpointB = Agent3ReadReviewResumeAuthority.capture("run-1", "step-b")
        assertTrue(canAgent3ReadReviewResume(checkpointA, null, busy = false))
        assertFalse(canAgent3ReadReviewResume(checkpointA, checkpointA, busy = false))
        assertFalse(canAgent3ReadReviewResume(checkpointA, null, busy = true))
        assertTrue(canAgent3ReadReviewResume(checkpointB, checkpointA, busy = false))
    }
}
