package dk.ternedal.modelrig.desktop.data

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

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
}
