package dk.ternedal.modelrig.desktop.data

import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedStartRecoveryPersistenceTest {
    private object TestProtector : CredentialProtector {
        override fun protect(plaintext: String): String = "test:$plaintext"
        override fun unprotect(envelope: String): String = envelope.removePrefix("test:")
        override fun isProtected(value: String): Boolean = value.startsWith("test:")
    }

    @Test
    fun authoritySurvivesDatabaseReopenAndRemainsRigScoped() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-", ".db").toString()
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val encoded = "{\"schema\":\"test-authority\"}"

        DesktopChatDb(dbPath, TestProtector).use { db ->
            val store = Agent3ReviewedStartRecoveryStore(db)
            assertTrue(store.write(rigA, encoded))
        }

        DesktopChatDb(dbPath, TestProtector).use { reopened ->
            val store = Agent3ReviewedStartRecoveryStore(reopened)
            assertEquals(encoded, store.read("https://rig-a.example:8443"))
            assertNull(store.read(rigB))
            assertTrue(store.write(rigA, null))
        }

        DesktopChatDb(dbPath, TestProtector).use { reopenedAgain ->
            assertNull(Agent3ReviewedStartRecoveryStore(reopenedAgain).read(rigA))
        }
    }
}
