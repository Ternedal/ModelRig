package dk.ternedal.modelrig.data

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * At-rest encryption for the Ollama Cloud API key (which can cost real money if
 * leaked). Uses an AES-256-GCM key held in the AndroidKeyStore — the key material
 * never leaves the Keystore/TEE, and there is no external dependency (Jetpack
 * Security's EncryptedSharedPreferences is deprecated, so it is avoided).
 *
 * Stored form: "enc:v1:" + base64( 12-byte GCM IV || ciphertext+tag ). The
 * prefix makes ciphertext SELF-IDENTIFYING: a reader can distinguish "encrypted
 * value that failed to decrypt" (corrupt, or the Keystore key was lost after a
 * restore/device move -> INVALID, require re-pair) from "legacy plaintext that
 * predates encryption" (-> migrate). Without it, a failed decrypt was
 * indistinguishable from plaintext, and re-"migrating" garbage laundered it
 * into a valid-looking secret (audit 1.58.36). Prefixless values are accepted
 * on read for backward compatibility.
 */
internal object Crypto {
    // Defined in the pure layer (TokenFormat) and re-exported here so the
    // classification rule and the encoder can never disagree about the string.
    const val PREFIX = dk.ternedal.modelrig.logic.TokenFormat.PREFIX

    fun isEncrypted(v: String): Boolean = v.startsWith(PREFIX)

    private const val ALIAS = "modelrig_cloud_key"
    private const val KEYSTORE = "AndroidKeyStore"
    private const val TRANSFORM = "AES/GCM/NoPadding"
    private const val IV_LEN = 12
    private const val TAG_BITS = 128

    private fun secretKey(): SecretKey {
        val ks = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (ks.getEntry(ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        gen.init(
            KeyGenParameterSpec.Builder(
                ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return gen.generateKey()
    }

    fun encrypt(plain: String): String {
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val iv = cipher.iv
        val ct = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        val out = ByteArray(iv.size + ct.size)
        System.arraycopy(iv, 0, out, 0, iv.size)
        System.arraycopy(ct, 0, out, iv.size, ct.size)
        return PREFIX + Base64.encodeToString(out, Base64.NO_WRAP)
    }

    fun decrypt(data: String): String {
        val raw = Base64.decode(data.removePrefix(PREFIX), Base64.NO_WRAP)
        val iv = raw.copyOfRange(0, IV_LEN)
        val ct = raw.copyOfRange(IV_LEN, raw.size)
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(TAG_BITS, iv))
        return String(cipher.doFinal(ct), Charsets.UTF_8)
    }
}
