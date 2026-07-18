package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SourceAvailabilityTest {
    @Test
    fun noCredentialsRouteToSetup() {
        val availability = SourceAvailability.from(
            StoredCredentialRead.Missing,
            StoredCredentialRead.Missing,
        )

        assertFalse(availability.canChat)
        assertFalse(availability.hasInvalidCredentials)
        assertEquals(AppEntryDestination.SETUP, availability.entryDestination)
    }

    @Test
    fun eitherReadySourceRoutesToChat() {
        val rigReady = SourceAvailability.from(
            StoredCredentialRead.Ready("rig-secret"),
            StoredCredentialRead.Missing,
        )
        val cloudReady = SourceAvailability.from(
            StoredCredentialRead.Missing,
            StoredCredentialRead.Ready("cloud-secret"),
        )

        assertTrue(rigReady.canChat)
        assertTrue(cloudReady.canChat)
        assertEquals(AppEntryDestination.CHAT, rigReady.entryDestination)
        assertEquals(AppEntryDestination.CHAT, cloudReady.entryDestination)
    }

    @Test
    fun invalidCredentialsNeverCountAsConfigured() {
        val availability = SourceAvailability.from(
            StoredCredentialRead.Invalid,
            StoredCredentialRead.Missing,
        )

        assertFalse(availability.canChat)
        assertTrue(availability.hasInvalidCredentials)
        assertEquals(AppEntryDestination.SETUP, availability.entryDestination)
        assertEquals(CredentialCondition.INVALID, availability.rig)
    }

    @Test
    fun oneReadySourceStillAllowsChatWhenTheOtherIsInvalid() {
        val availability = SourceAvailability.from(
            StoredCredentialRead.Invalid,
            StoredCredentialRead.Ready("cloud-secret"),
        )

        assertTrue(availability.canChat)
        assertTrue(availability.hasInvalidCredentials)
        assertEquals(AppEntryDestination.CHAT, availability.entryDestination)
    }
}
