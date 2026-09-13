package dk.ternedal.modelrig.desktop.data

import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
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
    fun authorityReservationIsCrossConnectionCasRigAndCredentialScoped() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-", ".db").toString()
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val first = "{\"schema\":\"authority-a-${System.nanoTime()}\"}"
        val second = "{\"schema\":\"authority-b-${System.nanoTime()}\"}"
        var token = "token-a"

        DesktopChatDb(dbPath, TestProtector).use { dbA ->
            DesktopChatDb(dbPath, TestProtector).use { dbB ->
                val storeA = Agent3ReviewedStartRecoveryStore(dbA) { token }
                val storeB = Agent3ReviewedStartRecoveryStore(dbB) { token }
                assertTrue(storeA.reserve(rigA, first))
                assertFalse(storeB.reserve(rigA, second))
                assertEquals(first, storeB.read("https://rig-a.example:8443"))
                assertFalse(storeB.clearIfMatches(rigA, second))
                assertEquals(first, storeA.read(rigA))
                assertNull(storeA.read(rigB))

                token = "token-b"
                val mismatched = storeB.read(rigA)
                assertNotNull(mismatched)
                assertNotEquals(first, mismatched)

                token = "token-a"
                assertEquals(first, storeA.read(rigA))
                assertTrue(storeA.clearIfMatches(rigA, first))
                assertNull(storeB.read(rigA))
            }
        }
    }

    @Test
    fun legacyUnboundAuthorityStaysUnresolvedAndIsNeverAdoptedByCurrentCredential() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-legacy-", ".db").toString()
        val rig = "https://legacy-rig-${System.nanoTime()}.example"
        val encoded = "{\"schema\":\"legacy-authority\"}"

        DesktopChatDb(dbPath, TestProtector).use { db ->
            val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
            db.putSetting(key, encoded)
            val store = Agent3ReviewedStartRecoveryStore(db) { "token-a" }
            val visible = store.read(rig)
            assertNotNull(visible)
            assertNotEquals(encoded, visible)
            assertFalse(store.clearIfMatches(rig, encoded))
            assertEquals(encoded, db.getSetting(key))
        }
    }
}
