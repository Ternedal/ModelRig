package dk.ternedal.modelrig.desktop.data

import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedStartRecoveryPersistenceTest {
    private object TestProtector : CredentialProtector {
        override fun protect(plaintext: String): String = "test:$plaintext"
        override fun unprotect(envelope: String): String = envelope.removePrefix("test:")
        override fun isProtected(value: String): Boolean = value.startsWith("test:")
    }

    @Test
    fun authoritySurvivesDatabaseReopenAndRemainsRigAndCredentialScoped() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-", ".db").toString()
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val encoded = "{\"schema\":\"test-authority\"}"
        var currentToken = "token-a"

        DesktopChatDb(dbPath, TestProtector).use { db ->
            val store = Agent3ReviewedStartRecoveryStore(db) { currentToken }
            assertTrue(store.write(rigA, encoded))
        }

        DesktopChatDb(dbPath, TestProtector).use { reopened ->
            val store = Agent3ReviewedStartRecoveryStore(reopened) { currentToken }
            assertEquals(encoded, store.read("https://rig-a.example:8443"))
            assertNull(store.read(rigB))

            currentToken = "token-b"
            val mismatched = store.read(rigA)
            assertNotNull(mismatched)
            assertNotEquals(encoded, mismatched)

            currentToken = "token-a"
            assertEquals(encoded, store.read(rigA))
            assertTrue(store.write(rigA, null))
        }

        DesktopChatDb(dbPath, TestProtector).use { reopenedAgain ->
            assertNull(Agent3ReviewedStartRecoveryStore(reopenedAgain) { currentToken }.read(rigA))
        }
    }

    @Test
    fun legacyUnboundAuthorityStaysNonemptyButCannotBeRecovered() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-legacy-", ".db").toString()
        val rig = "https://rig.example:8443"
        val encoded = "{\"schema\":\"test-authority\"}"

        DesktopChatDb(dbPath, TestProtector).use { db ->
            val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
            db.putSetting(key, encoded)
            val visible = Agent3ReviewedStartRecoveryStore(db) { "token-a" }.read(rig)
            assertNotNull(visible)
            assertNotEquals(encoded, visible)
        }
    }
}
