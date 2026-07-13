package dk.ternedal.modelrig.desktop.net

/** A chat answer tagged with which source produced it. */
data class ChatResult(val content: String, val source: Source) {
    enum class Source { LOCAL, CLOUD }
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
 */
class ChatRouter(
    private val local: OllamaClient?,
    private val localModel: String,
    private val cloud: OllamaClient?,
    private val cloudModel: String,
    private val preferLocal: Boolean = true,
    private val autoFallback: Boolean = false,
) {
    private enum class Target { LOCAL, CLOUD }

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
                return ChatResult(client.chat(model, messages), src)
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
                client.chatStream(model, messages) { d -> emitted++; onDelta(src, d) }
                return src
            } catch (e: Exception) {
                lastError = e
                if (emitted > 0) throw OllamaException("stream interrupted from $src: ${e.message}")
            }
        }
        throw OllamaException("all chat sources failed: ${lastError?.message ?: "none configured"}")
    }
}
