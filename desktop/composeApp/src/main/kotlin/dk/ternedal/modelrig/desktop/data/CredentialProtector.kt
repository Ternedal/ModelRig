package dk.ternedal.modelrig.desktop.data

import com.sun.jna.platform.win32.Crypt32Util
import com.sun.jna.platform.win32.WinCrypt
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import java.nio.charset.StandardCharsets
import java.util.Base64

/**
 * Protects desktop credentials before they are written to persistent storage.
 *
 * The production implementation uses Windows DPAPI in current-user scope. The
 * interface keeps persistence tests platform-independent and makes it impossible
 * for the SQLite layer to silently fall back to plaintext.
 */
interface CredentialProtector {
    fun protect(plaintext: String): String
    fun unprotect(envelope: String): String

    fun isProtected(value: String): Boolean = value.startsWith(CREDENTIAL_ENVELOPE_PREFIX)
}

class CredentialProtectionException(message: String, cause: Throwable? = null) :
    IllegalStateException(message, cause)

/**
 * Windows DPAPI wrapper. No machine-scope flag is supplied, so Windows binds the
 * ciphertext to the current Windows user on this computer. UI is forbidden so
 * background persistence can never display a native credential prompt.
 */
class WindowsDpapiCredentialProtector(
    private val osName: String = System.getProperty("os.name", ""),
) : CredentialProtector {

    override fun protect(plaintext: String): String {
        if (plaintext.isEmpty()) return ""
        requireWindows()

        val clear = plaintext.toByteArray(StandardCharsets.UTF_8)
        val entropy = ENTROPY.copyOf()
        var encryptedForWipe: ByteArray? = null
        try {
            val encrypted = Crypt32Util.cryptProtectData(
                clear,
                entropy,
                WinCrypt.CRYPTPROTECT_UI_FORBIDDEN,
                DESCRIPTION,
                null,
            )
            encryptedForWipe = encrypted
            return CREDENTIAL_ENVELOPE_PREFIX + Base64.getEncoder().encodeToString(encrypted)
        } catch (e: Exception) {
            throw CredentialProtectionException("Windows could not protect the desktop credential", e)
        } catch (e: LinkageError) {
            throw CredentialProtectionException("Windows credential protection is unavailable", e)
        } finally {
            clear.fill(0)
            entropy.fill(0)
            encryptedForWipe?.fill(0)
        }
    }

    override fun unprotect(envelope: String): String {
        if (!isProtected(envelope)) {
            throw CredentialProtectionException("Unsupported desktop credential envelope")
        }
        requireWindows()

        val payload = envelope.removePrefix(CREDENTIAL_ENVELOPE_PREFIX)
        if (payload.isEmpty()) {
            throw CredentialProtectionException("Desktop credential envelope is empty")
        }

        val encrypted = try {
            Base64.getDecoder().decode(payload)
        } catch (e: IllegalArgumentException) {
            throw CredentialProtectionException("Desktop credential envelope is corrupt", e)
        }
        val entropy = ENTROPY.copyOf()
        var clearForWipe: ByteArray? = null
        try {
            val clear = Crypt32Util.cryptUnprotectData(
                encrypted,
                entropy,
                WinCrypt.CRYPTPROTECT_UI_FORBIDDEN,
                null,
            )
            clearForWipe = clear
            return decodeUtf8(clear)
        } catch (e: CredentialProtectionException) {
            throw e
        } catch (e: Exception) {
            throw CredentialProtectionException("Windows could not unlock the desktop credential", e)
        } catch (e: LinkageError) {
            throw CredentialProtectionException("Windows credential protection is unavailable", e)
        } finally {
            encrypted.fill(0)
            entropy.fill(0)
            clearForWipe?.fill(0)
        }
    }

    private fun requireWindows() {
        if (!osName.startsWith("Windows", ignoreCase = true)) {
            throw CredentialProtectionException("Desktop credential storage requires Windows DPAPI")
        }
    }

    private fun decodeUtf8(bytes: ByteArray): String = try {
        StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(bytes))
            .toString()
    } catch (e: Exception) {
        throw CredentialProtectionException("Unlocked desktop credential is not valid UTF-8", e)
    }

    private companion object {
        const val DESCRIPTION = "Kaliv desktop credential"
        val ENTROPY: ByteArray =
            "dk.ternedal.modelrig.desktop.credentials.v1".toByteArray(StandardCharsets.UTF_8)
    }
}

internal const val CREDENTIAL_ENVELOPE_PREFIX = "kaliv-dpapi:v1:"
internal const val CREDENTIAL_ENVELOPE_FAMILY_PREFIX = "kaliv-dpapi:"
