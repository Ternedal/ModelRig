package dk.ternedal.modelrig.logic

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ConfirmationAuthorityTest {
    @Test
    fun exactRunStepAndDigestIdentifyOneAuthority() {
        val consumed = Agent3ConfirmationAuthority.capture("run-1", "step-1", "a".repeat(64))
        val same = Agent3ConfirmationAuthority.capture("run-1", "step-1", "a".repeat(64))
        val newDigest = Agent3ConfirmationAuthority.capture("run-1", "step-1", "b".repeat(64))
        val newStep = Agent3ConfirmationAuthority.capture("run-1", "step-2", "a".repeat(64))
        val newRun = Agent3ConfirmationAuthority.capture("run-2", "step-1", "a".repeat(64))

        assertTrue(isAgent3ConfirmationAuthorityConsumed(same, consumed))
        assertFalse(isAgent3ConfirmationAuthorityConsumed(newDigest, consumed))
        assertFalse(isAgent3ConfirmationAuthorityConsumed(newStep, consumed))
        assertFalse(isAgent3ConfirmationAuthorityConsumed(newRun, consumed))
        assertNotEquals(consumed, newDigest)
    }

    @Test
    fun incompleteAuthorityFailsClosedWithoutInventingIdentity() {
        assertNull(Agent3ConfirmationAuthority.capture(null, "step", "digest"))
        assertNull(Agent3ConfirmationAuthority.capture("run", " ", "digest"))
        assertNull(Agent3ConfirmationAuthority.capture("run", "step", ""))
        assertFalse(isAgent3ConfirmationAuthorityConsumed(null, null))
    }
}
