package dk.ternedal.modelrig.logic

/**
 * Resolves a rig-profile token without knowing anything about Android SQLite or
 * the Android Keystore.
 *
 * A migration is deliberately returned as a separate result: the caller MUST
 * persist [RigProfileTokenResolution.Migration.envelope] successfully before
 * exposing [RigProfileTokenResolution.Migration.token] to the rest of the
 * application. This prevents a legacy plaintext credential from being used
 * while its at-rest upgrade quietly failed.
 */
sealed interface RigProfileTokenResolution {
    data class Ready(val token: String) : RigProfileTokenResolution
    data class Migration(val token: String, val envelope: String) : RigProfileTokenResolution
    data object Invalid : RigProfileTokenResolution
}

object RigProfileTokenResolver {
    fun resolve(
        raw: String,
        decrypt: (String) -> String,
        encrypt: (String) -> String,
    ): RigProfileTokenResolution = when (TokenFormat.classify(raw)) {
        StoredTokenForm.ENCRYPTED_V1 ->
            runCatching { decrypt(raw) }
                .fold(
                    onSuccess = { RigProfileTokenResolution.Ready(it) },
                    onFailure = { RigProfileTokenResolution.Invalid },
                )

        StoredTokenForm.LEGACY_PLAINTEXT ->
            RigProfileTokenResolution.Migration(
                token = raw,
                envelope = requireEnvelope(encrypt(raw)),
            )

        StoredTokenForm.OLD_FORMAT_CIPHERTEXT ->
            runCatching { decrypt(raw) }
                .fold(
                    onSuccess = { token ->
                        RigProfileTokenResolution.Migration(
                            token = token,
                            envelope = requireEnvelope(encrypt(token)),
                        )
                    },
                    onFailure = { RigProfileTokenResolution.Invalid },
                )
    }

    private fun requireEnvelope(value: String): String {
        check(TokenFormat.classify(value) == StoredTokenForm.ENCRYPTED_V1) {
            "Credential encryption did not return a recognised envelope"
        }
        return value
    }
}
