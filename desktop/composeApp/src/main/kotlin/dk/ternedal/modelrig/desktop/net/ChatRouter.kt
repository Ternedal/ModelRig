package dk.ternedal.modelrig.desktop.net

/** A chat answer tagged with which source produced it. */
data class ChatResult(val content: String, val source: Source) {
    enum class Source { LOCAL, CLOUD }
}

private const val LEGACY_LOCAL_IDENTITY =
    "Du er Kaliv, en personlig AI-assistent der kører på Anders' egen maskine. "

private const val LEGACY_LOCAL_TOOL_CLAIM =
    "- Du er en lokal assistent med værktøjer (bl.a. læse riggens status og " +
        "tilføje noter) når de er slået til. Kald et værktøj når det giver mening."

private const val CLOUD_EXECUTION_IDENTITY =
    "KØRSELSIDENTITET: Denne modelkørsel foregår via en cloud-model. " +
        "Den foregår ikke på brugerens egen maskine; påstå ikke at den gør."

private const val CLOUD_TOOL_BOUNDARY =
    "- Brug kun værktøjer, hvis den aktuelle kørselsvej eksplicit stiller dem til rådighed."

/**
 * Build the messages for the source that is actually about to execute.
 *
 * The normal desktop chat owns exactly one product system prompt per route. A
 * fallback therefore replaces the preferred route's system identity instead of
 * reusing it. Arbitrary configured prose is preserved. Only the two exact
 * product-owned legacy local claims are rewritten on cloud, so old defaults do
 * not instruct a cloud model to claim local execution.
 */
internal fun messagesForChatSource(
    source: ChatResult.Source,
    conversation: List<ChatMessage>,
    localSystem: String,
    cloudSystem: String,
): List<ChatMessage> {
    val configured = when (source) {
        ChatResult.Source.LOCAL -> localSystem.trim()
        ChatResult.Source.CLOUD -> cloudSystem.trim()
    }
    val system = when (source) {
        ChatResult.Source.LOCAL -> configured
        ChatResult.Source.CLOUD -> {
            val cloudSafe = configured
                .replace(LEGACY_LOCAL_IDENTITY, "Du er Kaliv, en personlig AI-assistent. ")
                .replace(LEGACY_LOCAL_TOOL_CLAIM, CLOUD_TOOL_BOUNDARY)
                .trim()
            listOf(CLOUD_EXECUTION_IDENTITY, cloudSafe)
                .filter { it.isNotBlank() }
                .joinToString("\n\n")
        }
    }

    return buildList {
        if (system.isNotBlank()) add(ChatMessage("system", system))
        addAll(conversation.filterNot { it.role == "system" })
    }
}

/**
 * Local-first router with Ollama Cloud fallback.
 *
 * Tries the local source (local Ollama, or the ModelRig backend). On a
 * pre-output failure it falls back to Ollama Cloud ONLY when autoFallback is on
 * (opt-in): local-first means the rig failing does not silently send the
 * conversation to cloud by default -- the error is surfaced and the user chooses.
 * When the user has explicitly preferred cloud (preferLocal=false), cloud is
 * their choice and local is the fallback.
 *
 * When route systems are supplied, each attempt receives messages rebuilt for
 * the source that is actually executing. This keeps execution identity truthful
 * across local -> cloud and cloud -> local fallback.
 */
class ChatRouter(
    private val local: OllamaClient?,
    private val localModel: String,
    private val cloud: OllamaClient?,
    private val cloudModel: String,
    private val preferLocal: Boolean = true,
    // D4 (25/07-2026): if this ever becomes automatic, it still may not carry
    // RAG document content to a cloud model. Consent has exactly two sources --
    // an explicit per-request allow_rag_cloud, or the operator's
    // KALIV_ALLOW_RAG_CLOUD -- and a router is not allowed to be a third.
    // When RAG matches, the turn stays local. See ROADMAP + the worker gate in
    // main.py (_rag_cloud_allowed), pinned by tests/worker_d4_auto_routing.py.
    private val autoFallback: Boolean = false,
    private val localSystem: String? = null,
    private val cloudSystem: String? = null,
) {
    private enum class Target { LOCAL, CLOUD }

    private fun messagesFor(target: Target, messages: List<ChatMessage>): List<ChatMessage> {
        val localPrompt = localSystem
        val cloudPrompt = cloudSystem
        if (localPrompt == null || cloudPrompt == null) return messages
        val source = when (target) {
            Target.LOCAL -> ChatResult.Source.LOCAL
            Target.CLOUD -> ChatResult.Source.CLOUD
        }
        return messagesForChatSource(source, messages, localPrompt, cloudPrompt)
    }

    fun chat(messages: List<ChatMessage>): ChatResult {
        val order =
            if (preferLocal) (if (autoFallback) listOf(Target.LOCAL, Target.CLOUD) else listOf(Target.LOCAL))
            else listOf(Target.CLOUD, Target.LOCAL)

        var lastError: Exception? = null
        for (t in order) {
            val client: OllamaClient?
            val model: String
            val src: ChatResult.Source
            when (t) {
                Target.LOCAL -> { client = local; model = localModel; src = ChatResult.Source.LOCAL }
                Target.CLOUD -> { client = cloud; model = cloudModel; src = ChatResult.Source.CLOUD }
            }
            if (client == null) continue
            try {
                return ChatResult(client.chat(model, messagesFor(t, messages)), src)
            } catch (e: Exception) {
                lastError = e
            }
        }
        throw OllamaException("all chat sources failed: ${lastError?.message ?: "none configured"}")
    }

    /**
     * Streaming variant. Falls back to the next source only if the current one
     * fails *before* emitting anything; a mid-stream failure is surfaced (we
     * don't restart and double the output). Returns the source that answered.
     */
    fun chatStream(messages: List<ChatMessage>, onDelta: (ChatResult.Source, String) -> Unit): ChatResult.Source {
        val order =
            if (preferLocal) (if (autoFallback) listOf(Target.LOCAL, Target.CLOUD) else listOf(Target.LOCAL))
            else listOf(Target.CLOUD, Target.LOCAL)

        var lastError: Exception? = null
        for (t in order) {
            val client: OllamaClient?
            val model: String
            val src: ChatResult.Source
            when (t) {
                Target.LOCAL -> { client = local; model = localModel; src = ChatResult.Source.LOCAL }
                Target.CLOUD -> { client = cloud; model = cloudModel; src = ChatResult.Source.CLOUD }
            }
            if (client == null) continue
            var emitted = 0
            try {
                client.chatStream(model, messagesFor(t, messages)) { d -> emitted++; onDelta(src, d) }
                return src
            } catch (e: Exception) {
                lastError = e
                if (emitted > 0) throw OllamaException("stream interrupted from $src: ${e.message}")
            }
        }
        throw OllamaException("all chat sources failed: ${lastError?.message ?: "none configured"}")
    }
}
