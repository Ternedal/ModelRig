package dk.ternedal.modelrig.logic

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceTurnOwnershipTest {
    @Test fun unchangedExistingConversationMayPersist() {
        assertTrue(mayPersistCompletedVoiceTurn(42L, 42L, 7, 7, false))
    }

    @Test fun freshConversationMayPersistBeforeItsIdIsAssigned() {
        assertTrue(mayPersistCompletedVoiceTurn(null, null, 0, 0, false))
    }

    @Test fun switchingToAnotherConversationRejectsLateTurn() {
        assertFalse(mayPersistCompletedVoiceTurn(42L, 99L, 7, 8, false))
        assertFalse(mayPersistCompletedVoiceTurn(null, 99L, 7, 8, false))
    }

    @Test fun switchingAwayAndBackStillRejectsLateTurn() {
        // The ID alone matches, but the navigation revision proves a switch.
        assertFalse(mayPersistCompletedVoiceTurn(42L, 42L, 7, 9, false))
        assertFalse(mayPersistCompletedVoiceTurn(null, null, 7, 9, false))
    }

    @Test fun cancellationAlwaysRejectsLateTurn() {
        assertFalse(mayPersistCompletedVoiceTurn(42L, 42L, 7, 7, true))
        assertFalse(mayPersistCompletedVoiceTurn(null, null, 0, 0, true))
    }
}
