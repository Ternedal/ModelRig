package dk.ternedal.modelrig.desktop.data

import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path
import java.sql.DriverManager
import java.util.Base64
import kotlin.io.path.deleteIfExists
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class DesktopChatDbCredentialTest {

    @Test
    fun `new credentials are encrypted at rest and decrypt through the existing settings API`() =
        withDatabase { path, db, protector ->
            db.putSetting("deviceToken", "device-secret")
            db.putSetting("cloudKey", "cloud-secret")
            db.putSetting("localUrl", "http://127.0.0.1:8080")

            assertEquals("device-secret", db.getSetting("deviceToken"))
            assertEquals("cloud-secret", db.getSetting("cloudKey"))
            assertEquals("http://127.0.0.1:8080", db.getSetting("localUrl"))

            val storedToken = rawSetting(path, "deviceToken")!!
            val storedCloudKey = rawSetting(path, "cloudKey")!!
            assertNotEquals("device-secret", storedToken)
            assertNotEquals("cloud-secret", storedCloudKey)
            assertTrue(storedToken.startsWith(CREDENTIAL_ENVELOPE_PREFIX))
            assertTrue(storedCloudKey.startsWith(CREDENTIAL_ENVELOPE_PREFIX))
            assertEquals("http://127.0.0.1:8080", rawSetting(path, "localUrl"))
            assertEquals(2, protector.protectCalls)
        }

    @Test
    fun `legacy plaintext is migrated before it is returned`() =
        withDatabase { path, db, protector ->
            rawPutSetting(path, "deviceToken", "legacy-token")

            assertEquals("legacy-token", db.getSetting("deviceToken"))
            val migrated = rawSetting(path, "deviceToken")!!
            assertTrue(migrated.startsWith(CREDENTIAL_ENVELOPE_PREFIX))
            assertNotEquals("legacy-token", migrated)
            assertEquals(1, protector.protectCalls)

            // A second read decrypts the envelope; it does not re-migrate it.
            assertEquals("legacy-token", db.getSetting("deviceToken"))
            assertEquals(1, protector.protectCalls)
        }

    @Test
    fun `corrupt protected credentials fail closed and are never returned as text`() =
        withDatabase { path, db, _ ->
            val corrupt = CREDENTIAL_ENVELOPE_PREFIX + "not-valid-base64!"
            rawPutSetting(path, "cloudKey", corrupt)

            assertFailsWith<CredentialProtectionException> { db.getSetting("cloudKey") }
            assertEquals(corrupt, rawSetting(path, "cloudKey"))
        }

    @Test
    fun `unknown credential envelope versions fail closed`() =
        withDatabase { path, db, _ ->
            val futureEnvelope = "${CREDENTIAL_ENVELOPE_FAMILY_PREFIX}v2:opaque"
            rawPutSetting(path, "deviceToken", futureEnvelope)

            assertFailsWith<CredentialProtectionException> { db.getSetting("deviceToken") }
            assertEquals(futureEnvelope, rawSetting(path, "deviceToken"))
        }

    @Test
    fun `a protection failure never overwrites the database with plaintext`() {
        val path = Files.createTempFile("modelrig-credentials-failure-", ".db")
        try {
            DesktopChatDb(path.toString(), FailingProtector()).use { db ->
                assertFailsWith<CredentialProtectionException> {
                    db.putSetting("deviceToken", "must-not-be-written")
                }
                assertEquals(null, rawSetting(path, "deviceToken"))

                rawPutSetting(path, "deviceToken", "legacy-plaintext")
                assertFailsWith<CredentialProtectionException> { db.getSetting("deviceToken") }
                assertEquals("legacy-plaintext", rawSetting(path, "deviceToken"))
            }
        } finally {
            cleanup(path)
        }
    }

    @Test
    fun `empty credentials can be cleared without invoking native protection`() =
        withDatabase { path, db, protector ->
            db.putSetting("deviceToken", "")

            assertEquals("", db.getSetting("deviceToken"))
            assertEquals("", rawSetting(path, "deviceToken"))
            assertEquals(0, protector.protectCalls)
        }

    @Test
    fun `the production protector refuses non-Windows use before loading native DPAPI`() {
        val protector = WindowsDpapiCredentialProtector(osName = "Linux")

        assertFailsWith<CredentialProtectionException> { protector.protect("secret") }
        assertFailsWith<CredentialProtectionException> {
            protector.unprotect(CREDENTIAL_ENVELOPE_PREFIX + "AA==")
        }
    }

    private fun withDatabase(block: (Path, DesktopChatDb, FakeProtector) -> Unit) {
        val path = Files.createTempFile("modelrig-credentials-", ".db")
        val protector = FakeProtector()
        try {
            DesktopChatDb(path.toString(), protector).use { db -> block(path, db, protector) }
        } finally {
            cleanup(path)
        }
    }

    private fun rawSetting(path: Path, key: String): String? =
        DriverManager.getConnection("jdbc:sqlite:$path").use { conn ->
            conn.prepareStatement("SELECT value FROM setting WHERE key=?").use { st ->
                st.setString(1, key)
                st.executeQuery().use { rs -> if (rs.next()) rs.getString(1) else null }
            }
        }

    private fun rawPutSetting(path: Path, key: String, value: String) {
        DriverManager.getConnection("jdbc:sqlite:$path").use { conn ->
            conn.prepareStatement(
                "INSERT INTO setting(key, value) VALUES(?, ?) " +
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ).use { st ->
                st.setString(1, key)
                st.setString(2, value)
                st.executeUpdate()
            }
        }
    }

    private fun cleanup(path: Path) {
        path.deleteIfExists()
        Path.of("$path-journal").deleteIfExists()
        Path.of("$path-shm").deleteIfExists()
        Path.of("$path-wal").deleteIfExists()
    }

    private class FakeProtector : CredentialProtector {
        var protectCalls: Int = 0
            private set

        override fun protect(plaintext: String): String {
            protectCalls += 1
            val encoded = Base64.getEncoder().encodeToString(plaintext.toByteArray(StandardCharsets.UTF_8))
            return CREDENTIAL_ENVELOPE_PREFIX + encoded
        }

        override fun unprotect(envelope: String): String {
            if (!isProtected(envelope)) {
                throw CredentialProtectionException("Unsupported test envelope")
            }
            val bytes = try {
                Base64.getDecoder().decode(envelope.removePrefix(CREDENTIAL_ENVELOPE_PREFIX))
            } catch (e: IllegalArgumentException) {
                throw CredentialProtectionException("Corrupt test envelope", e)
            }
            return String(bytes, StandardCharsets.UTF_8)
        }
    }

    private class FailingProtector : CredentialProtector {
        override fun protect(plaintext: String): String =
            throw CredentialProtectionException("Synthetic protection failure")

        override fun unprotect(envelope: String): String =
            throw CredentialProtectionException("Synthetic unlock failure")
    }
}
