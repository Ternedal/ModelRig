package dk.ternedal.modelrig.desktop.data

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNull

class DesktopTaskRunReferenceScopeTest {
    @Test
    fun sameNormalizedRigUsesSameRunReferenceKey() {
        assertEquals(
            DesktopChatDb.taskRunReferenceStorageKey("http://rig.local:8080"),
            DesktopChatDb.taskRunReferenceStorageKey("  http://rig.local:8080///  "),
        )
    }

    @Test
    fun differentRigsCannotShareRunReferenceKey() {
        assertNotEquals(
            DesktopChatDb.taskRunReferenceStorageKey("http://rig-a.local:8080"),
            DesktopChatDb.taskRunReferenceStorageKey("http://rig-b.local:8080"),
        )
    }

    @Test
    fun sameNormalizedRigUsesSameStartRecoveryKey() {
        assertEquals(
            DesktopChatDb.taskStartRecoveryStorageKey("http://rig.local:8080"),
            DesktopChatDb.taskStartRecoveryStorageKey("  http://rig.local:8080///  "),
        )
    }

    @Test
    fun differentRigsCannotShareStartRecoveryKey() {
        assertNotEquals(
            DesktopChatDb.taskStartRecoveryStorageKey("http://rig-a.local:8080"),
            DesktopChatDb.taskStartRecoveryStorageKey("http://rig-b.local:8080"),
        )
    }

    @Test
    fun missingRigHasNoStartRecoveryStorageAuthority() {
        assertNull(DesktopChatDb.taskStartRecoveryStorageKey(null))
        assertNull(DesktopChatDb.taskStartRecoveryStorageKey("   "))
    }
}
