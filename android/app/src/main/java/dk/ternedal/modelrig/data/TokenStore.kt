package dk.ternedal.modelrig.data

import android.content.Context
import dk.ternedal.modelrig.logic.CredentialPersistence
import dk.ternedal.modelrig.logic.StoredCredentialRead
import dk.ternedal.modelrig.logic.StoredCredentialReader

/**
 * Local settings storage.
 *
 * Non-secret settings live in private SharedPreferences. Rig and cloud
 * credentials are encrypted at rest with AndroidKeyStore-backed AES-GCM.
 */
class TokenStore(context: Context) {
    private val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)

    // ---- rig (backend) ----
    var baseUrl: String?
        get() = prefs.getString("base_url", null)
        set(v) { prefs.edit().putString("base_url", v).apply() }

    /**
     * Explicit state for the stored rig credential.
     *
     * `Invalid` means ciphertext exists but cannot be decrypted with the current
     * Keystore. That is different from not being paired and must fail closed.
     */
    val rigCredentialStatus: StoredCredentialRead
        get() {
            prefs.getString("token_enc", null)?.let { encrypted ->
                return StoredCredentialReader.read(encrypted, Crypto::decrypt)
            }

            val legacy = prefs.getString("token", null)
                ?: return StoredCredentialRead.Missing
            if (legacy.isEmpty()) return StoredCredentialRead.Missing

            return try {
                val encrypted = Crypto.encrypt(legacy)
                val saved = prefs.edit()
                    .putString("token_enc", encrypted)
                    .remove("token")
                    .commit()
                if (saved) StoredCredentialRead.Ready(legacy)
                else StoredCredentialRead.Invalid
            } catch (_: Exception) {
                StoredCredentialRead.Invalid
            }
        }

    var token: String?
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

    var model: String
        get() = prefs.getString("model", "qwen2.5-coder:7b") ?: "qwen2.5-coder:7b"
        set(v) { prefs.edit().putString("model", v).apply() }

    // ---- cloud (Ollama Cloud, no rig needed) ----
    /** Explicit state for the encrypted Ollama Cloud API key. */
    val cloudCredentialStatus: StoredCredentialRead
        get() = StoredCredentialReader.read(
            prefs.getString("cloud_key_enc", null),
            Crypto::decrypt,
        )

    /** Ollama Cloud API key, stored encrypted. Returns null unless ready. */
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

    var cloudModel: String
        get() = prefs.getString("cloud_model", "gpt-oss:120b") ?: "gpt-oss:120b"
        set(v) { prefs.edit().putString("cloud_model", v).apply() }

    /** The cloud model used specifically for the voice (ASR->LLM->TTS) chain when
     *  "Stemme svarer via cloud" is on. Separate from cloudModel so voice can use
     *  a FASTER model (e.g. gpt-oss:120b) than a heavy text model (deepseek 671b),
     *  or vice versa. Falls back to cloudModel if never set, so existing behaviour
     *  is unchanged until the user picks a dedicated voice model. */
    var voiceCloudModel: String
        get() = prefs.getString("voice_cloud_model", null)?.ifBlank { null } ?: cloudModel
        set(v) { prefs.edit().putString("voice_cloud_model", v).apply() }

    /**
     * When true, a voice turn's LLM step is answered by the cloud model instead
     * of a local one. ASR and TTS still run on the rig -- only the thinking
     * moves. Off by default: the local path keeps the transcript in the house.
     */
    var voiceUsesCloud: Boolean
        get() = prefs.getBoolean("voice_uses_cloud", false)
        set(v) { prefs.edit().putBoolean("voice_uses_cloud", v).apply() }

    /**
     * When true, a rig chat that fails BEFORE emitting anything automatically
     * retries via the cloud model. Off by default: "local-first" means the rig
     * failing does NOT silently send the conversation to cloud -- the error is
     * shown and the user chooses. An attached image is never sent via fallback
     * even when this is on; it stays in the house.
     */
    var autoCloudFallback: Boolean
        get() = prefs.getBoolean("auto_cloud_fallback", false)
        set(v) { prefs.edit().putBoolean("auto_cloud_fallback", v).apply() }

    /**
     * D4 consent, PERSISTED (2a trin 1): may RAG document content leave the
     * house to a cloud model? Off by default -- local-first. Used by the
     * tools-with-RAG path today and by the useRagCloud route when trin 3-4
     * wire it. Until 1.58.45 this only existed as a dead remember{false} in
     * the UI: the consent literally could not be given.
     */
    var allowRagCloud: Boolean
        get() = prefs.getBoolean("allow_rag_cloud", false)
        set(v) { prefs.edit().putBoolean("allow_rag_cloud", v).apply() }

    /**
     * When true, speaking while Kaliv talks cuts her off (barge-in). Relies on
     * the platform's acoustic echo canceler when on speaker; a headset removes
     * the problem entirely. Off by default -- a false trigger mid-sentence is
     * more annoying than not having the feature.
     */
    var bargeInEnabled: Boolean
        get() = prefs.getBoolean("barge_in", false)
        set(v) { prefs.edit().putBoolean("barge_in", v).apply() }

    /**
     * Barge-in RMS threshold (0..32767 scale). 1500 was a guess made without a
     * device. Persisted so it can be tuned from the live readout instead of
     * requiring a rebuild.
     */
    var bargeInThreshold: Int
        get() = prefs.getInt("barge_in_rms", 1500)
        set(v) { prefs.edit().putInt("barge_in_rms", v.coerceIn(200, 8000)).apply() }

    /**
     * Kaliv Tools mode: route chat through the rig's tool layer, so the model
     * may propose an action. Off by default -- power is opted into, and the
     * rig has its own kill switch on top of this one.
     */
    var toolsMode: Boolean
        get() = prefs.getBoolean("tools_mode", false)
        set(v) { prefs.edit().putBoolean("tools_mode", v).apply() }

    /**
     * Dark (true) or light (false) UI. A manual choice, not the system theme,
     * so it stays put when Android auto-switches at sunset. Defaults to dark:
     * that is what every build before light mode looked like.
     */
    var darkMode: Boolean
        get() = prefs.getBoolean("dark_mode", true)
        set(v) { prefs.edit().putBoolean("dark_mode", v).apply() }

    /** "rig" or "cloud" — which source the chat screen uses. */
    var chatMode: String
        get() = prefs.getString("chat_mode", "rig") ?: "rig"
        set(v) { prefs.edit().putString("chat_mode", v).apply() }

    /** Optional system instruction sent as the first message, per source. */
    var rigSystem: String
        // A saved empty string (from before Kaliv had a default persona) also
        // means "use the default" -- otherwise existing installs stay hollow.
        get() = prefs.getString("rig_system", DEFAULT_SYSTEM)?.ifBlank { DEFAULT_SYSTEM } ?: DEFAULT_SYSTEM
        set(v) { prefs.edit().putString("rig_system", v).apply() }

    var cloudSystem: String
        get() = prefs.getString("cloud_system", DEFAULT_SYSTEM)?.ifBlank { DEFAULT_SYSTEM } ?: DEFAULT_SYSTEM
        set(v) { prefs.edit().putString("cloud_system", v).apply() }

    val hasRig: Boolean get() = rigCredentialStatus is StoredCredentialRead.Ready
    val hasCloud: Boolean get() = cloudCredentialStatus is StoredCredentialRead.Ready

    fun clearRig() { prefs.edit().remove("token_enc").remove("token").remove("base_url").apply() }
    fun clearCloud() { prefs.edit().remove("cloud_key_enc").apply() }
    fun clear() { prefs.edit().clear().apply() }
    companion object {
        // Kaliv's default persona. Without a system prompt an untethered instruct
        // model free-associates into an eager, emoji-drenched "helpful assistant"
        // that answers "hej" with three lines of rainbows and no substance -- the
        // hollow hygge-bot Anders saw on-device. This gives it a spine: grounded,
        // brief, Danish, honest, and aware of what it actually is. The user can
        // still replace it in Settings.
        const val DEFAULT_SYSTEM =
            "Du er Kaliv, en personlig AI-assistent der kører på Anders' egen maskine. " +
            "Du taler dansk, medmindre du bliver bedt om andet.\n\n" +
            "ABSOLUT VIGTIGST — tone:\n" +
            "- INGEN emojis. Slet ingen. Ikke 😊, ikke 🌟, ikke ✨, ikke 🌈. Aldrig.\n" +
            "- Ingen udråbstegn-begejstring. Ingen \"hyggeligt at høre fra dig\", ingen " +
            "\"jeg er her for dig\", ingen \"jeg er altid klar til at assistere dig\".\n" +
            "- Svar KORT. Et \"hej\" besvares med ét \"Hej\" eller \"Hej — hvad så?\", ikke mere. " +
            "Et \"tak\" besvares med \"Selv tak\" eller bare et nik i ord.\n" +
            "- Skriv som en kompetent voksen kollega, ikke som en kundeservice-bot.\n\n" +
            "Eksempel på HVORDAN du IKKE svarer:\n" +
            "  Bruger: hej\n" +
            "  DÅRLIGT: \"Hej! 😊 Det er så hyggeligt at høre fra dig! Er der noget " +
            "spændende på vej i dag? Jeg er altid klar til at assistere dig! 🌈✨\"\n" +
            "  GODT: \"Hej. Hvad kan jeg hjælpe med?\"\n\n" +
            "Indhold:\n" +
            "- Vær konkret og ærlig. Ved du ikke noget, så sig det. Find ikke på.\n" +
            "- Du er en lokal assistent med værktøjer (bl.a. læse riggens status og " +
            "tilføje noter) når de er slået til. Kald et værktøj når det giver mening — " +
            "beskriv det ikke bare, og pral ikke med evner du ikke bruger."
    }
}
