package dk.ternedal.modelrig.data

import android.content.Context

/**
 * Local settings storage.
 *
 * - Rig token / baseUrl / model: plain SharedPreferences. Acceptable for a
 *   LAN-only device token (low value). Harden with DataStore + Keystore later.
 * - Cloud API key: encrypted at rest via the AndroidKeystore (see Crypto) — it
 *   can cost real money if leaked, so it gets stronger protection than the token.
 */
class TokenStore(context: Context) {
    private val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)

    // ---- rig (backend) ----
    var baseUrl: String?
        get() = prefs.getString("base_url", null)
        set(v) { prefs.edit().putString("base_url", v).apply() }

    var token: String?
        get() = prefs.getString("token", null)
        set(v) { prefs.edit().putString("token", v).apply() }

    var model: String
        get() = prefs.getString("model", "qwen2.5-coder:7b") ?: "qwen2.5-coder:7b"
        set(v) { prefs.edit().putString("model", v).apply() }

    // ---- cloud (Ollama Cloud, no rig needed) ----
    /** Ollama Cloud API key, stored encrypted. Returns null if unset or undecryptable. */
    var cloudKey: String?
        get() = prefs.getString("cloud_key_enc", null)?.let { runCatching { Crypto.decrypt(it) }.getOrNull() }
        set(v) {
            val e = prefs.edit()
            if (v.isNullOrEmpty()) e.remove("cloud_key_enc")
            else e.putString("cloud_key_enc", Crypto.encrypt(v))
            e.apply()
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

    val hasRig: Boolean get() = token != null
    val hasCloud: Boolean get() = prefs.getString("cloud_key_enc", null) != null

    fun clearRig() { prefs.edit().remove("token").remove("base_url").apply() }
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
