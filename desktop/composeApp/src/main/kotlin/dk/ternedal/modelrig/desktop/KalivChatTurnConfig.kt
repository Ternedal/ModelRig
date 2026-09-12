package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.ChatResult

/**
 * Immutable execution authority captured synchronously when the user sends a turn.
 *
 * Settings remain editable while a request is running, but those edits belong to
 * the next turn. The active turn must not mix values read before/after suspension.
 *
 * Intentionally NOT a data class: deviceToken/cloudKey are credentials, so the
 * generated data-class toString()/copy surface would be an unnecessary leak risk.
 */
internal class KalivChatTurnConfig(
    val localUrl: String,
    val localPath: String,
    val localModel: String,
    val deviceToken: String,
    val cloudKey: String,
    val cloudModel: String,
    val localSystem: String,
    val cloudSystem: String,
    val preferLocal: Boolean,
    val autoCloudFallback: Boolean,
    val toolsMode: Boolean,
    val ragMode: Boolean,
    val ragSourceFilter: String?,
) {
    fun completedProvenance(source: ChatResult.Source): ChatConversationProvenance =
        completedChatConversationProvenance(source, localModel, cloudModel)

    /** RAG executes through the local worker with localModel, regardless of chat route preference. */
    fun ragConversationModel(): String = localModel
}
