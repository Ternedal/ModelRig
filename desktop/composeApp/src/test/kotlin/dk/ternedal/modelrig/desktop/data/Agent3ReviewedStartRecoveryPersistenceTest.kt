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
    fun staleCallbackFromSecondStoreCannotClearReusedGeneration() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-aba-", ".db").toString()
        val rig = "https://aba-rig-${System.nanoTime()}.example"
        val authority = "{\"schema\":\"same-authority-${System.nanoTime()}\"}"

        DesktopChatDb(dbPath, TestProtector).use { dbA ->
            DesktopChatDb(dbPath, TestProtector).use { dbB ->
                val clearingStore = Agent3ReviewedStartRecoveryStore(dbA) { "token-a" }
                val staleStore = Agent3ReviewedStartRecoveryStore(dbB) { "token-a" }
                val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))

                assertTrue(clearingStore.reserve(rig, authority))
                assertEquals(authority, staleStore.read(rig))
                val originalEnvelope = requireNotNull(dbA.getSetting(key))
                val parts = originalEnvelope.split('\n', limit = 4)
                assertEquals(4, parts.size)
                assertEquals("kaliv-agent3-reviewed-start-storage/v3", parts[0])

                val replacementGeneration = if (parts[2] == "11111111-1111-4111-8111-111111111111") {
                    "22222222-2222-4222-8222-222222222222"
                } else {
                    "11111111-1111-4111-8111-111111111111"
                }
                val replacementEnvelope = listOf(parts[0], parts[1], replacementGeneration, parts[3]).joinToString("\n")

                // Store A completes G1 and retires only its own callback handle.
                assertTrue(clearingStore.clearIfMatches(rig, authority))
                assertNull(dbA.getSetting(key))

                // Another process now reserves byte-identical authority as G2.
                // Store B still owns a stale in-flight callback for G1.
                assertTrue(dbA.putRawSettingIfAbsent(key, replacementEnvelope))
                assertEquals(authority, staleStore.read(rig))

                // Observing G2 must not replace store B's instance-local G1 clear
                // authority. The stale callback therefore cannot delete G2.
                assertFalse(staleStore.clearIfMatches(rig, authority))
                assertEquals(replacementEnvelope, dbA.getSetting(key))

                // After the stale handle is dropped, a fresh read binds G2 and
                // can clear exactly that reservation generation.
                assertEquals(authority, staleStore.read(rig))
                assertTrue(staleStore.clearIfMatches(rig, authority))
                assertNull(dbA.getSetting(key))
            }
        }
    }

    @Test
    fun legacyV2CredentialBoundAuthorityStaysUnresolvedInsteadOfBeingAdopted() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-v2-", ".db").toString()
        val rig = "https://legacy-v2-${System.nanoTime()}.example"
        val encoded = "{\"schema\":\"legacy-v2-authority\"}"

        DesktopChatDb(dbPath, TestProtector).use { db ->
            val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
            val raw = "kaliv-agent3-reviewed-start-storage/v2\n${"a".repeat(64)}\n$encoded"
            db.putSetting(key, raw)
            val store = Agent3ReviewedStartRecoveryStore(db) { "token-a" }
            val visible = store.read(rig)
            assertNotNull(visible)
            assertNotEquals(encoded, visible)
            assertFalse(store.clearIfMatches(rig, encoded))
            assertEquals(raw, db.getSetting(key))
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
