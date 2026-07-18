from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected {label} exactly once in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


logic_path = Path(
    "android/app/src/main/java/dk/ternedal/modelrig/logic/CredentialPersistence.kt"
)
logic_path.write_text(
    '''package dk.ternedal.modelrig.logic

/**
 * Pure fail-closed boundary for durable encrypted credential writes.
 *
 * AndroidKeyStore encryption and SharedPreferences persistence can fail
 * independently. Callers only get true after both have completed, so UI code
 * never treats an asynchronous or rejected write as a saved credential.
 */
object CredentialPersistence {
    fun commit(write: () -> Boolean): Boolean =
        runCatching(write).getOrDefault(false)

    fun commitEncrypted(
        plaintext: String,
        encrypt: (String) -> String,
        persist: (String) -> Boolean,
    ): Boolean {
        if (plaintext.isEmpty()) return false

        val ciphertext = runCatching { encrypt(plaintext) }.getOrNull()
            ?.takeIf { it.isNotEmpty() }
            ?: return false
        return commit { persist(ciphertext) }
    }
}
''',
    encoding="utf-8",
)


test_path = Path(
    "android/app/src/test/java/dk/ternedal/modelrig/logic/CredentialPersistenceTest.kt"
)
test_path.write_text(
    '''package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CredentialPersistenceTest {
    @Test
    fun encryptionFailureNeverAttemptsPersistence() {
        var persisted = false

        val saved = CredentialPersistence.commitEncrypted(
            plaintext = "secret",
            encrypt = { error("keystore unavailable") },
            persist = { persisted = true; true },
        )

        assertFalse(saved)
        assertFalse(persisted)
    }

    @Test
    fun rejectedCommitIsReportedAsFailure() {
        var received: String? = null

        val saved = CredentialPersistence.commitEncrypted(
            plaintext = "secret",
            encrypt = { "cipher:$it" },
            persist = { received = it; false },
        )

        assertFalse(saved)
        assertEquals("cipher:secret", received)
    }

    @Test
    fun successRequiresEncryptionAndConfirmedCommit() {
        val calls = mutableListOf<String>()

        val saved = CredentialPersistence.commitEncrypted(
            plaintext = "secret",
            encrypt = { calls += "encrypt"; "ciphertext" },
            persist = { calls += "persist:$it"; true },
        )

        assertTrue(saved)
        assertEquals(listOf("encrypt", "persist:ciphertext"), calls)
    }

    @Test
    fun blankOrEmptyCiphertextFailsClosed() {
        var persisted = false

        assertFalse(
            CredentialPersistence.commitEncrypted(
                plaintext = "",
                encrypt = { "ciphertext" },
                persist = { persisted = true; true },
            ),
        )
        assertFalse(
            CredentialPersistence.commitEncrypted(
                plaintext = "secret",
                encrypt = { "" },
                persist = { persisted = true; true },
            ),
        )
        assertFalse(persisted)
    }

    @Test
    fun plainCommitExceptionsAreFailures() {
        assertFalse(CredentialPersistence.commit { error("disk unavailable") })
        assertFalse(CredentialPersistence.commit { false })
        assertTrue(CredentialPersistence.commit { true })
    }
}
''',
    encoding="utf-8",
)


token_path = Path(
    "android/app/src/main/java/dk/ternedal/modelrig/data/TokenStore.kt"
)
replace_once(
    token_path,
    '''import dk.ternedal.modelrig.logic.StoredCredentialRead
import dk.ternedal.modelrig.logic.StoredCredentialReader
''',
    '''import dk.ternedal.modelrig.logic.CredentialPersistence
import dk.ternedal.modelrig.logic.StoredCredentialRead
import dk.ternedal.modelrig.logic.StoredCredentialReader
''',
    "TokenStore imports",
)
replace_once(
    token_path,
    '''    var token: String?
        // Encrypted at rest like the cloud key. It grants full rig access
        // (chat, RAG, model + tool operations), so a legacy plaintext "token"
        // is migrated to "token_enc" before it is returned.
        get() = (rigCredentialStatus as? StoredCredentialRead.Ready)?.value
        set(v) {
            val e = prefs.edit()
            if (v.isNullOrEmpty()) e.remove("token_enc") else e.putString("token_enc", Crypto.encrypt(v))
            e.remove("token") // drop any legacy plaintext copy
            e.apply()
        }

''',
    '''    var token: String?
        // Encrypted at rest like the cloud key. It grants full rig access
        // (chat, RAG, model + tool operations), so a legacy plaintext "token"
        // is migrated to "token_enc" before it is returned.
        get() = (rigCredentialStatus as? StoredCredentialRead.Ready)?.value
        set(v) {
            val saved = if (v.isNullOrEmpty()) {
                CredentialPersistence.commit {
                    prefs.edit().remove("token_enc").remove("token").commit()
                }
            } else {
                CredentialPersistence.commitEncrypted(v, Crypto::encrypt) { encrypted ->
                    prefs.edit()
                        .putString("token_enc", encrypted)
                        .remove("token")
                        .commit()
                }
            }
            check(saved) { "Kunne ikke gemme rig-token sikkert" }
        }

    /**
     * Persist one usable rig connection as a single synchronous transaction.
     *
     * A null token means reconnect with the credential already on disk. A new
     * pairing/profile token is encrypted before the editor is committed, so URL,
     * active source and ciphertext either all land or none of them do.
     */
    fun saveRigConnection(url: String, token: String? = null): Boolean {
        val normalizedUrl = url.trim()
        if (normalizedUrl.isEmpty()) return false

        fun persist(encryptedToken: String?): Boolean {
            val editor = prefs.edit()
                .putString("base_url", normalizedUrl)
                .putString("chat_mode", "rig")
            if (encryptedToken != null) {
                editor.putString("token_enc", encryptedToken).remove("token")
            }
            return editor.commit()
        }

        if (token == null) return CredentialPersistence.commit { persist(null) }
        val normalizedToken = token.trim()
        return CredentialPersistence.commitEncrypted(
            normalizedToken,
            Crypto::encrypt,
        ) { encrypted -> persist(encrypted) }
    }

''',
    "rig credential setter",
)
replace_once(
    token_path,
    '''    /** Ollama Cloud API key, stored encrypted. Returns null unless ready. */
    var cloudKey: String?
        get() = (cloudCredentialStatus as? StoredCredentialRead.Ready)?.value
        set(v) {
            val e = prefs.edit()
            if (v.isNullOrEmpty()) e.remove("cloud_key_enc")
            else e.putString("cloud_key_enc", Crypto.encrypt(v))
            e.apply()
        }

''',
    '''    /** Ollama Cloud API key, stored encrypted. Returns null unless ready. */
    var cloudKey: String?
        get() = (cloudCredentialStatus as? StoredCredentialRead.Ready)?.value
        set(v) {
            val saved = if (v.isNullOrEmpty()) {
                CredentialPersistence.commit {
                    prefs.edit().remove("cloud_key_enc").commit()
                }
            } else {
                CredentialPersistence.commitEncrypted(v, Crypto::encrypt) { encrypted ->
                    prefs.edit().putString("cloud_key_enc", encrypted).commit()
                }
            }
            check(saved) { "Kunne ikke gemme cloud-nøgle sikkert" }
        }

    /**
     * Persist cloud credential, model and active source atomically.
     *
     * A null key deliberately keeps an already configured encrypted key while
     * updating model/source. A supplied key is encrypted before the transaction.
     */
    fun saveCloudConfiguration(key: String?, model: String): Boolean {
        val normalizedModel = model.trim().ifBlank { "gpt-oss:120b" }

        fun persist(encryptedKey: String?): Boolean {
            val editor = prefs.edit()
                .putString("cloud_model", normalizedModel)
                .putString("chat_mode", "cloud")
            if (encryptedKey != null) editor.putString("cloud_key_enc", encryptedKey)
            return editor.commit()
        }

        val normalizedKey = key?.trim()?.takeIf { it.isNotEmpty() }
            ?: return CredentialPersistence.commit { persist(null) }
        return CredentialPersistence.commitEncrypted(
            normalizedKey,
            Crypto::encrypt,
        ) { encrypted -> persist(encrypted) }
    }

''',
    "cloud credential setter",
)


ui_path = Path(
    "android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt"
)
replace_once(
    ui_path,
    '''                    onClick = {
                        runCatching {
                            if (key.isNotBlank()) store.cloudKey = key.trim()
                            store.cloudModel = model.trim().ifBlank { "gpt-oss:120b" }
                            store.chatMode = "cloud"
                        }.onSuccess { key = ""; configured = true; msg = null; onSaved() }
                            .onFailure { msg = "Kunne ikke gemme nøgle: ${it.message}" }
                    },
''',
    '''                    onClick = {
                        val saved = store.saveCloudConfiguration(
                            key = key.trim().takeIf { it.isNotBlank() },
                            model = model,
                        )
                        if (saved) {
                            key = ""
                            configured = true
                            msg = null
                            onSaved()
                        } else {
                            msg = "Kunne ikke gemme cloud-adgangen sikkert. Prøv igen."
                        }
                    },
''',
    "cloud save UI",
)
replace_once(
    ui_path,
    '''                onApply = { profile ->
                    store.baseUrl = profile.serverUrl
                    store.token = profile.deviceToken
                    store.chatMode = "rig"
                    baseUrl = profile.serverUrl
                    connected = true
                    onConnected()
                },
''',
    '''                onApply = { profile ->
                    if (store.saveRigConnection(profile.serverUrl, profile.deviceToken)) {
                        baseUrl = profile.serverUrl
                        connected = true
                        msg = null
                        onConnected()
                    } else {
                        msg = "Kunne ikke gemme den valgte rig sikkert."
                    }
                },
''',
    "rig profile apply UI",
)
replace_once(
    ui_path,
    '''                                if (ok) {
                                    store.baseUrl = url; store.chatMode = "rig"
                                    connected = true; reachable = true; onConnected()
                                } else {
                                    reachable = false
                                    msg = "Rig'en svarer ikke på $url. Tjek IP'en og at serveren kører."
                                }
''',
    '''                                if (ok) {
                                    val saved = store.saveRigConnection(url)
                                    if (saved) {
                                        connected = true; reachable = true; onConnected()
                                    } else {
                                        reachable = true
                                        msg = "Rig'en svarer, men den nye adresse kunne ikke gemmes sikkert."
                                    }
                                } else {
                                    reachable = false
                                    msg = "Rig'en svarer ikke på $url. Tjek IP'en og at serveren kører."
                                }
''',
    "rig reconnect UI",
)
replace_once(
    ui_path,
    '''                                res.onSuccess {
                                    store.baseUrl = url; store.token = it; store.chatMode = "rig"
                                    busy = false; connected = true; reachable = true; onConnected()
                                }.onFailure { msg = it.message ?: "Kunne ikke forbinde"; busy = false }
''',
    '''                                res.onSuccess { claimedToken ->
                                    val saved = store.saveRigConnection(url, claimedToken)
                                    busy = false
                                    if (saved) {
                                        connected = true; reachable = true; onConnected()
                                    } else {
                                        reachable = true
                                        msg = "Parringen lykkedes, men credential kunne ikke gemmes sikkert. Par igen."
                                    }
                                }.onFailure { msg = it.message ?: "Kunne ikke forbinde"; busy = false }
''',
    "rig pairing UI",
)


contract_path = Path("tests/android_credential_commit_contract.py")
contract_path.write_text(
    '''"""Android setup must only claim credentials after a confirmed durable commit.

Run: python tests/android_credential_commit_contract.py
"""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
store = (root / "android/app/src/main/java/dk/ternedal/modelrig/data/TokenStore.kt").read_text(encoding="utf-8")
ui = (root / "android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt").read_text(encoding="utf-8")

checks = {
    "rig connection has an explicit commit result": "fun saveRigConnection" in store,
    "cloud configuration has an explicit commit result": "fun saveCloudConfiguration" in store,
    "credential transactions use synchronous commit": store.count("return editor.commit()") >= 2,
    "setup no longer assigns rig token through apply-backed property": "store.token =" not in ui,
    "setup no longer assigns cloud key through apply-backed property": "store.cloudKey =" not in ui,
    "all rig setup paths use the transactional boundary": ui.count("store.saveRigConnection(") >= 3,
    "cloud setup uses the transactional boundary": "store.saveCloudConfiguration(" in ui,
    "UI branches on confirmed persistence": ui.count("if (saved)") >= 4,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")
print(f"\\n===== ANDROID CREDENTIAL COMMIT CONTRACT: {len(checks) - len(failed)} passed, {len(failed)} failed =====")
raise SystemExit(1 if failed else 0)
''',
    encoding="utf-8",
)
